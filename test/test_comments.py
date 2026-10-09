"""Regression coverage for comment loading against an existing SQLite database."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_manager as database_module
from core.dependencies import get_current_user
from db_manager import Base
from db_model import Comments, TargetChannel, TargetVideo, User, Videos, YoutubeChannel
from router.comments_fetching_router import router
from services import coments_fetching_service as comments_service


CHANNEL_ID = "UCGqQnXpVgoN7hZ8HFb6Ochw"
VIDEO_ID = "J-NySuH-qBI"


class CommentsEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            user = User()
            db.add(user)
            db.flush()
            self.user_id = user.user_id
            channel = YoutubeChannel(
                user_id=self.user_id,
                youtube_channel_id=CHANNEL_ID,
                channel_name="Test channel",
                channel_subscribers=0,
                channel_views=0,
            )
            db.add(channel)
            db.flush()
            target = TargetChannel(user_id=self.user_id, channel_id=channel.channel_id)
            db.add(target)
            db.flush()
            video = Videos(
                user_id=self.user_id,
                target_channel_id=target.target_channel_id,
                youtube_video_id=VIDEO_ID,
                title="Test video",
            )
            db.add(video)
            db.flush()
            db.add(TargetVideo(user_id=self.user_id, video_id=video.video_id))
            db.commit()

        app = FastAPI()
        app.include_router(router)

        def get_test_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[database_module.db_manager.get_db] = get_test_db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            user_id=self.user_id
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def get_comments(self, payload, *, status=200, video_id=VIDEO_ID):
        request = httpx.Request("GET", "https://www.googleapis.com/youtube/v3/commentThreads")
        response = httpx.Response(status, json=payload, request=request)
        fake_client = SimpleNamespace(get=lambda *args, **kwargs: response)
        with patch.object(comments_service, "_get_access_token", return_value="test-token"), patch.object(
            comments_service, "get_sync_http_client", return_value=fake_client
        ):
            return self.client.get(f"/comments/{CHANNEL_ID}/{video_id}")

    def test_comments_are_persisted_and_retry_does_not_duplicate(self):
        payload = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "id": "comment-1",
                            "snippet": {
                                "textDisplay": "Nice video",
                                "publishedAt": "2026-10-08T12:30:00Z",
                            },
                        }
                    }
                }
            ]
        }
        for _ in range(2):
            result = self.get_comments(payload)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()[0]["youtube_comment_id"], "comment-1")
        with self.sessions() as db:
            self.assertEqual(db.query(Comments).count(), 1)

    def test_empty_comments_are_successful(self):
        result = self.get_comments({"items": []})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), [])

    def test_missing_selected_video_is_404(self):
        result = self.get_comments({"items": []}, video_id="not-selected")
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.json()["detail"], "Selected video not found")

    def test_known_google_errors_remain_controlled(self):
        for reason, expected_status in (
            ("commentsDisabled", 422),
            ("insufficientPermissions", 403),
        ):
            with self.subTest(reason=reason):
                result = self.get_comments(
                    {"error": {"code": 403, "errors": [{"reason": reason}]}},
                    status=403,
                )
                self.assertEqual(result.status_code, expected_status)


class LegacyCommentsMigrationTests(unittest.TestCase):
    def test_existing_comments_table_gets_parent_comment_id(self):
        with patch.object(database_module, "DB_URL", "sqlite:///:memory:"):
            manager = database_module.DBManager()
        with manager.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE comments ("
                    "comment_id INTEGER PRIMARY KEY, selected_video_id INTEGER NOT NULL, "
                    "youtube_comment_id VARCHAR(100) NOT NULL, "
                    "comment_text VARCHAR(800) NOT NULL, ai_reply VARCHAR(800), "
                    "is_replied BOOLEAN NOT NULL DEFAULT 0, "
                    "created_at DATETIME, updated_at DATETIME)"
                )
            )
        manager.create_tables()
        with manager.engine.connect() as connection:
            columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(comments)"))
            }
        self.assertIn("parent_comment_id", columns)
        manager.engine.dispose()


if __name__ == "__main__":
    unittest.main()
