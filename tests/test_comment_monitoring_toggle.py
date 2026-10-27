import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from router import ai_router, google_oauth_router
from services import coments_fetching_service, comment_monitor_service


class CommentMonitoringToggleTests(unittest.TestCase):
	def test_status_reports_saved_setting(self):
		db = Mock()
		user = SimpleNamespace(user_id=12)

		with patch.object(
			google_oauth_router.auth_repository,
			"is_comment_monitoring_enabled",
			return_value=False,
		):
			result = google_oauth_router.get_comment_monitoring(db, user)

		self.assertEqual(result, {"enabled": False})

	def test_toggle_update_saves_setting(self):
		db = Mock()
		user = SimpleNamespace(user_id=12)
		payload = google_oauth_router.CommentMonitoringSetting(enabled=True)

		with patch.object(
			google_oauth_router.auth_repository, "set_comment_monitoring_enabled"
		) as set_enabled:
			result = google_oauth_router.update_comment_monitoring(
				payload, db, user
			)

		set_enabled.assert_called_once_with(db, 12, True)
		db.commit.assert_called_once()
		self.assertEqual(result, {"enabled": True})

	def test_disabled_comment_request_returns_only_awaiting_comments_without_youtube(self):
		pending_root = SimpleNamespace(
			comment_id=1,
			parent_comment_id=None,
			youtube_comment_id="root",
			parent_youtube_comment_id=None,
			author_name="Viewer",
			author_channel_id="viewer-channel",
			comment_text="Question",
			published_at=None,
			can_reply=True,
			ai_reply=None,
			is_replied=False,
			youtube_reply_id=None,
			reply_status="draft",
		)
		pending_reply = SimpleNamespace(
			comment_id=2,
			parent_comment_id=1,
			youtube_comment_id="reply",
			parent_youtube_comment_id="root",
			author_name="Viewer",
			author_channel_id="viewer-channel",
			comment_text="Follow-up",
			published_at=None,
			can_reply=True,
			ai_reply="@Viewer Answer",
			is_replied=False,
			youtube_reply_id=None,
			reply_status="draft",
		)
		posted_comment = SimpleNamespace(
			comment_id=3,
			parent_comment_id=None,
			youtube_comment_id="posted",
			parent_youtube_comment_id=None,
			author_name="Another viewer",
			author_channel_id="another-viewer",
			comment_text="Already answered",
			published_at=None,
			can_reply=True,
			ai_reply="@Another viewer Thanks",
			is_replied=True,
			youtube_reply_id="bot-reply",
			reply_status="posted",
		)
		own_comment = SimpleNamespace(
			comment_id=4,
			parent_comment_id=None,
			youtube_comment_id="own",
			parent_youtube_comment_id=None,
			author_name="Our channel",
			author_channel_id="channel",
			comment_text="Own comment",
			published_at=None,
			can_reply=True,
			ai_reply=None,
			is_replied=False,
			youtube_reply_id=None,
			reply_status="draft",
		)
		skipped_comment = SimpleNamespace(
			comment_id=5,
			parent_comment_id=None,
			youtube_comment_id="skipped",
			parent_youtube_comment_id=None,
			author_name="Viewer",
			author_channel_id="viewer-channel",
			comment_text="Spam",
			published_at=None,
			can_reply=True,
			ai_reply=None,
			is_replied=False,
			youtube_reply_id=None,
			reply_status="skipped",
		)
		db = Mock()
		selected_video = SimpleNamespace(selected_video_id=22)

		with patch.object(
			coments_fetching_service.ai_repo,
			"get_selected_video",
			return_value=selected_video,
		), patch.object(
			coments_fetching_service.auth_repository,
			"is_comment_monitoring_enabled",
			return_value=False,
		), patch.object(
			coments_fetching_service.ai_repo,
			"get_video_comments",
			return_value=[
				pending_root,
				pending_reply,
				posted_comment,
				own_comment,
				skipped_comment,
			],
		), patch.object(
			coments_fetching_service,
			"_get_all_comments",
			side_effect=AssertionError("YouTube must not be queried while disabled"),
		):
			result = coments_fetching_service.fetch_video_comments(
				db, 12, "channel", "video"
			)

		self.assertEqual(
			[item["youtube_comment_id"] for item in result], ["root", "reply"]
		)
		self.assertTrue(all(item["awaiting_reply"] for item in result))
		self.assertTrue(all(not item["replies"] for item in result))
		self.assertEqual(result[1]["ai_reply"], "@Viewer Answer")

	def test_enabled_comment_request_fetches_and_saves_current_youtube_comments(self):
		db = Mock()
		selected_video = SimpleNamespace(selected_video_id=22)
		fetched = [
			{
				"youtube_comment_id": "new-comment",
				"author_channel_id": "viewer-channel",
				"text": "New question",
				"replies": [],
			}
		]

		with patch.object(
			coments_fetching_service.ai_repo,
			"get_selected_video",
			return_value=selected_video,
		), patch.object(
			coments_fetching_service.auth_repository,
			"is_comment_monitoring_enabled",
			return_value=True,
		), patch.object(
			coments_fetching_service,
			"_get_access_token",
			return_value="access-token",
		), patch.object(
			coments_fetching_service,
			"_get_all_comments",
			return_value=fetched,
		) as fetch_youtube, patch.object(
			coments_fetching_service.coments_feching_repo,
			"save_fetched_comments",
		) as save_comments, patch.object(
			coments_fetching_service.ai_service,
			"attach_saved_reply_state",
		):
			result = coments_fetching_service.fetch_video_comments(
				db, 12, "channel", "video"
			)

		fetch_youtube.assert_called_once_with(
			"access-token", "video", max_comments=100, max_replies=50
		)
		save_comments.assert_called_once_with(db, 22, fetched)
		db.commit.assert_called_once()
		self.assertEqual(result, fetched)

	def test_disabled_toggle_blocks_reply_generation(self):
		db = Mock()
		user = SimpleNamespace(user_id=12)

		with patch.object(
			ai_router.auth_repository,
			"is_comment_monitoring_enabled",
			return_value=False,
		), patch.object(
			ai_router.coments_fetching_service, "fetch_video_comments"
		) as fetch_comments:
			with self.assertRaises(HTTPException) as raised:
				ai_router.generate_and_post_replies("channel", "video", db, user)

		self.assertEqual(raised.exception.status_code, 409)
		fetch_comments.assert_not_called()

	def test_monitor_cycle_does_not_fetch_when_toggle_is_disabled(self):
		initial_db, video_db = Mock(), Mock()
		for db in (initial_db, video_db):
			db.__enter__ = Mock(return_value=db)
			db.__exit__ = Mock(return_value=False)

		with patch.object(
			comment_monitor_service.db_manager,
			"SessionLocal",
			side_effect=[initial_db, video_db],
		), patch.object(
			comment_monitor_service.ai_repo,
			"get_selected_videos_for_monitoring",
			return_value=[(12, "channel", "video")],
		), patch.object(
			comment_monitor_service.auth_repository,
			"is_comment_monitoring_enabled",
			return_value=False,
		), patch.object(
			comment_monitor_service.coments_fetching_service,
			"fetch_video_comments",
		) as fetch_comments:
			comment_monitor_service.run_comment_monitoring_cycle()

		fetch_comments.assert_not_called()

	def test_enabled_monitor_processes_fetched_pending_comment_ids(self):
		initial_db, video_db = Mock(), Mock()
		for db in (initial_db, video_db):
			db.__enter__ = Mock(return_value=db)
			db.__exit__ = Mock(return_value=False)
		fetched_comments = [
			{
				"youtube_comment_id": "pending-root",
				"replies": [
					{"youtube_comment_id": "pending-reply", "replies": []}
				],
			}
		]

		with patch.object(
			comment_monitor_service.db_manager,
			"SessionLocal",
			side_effect=[initial_db, video_db],
		), patch.object(
			comment_monitor_service.ai_repo,
			"get_selected_videos_for_monitoring",
			return_value=[(12, "channel", "video")],
		), patch.object(
			comment_monitor_service.auth_repository,
			"is_comment_monitoring_enabled",
			return_value=True,
		), patch.object(
			comment_monitor_service.coments_fetching_service,
			"fetch_video_comments",
			return_value=fetched_comments,
		), patch.object(
			comment_monitor_service.ai_service,
			"generate_and_post_new_video_replies",
			return_value={
				"attempted": 2,
				"posted": 2,
				"skipped": 0,
				"failed": 0,
			},
		) as process_replies:
			comment_monitor_service.run_comment_monitoring_cycle()

		process_replies.assert_called_once_with(
			video_db,
			12,
			"channel",
			"video",
			{"pending-root", "pending-reply"},
			already_replied_comment_ids=set(),
		)


if __name__ == "__main__":
	unittest.main()
