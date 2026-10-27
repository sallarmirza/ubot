from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.token_encryption import (
    EncryptedToken,
    TOKEN_CIPHER_PREFIX,
    _get_fernet,
    encrypt_legacy_oauth_tokens,
)
from db_manager import Base
from db_model import (
    Analytics,
    BusinessSetup,
    Comments,
    TargetChannel,
    TargetVideo,
    User,
    UserOAuth,
    Videos,
    YoutubeChannel,
)
from repositories.ai_repo import get_selected_videos_for_monitoring
from repositories.auth_repository import (
    delete_google_connection,
    delete_user_account,
    set_comment_monitoring_enabled,
)
from repositories.retention_repository import prune_expired_data
from schema.oauth_schema import GoogleOAuthError
from services import auth_service, google_oauth_service


class OAuthRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_key = settings.TOKEN_ENCRYPTION_KEY
        settings.TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode("ascii")
        _get_fernet.cache_clear()
        self.engine = create_engine("sqlite:///:memory:")
        event.listen(
            self.engine,
            "connect",
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        settings.TOKEN_ENCRYPTION_KEY = self.original_key
        _get_fernet.cache_clear()

    def test_encrypted_token_round_trip(self) -> None:
        token_type = EncryptedToken()
        stored = token_type.process_bind_param("oauth-secret", sqlite.dialect())

        self.assertTrue(stored.startswith(TOKEN_CIPHER_PREFIX))
        self.assertNotIn("oauth-secret", stored)
        self.assertEqual(
            token_type.process_result_value(stored, sqlite.dialect()),
            "oauth-secret",
        )

    def test_legacy_token_migration_is_idempotent(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE user_oauth"))
            connection.execute(
                text(
                    "CREATE TABLE user_oauth ("
                    "oauth_id INTEGER PRIMARY KEY, "
                    "access_token TEXT, refresh_token TEXT)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO user_oauth "
                    "(oauth_id, access_token, refresh_token) "
                    "VALUES (1, 'legacy-access', 'legacy-refresh')"
                )
            )

        self.assertEqual(encrypt_legacy_oauth_tokens(self.engine), 1)
        self.assertEqual(encrypt_legacy_oauth_tokens(self.engine), 0)
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT access_token, refresh_token "
                    "FROM user_oauth WHERE oauth_id = 1"
                )
            ).one()

        self.assertTrue(row.access_token.startswith(TOKEN_CIPHER_PREFIX))
        self.assertTrue(row.refresh_token.startswith(TOKEN_CIPHER_PREFIX))
        self.assertEqual(
            _get_fernet().decrypt(
                row.access_token[len(TOKEN_CIPHER_PREFIX) :].encode("ascii")
            ).decode("utf-8"),
            "legacy-access",
        )

    def test_disconnect_preserves_identity_and_removes_channel_data(self) -> None:
        with self.session_factory() as db:
            user, selected_video = self._create_account_graph(db, "stable-subject")
            user_id = user.user_id
            comment = Comments(
                selected_video_id=selected_video.selected_video_id,
                youtube_comment_id="youtube-comment",
                comment_text="viewer text",
            )
            db.add(comment)
            db.commit()

            delete_google_connection(db, user_id)
            db.commit()

            oauth = db.query(UserOAuth).filter_by(user_id=user_id).one()
            self.assertEqual(oauth.google_subject, "stable-subject")
            self.assertEqual(oauth.access_token, "")
            self.assertIsNone(oauth.refresh_token)
            self.assertFalse(oauth.comment_monitoring_enabled)
            self.assertIsNotNone(db.get(User, user_id))
            self.assertEqual(db.query(YoutubeChannel).filter_by(user_id=user_id).count(), 0)
            self.assertEqual(db.query(Comments).count(), 0)

    def test_comment_monitoring_only_runs_for_signed_in_accounts(self) -> None:
        with self.session_factory() as db:
            user, selected_video = self._create_account_graph(db, "monitor-subject")
            db.commit()

            self.assertEqual(get_selected_videos_for_monitoring(db), [])

            set_comment_monitoring_enabled(db, user.user_id, True)
            db.commit()
            self.assertEqual(
                get_selected_videos_for_monitoring(db),
                [
                    (
                        user.user_id,
                        f"channel-{user.user_id}",
                        f"video-{user.user_id}",
                    )
                ],
            )

            set_comment_monitoring_enabled(db, user.user_id, False)
            db.commit()
            self.assertEqual(get_selected_videos_for_monitoring(db), [])

    def test_account_deletion_removes_only_the_requested_users_data(self) -> None:
        with self.session_factory() as db:
            deleted_user, deleted_video = self._create_account_graph(db, "deleted")
            retained_user, retained_video = self._create_account_graph(db, "retained")
            deleted_user_id = deleted_user.user_id
            retained_user_id = retained_user.user_id
            db.add_all(
                [
                    Comments(
                        selected_video_id=deleted_video.selected_video_id,
                        youtube_comment_id="deleted-comment",
                        comment_text="private comment",
                    ),
                    Comments(
                        selected_video_id=retained_video.selected_video_id,
                        youtube_comment_id="retained-comment",
                        comment_text="other user's comment",
                    ),
                    Analytics(
                        user_id=deleted_user.user_id,
                        selected_video_id=deleted_video.selected_video_id,
                    ),
                    Analytics(
                        user_id=retained_user.user_id,
                        selected_video_id=retained_video.selected_video_id,
                    ),
                ]
            )
            db.commit()

            delete_user_account(db, deleted_user_id)
            db.commit()
            db.expire_all()

            self.assertIsNone(db.get(User, deleted_user_id))
            self.assertIsNotNone(db.get(User, retained_user_id))
            self.assertEqual(
                db.query(Comments).filter_by(youtube_comment_id="deleted-comment").count(),
                0,
            )
            self.assertEqual(
                db.query(Comments).filter_by(youtube_comment_id="retained-comment").count(),
                1,
            )
            self.assertEqual(db.query(Analytics).count(), 1)
            self.assertEqual(db.query(UserOAuth).count(), 1)
            self.assertEqual(db.query(YoutubeChannel).count(), 1)
            self.assertEqual(db.query(TargetChannel).count(), 1)
            self.assertEqual(db.query(BusinessSetup).count(), 1)
            self.assertEqual(db.query(Videos).count(), 1)
            self.assertEqual(db.query(TargetVideo).count(), 1)

    def test_retention_redacts_old_comments_and_deletes_only_old_analytics(self) -> None:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        old = cutoff - timedelta(seconds=1)
        recent = cutoff + timedelta(seconds=1)
        with self.session_factory() as db:
            user, selected_video = self._create_account_graph(db, "retention-subject")
            comments = [
                Comments(
                    selected_video_id=selected_video.selected_video_id,
                    youtube_comment_id="old-draft",
                    comment_text="old viewer text",
                    ai_reply="generated reply",
                    reply_status="draft",
                    created_at=old,
                ),
                Comments(
                    selected_video_id=selected_video.selected_video_id,
                    youtube_comment_id="old-posting",
                    comment_text="posting text",
                    reply_status="posting",
                    created_at=old,
                ),
                Comments(
                    selected_video_id=selected_video.selected_video_id,
                    youtube_comment_id="old-unknown",
                    comment_text="unknown text",
                    reply_status="unknown",
                    created_at=old,
                ),
                Comments(
                    selected_video_id=selected_video.selected_video_id,
                    youtube_comment_id="recent-draft",
                    comment_text="recent viewer text",
                    created_at=recent,
                ),
            ]
            old_analytics = Analytics(
                user_id=user.user_id,
                selected_video_id=selected_video.selected_video_id,
                created_at=old,
            )
            recent_analytics = Analytics(
                user_id=user.user_id,
                selected_video_id=selected_video.selected_video_id,
                created_at=recent,
            )
            db.add_all([*comments, old_analytics, recent_analytics])
            db.commit()

            result = prune_expired_data(db, cutoff)
            db.commit()

            self.assertEqual(result, {"comments_redacted": 1, "analytics_deleted": 1})
            redacted = db.query(Comments).filter_by(youtube_comment_id="old-draft").one()
            self.assertEqual(redacted.reply_status, "retained")
            self.assertEqual(redacted.comment_text, "")
            self.assertIsNone(redacted.ai_reply)
            self.assertEqual(
                db.query(Comments).filter_by(youtube_comment_id="old-posting").one().comment_text,
                "posting text",
            )
            self.assertEqual(
                db.query(Comments).filter_by(youtube_comment_id="old-unknown").one().comment_text,
                "unknown text",
            )
            self.assertEqual(
                db.query(Comments).filter_by(youtube_comment_id="recent-draft").one().comment_text,
                "recent viewer text",
            )
            self.assertEqual(db.query(Analytics).count(), 1)

    def test_disconnect_keeps_local_data_if_google_revocation_fails(self) -> None:
        with self.session_factory() as db:
            user, _ = self._create_account_graph(db, "disconnect-subject")
            db.commit()
            with (
                patch.object(
                    google_oauth_service,
                    "revoke_token",
                    side_effect=GoogleOAuthError("provider unavailable"),
                ),
                patch("services.auth_service.repo.delete_google_connection") as delete,
            ):
                with self.assertRaises(HTTPException) as raised:
                    auth_service.disconnect_google(db, user.user_id)

            self.assertEqual(raised.exception.status_code, 502)
            delete.assert_not_called()
            self.assertIsNotNone(db.get(User, user.user_id))

    def test_google_revoke_accepts_already_invalid_token(self) -> None:
        response = Mock(status_code=400)
        response.json.return_value = {"error": "invalid_token"}
        client = Mock()
        client.post.return_value = response
        with patch.object(google_oauth_service, "get_sync_http_client", return_value=client):
            google_oauth_service.revoke_token("expired-token")

        client.post.assert_called_once()
        self.assertEqual(client.post.call_args.kwargs["data"], {"token": "expired-token"})

    @staticmethod
    def _create_account_graph(db, google_subject: str):
        user = User()
        db.add(user)
        db.flush()
        db.add(
            UserOAuth(
                user_id=user.user_id,
                google_subject=google_subject,
                access_token="access-secret",
                refresh_token="refresh-secret",
            )
        )
        channel = YoutubeChannel(
            user_id=user.user_id,
            youtube_channel_id=f"channel-{user.user_id}",
            channel_name="Channel",
        )
        db.add(channel)
        db.flush()
        target_channel = TargetChannel(
            user_id=user.user_id,
            channel_id=channel.channel_id,
        )
        db.add(target_channel)
        db.flush()
        db.add(
            BusinessSetup(
                user_id=user.user_id,
                target_channel_id=target_channel.target_channel_id,
                business_name="Business",
                business_services="Services",
            )
        )
        video = Videos(
            user_id=user.user_id,
            target_channel_id=target_channel.target_channel_id,
            youtube_video_id=f"video-{user.user_id}",
            title="Video",
        )
        db.add(video)
        db.flush()
        selected_video = TargetVideo(
            user_id=user.user_id,
            video_id=video.video_id,
        )
        db.add(selected_video)
        db.flush()
        return user, selected_video


if __name__ == "__main__":
    unittest.main()
