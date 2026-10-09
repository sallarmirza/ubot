"""End-to-end API tests for automatic AI generation and YouTube reply posting."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.dependencies import get_current_user
from db_manager import Base, db_manager
from db_model import BusinessSetup, Comments, TargetChannel, TargetVideo, User, Videos, YoutubeChannel
from router.ai_router import router
from services import ai_service


CHANNEL_ID = "UC-bulk-test"
VIDEO_ID = "video-bulk-test"
PATH = f"/ai/{CHANNEL_ID}/{VIDEO_ID}/generate-and-post-replies"


class BulkReplyEndpointTests(unittest.TestCase):
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
            db.add(
                BusinessSetup(
                    user_id=self.user_id,
                    target_channel_id=target.target_channel_id,
                    business_name="Example brand",
                    business_services="Useful services",
                    business_rules="Be helpful",
                    tone="Friendly",
                )
            )
            video = Videos(
                user_id=self.user_id,
                target_channel_id=target.target_channel_id,
                youtube_video_id=VIDEO_ID,
                title="Example video",
            )
            db.add(video)
            db.flush()
            selected = TargetVideo(user_id=self.user_id, video_id=video.video_id)
            db.add(selected)
            db.flush()
            self.selected_video_id = selected.selected_video_id
            db.commit()

        app = FastAPI()
        app.include_router(router)

        def test_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[db_manager.get_db] = test_db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            user_id=self.user_id
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def seed_comments(self, count, *, already_replied=0, empty_text_at=None):
        with self.sessions() as db:
            for number in range(count):
                replied = number < already_replied
                db.add(
                    Comments(
                        selected_video_id=self.selected_video_id,
                        youtube_comment_id=f"comment-{number}",
                        comment_text="" if number == empty_text_at else f"Viewer {number}",
                        ai_reply=f"Existing reply {number}" if replied else None,
                        is_replied=replied,
                        youtube_reply_id=f"posted-{number}" if replied else None,
                        reply_status="posted" if replied else "draft",
                    )
                )
            db.commit()

    def run_bulk(self, *, failing_comment=None, network_failure=False, ai_reply=None):
        posted = []

        def youtube_post(url, **kwargs):
            comment_id = kwargs["json"]["snippet"]["parentId"]
            posted.append(comment_id)
            request = httpx.Request("POST", url)
            if comment_id == failing_comment:
                if network_failure:
                    raise httpx.ReadTimeout("simulated timeout", request=request)
                return httpx.Response(403, json={"error": "posting refused"}, request=request)
            return httpx.Response(
                200, json={"id": f"posted-{comment_id}"}, request=request
            )

        generate = Mock(side_effect=ai_reply or (lambda context, text: f"Reply to {text}"))
        with patch.object(ai_service, "_generate_ai_reply", generate), patch.object(
            ai_service, "_get_access_token", return_value="test-token"
        ), patch.object(
            ai_service, "get_sync_http_client", return_value=SimpleNamespace(post=youtube_post)
        ):
            response = self.client.post(PATH)
        return response, generate, posted

    def test_five_unreplied_comments_are_generated_posted_and_saved(self):
        self.seed_comments(5)
        response, generate, posted = self.run_bulk()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "total": 5, "attempted": 5, "posted": 5, "failed": 0, "failures": []
        })
        self.assertEqual(generate.call_count, 5)
        self.assertEqual(len(posted), 5)
        self.assertIn("Example brand", generate.call_args_list[0].args[0])
        with self.sessions() as db:
            rows = db.query(Comments).order_by(Comments.comment_id).all()
            self.assertTrue(all(row.is_replied and row.reply_status == "posted" for row in rows))
            self.assertTrue(all(row.ai_reply and row.youtube_reply_id for row in rows))

    def test_already_replied_comments_are_skipped_and_retry_is_idempotent(self):
        self.seed_comments(5, already_replied=3)
        first, generated, posted = self.run_bulk()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["attempted"], 2)
        self.assertEqual(first.json()["posted"], 2)
        self.assertEqual(generated.call_count, 2)
        self.assertEqual(len(posted), 2)
        second, generated_again, posted_again = self.run_bulk()
        self.assertEqual(second.json()["attempted"], 0)
        self.assertEqual(second.json()["posted"], 0)
        self.assertEqual(generated_again.call_count, 0)
        self.assertEqual(posted_again, [])

    def test_one_post_failure_does_not_undo_other_replies(self):
        self.seed_comments(3)
        response, generated, posted = self.run_bulk(failing_comment="comment-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["posted"], 2)
        self.assertEqual(response.json()["failed"], 1)
        self.assertEqual(generated.call_count, 3)
        self.assertEqual(len(posted), 3)
        with self.sessions() as db:
            rows = {row.youtube_comment_id: row for row in db.query(Comments).all()}
            self.assertTrue(rows["comment-0"].is_replied)
            self.assertFalse(rows["comment-1"].is_replied)
            self.assertTrue(rows["comment-2"].is_replied)

    def test_empty_ai_reply_is_not_posted(self):
        self.seed_comments(1)
        response, generated, posted = self.run_bulk(ai_reply=lambda context, text: "")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["failed"], 1)
        self.assertEqual(generated.call_count, 1)
        self.assertEqual(posted, [])
        with self.sessions() as db:
            self.assertFalse(db.query(Comments).one().is_replied)

    def test_uncertain_youtube_outcome_is_not_retried(self):
        self.seed_comments(1)
        first, _, posted = self.run_bulk(
            failing_comment="comment-0", network_failure=True
        )
        self.assertEqual(first.json()["failed"], 1)
        self.assertEqual(posted, ["comment-0"])
        with self.sessions() as db:
            comment = db.query(Comments).one()
            self.assertFalse(comment.is_replied)
            self.assertEqual(comment.reply_status, "unknown")
        second, generated_again, posted_again = self.run_bulk()
        self.assertEqual(second.json()["posted"], 0)
        self.assertEqual(second.json()["failed"], 1)
        self.assertEqual(generated_again.call_count, 0)
        self.assertEqual(posted_again, [])


if __name__ == "__main__":
    unittest.main()
