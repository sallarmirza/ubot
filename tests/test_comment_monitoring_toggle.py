import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from router import ai_router, google_oauth_router
from services import coments_fetching_service, comment_monitor_service


class CommentMonitoringToggleTests(unittest.TestCase):
	def test_status_reports_saved_setting(self):
		db = Mock()
		user = SimpleNamespace(user_id=12)

		with patch.object(
			google_oauth_router.auth_repository,
			"get_comment_monitoring_settings",
			return_value={
				"enabled": False,
				"comment_fetch_interval_minutes": 15,
			},
		):
			result = google_oauth_router.get_comment_monitoring(db, user)

		self.assertEqual(
			result,
			{"enabled": False, "comment_fetch_interval_minutes": 15},
		)

	def test_toggle_update_saves_interval_and_returns_preferences(self):
		db = Mock()
		user = SimpleNamespace(user_id=12)
		payload = google_oauth_router.CommentMonitoringSetting(
			enabled=True, comment_fetch_interval_minutes=15
		)

		with patch.object(
			google_oauth_router.auth_repository, "set_comment_monitoring_enabled"
		) as set_enabled, patch.object(
			google_oauth_router.auth_repository,
			"get_comment_monitoring_settings",
			return_value={
				"enabled": True,
				"comment_fetch_interval_minutes": 15,
			},
		):
			result = google_oauth_router.update_comment_monitoring(
				payload, db, user
			)

		set_enabled.assert_called_once_with(db, 12, True, 15)
		db.commit.assert_called_once()
		self.assertEqual(
			result,
			{"enabled": True, "comment_fetch_interval_minutes": 15},
		)

	def test_update_without_interval_preserves_existing_interval(self):
		db = Mock()
		user = SimpleNamespace(user_id=12)
		payload = google_oauth_router.CommentMonitoringSetting(enabled=False)

		with patch.object(
			google_oauth_router.auth_repository, "set_comment_monitoring_enabled"
		) as set_enabled, patch.object(
			google_oauth_router.auth_repository,
			"get_comment_monitoring_settings",
			return_value={
				"enabled": False,
				"comment_fetch_interval_minutes": 30,
			},
		):
			result = google_oauth_router.update_comment_monitoring(
				payload, db, user
			)

		set_enabled.assert_called_once_with(db, 12, False, None)
		self.assertEqual(result["comment_fetch_interval_minutes"], 30)

	def test_comment_fetch_interval_validation(self):
		for invalid_interval in (0, 1441, 1.5, True, "5", None):
			with self.subTest(interval=invalid_interval):
				with self.assertRaises(ValidationError):
					google_oauth_router.CommentMonitoringSetting(
						enabled=True,
						comment_fetch_interval_minutes=invalid_interval,
					)

		for valid_interval in (1, 5, 1440):
			with self.subTest(interval=valid_interval):
				payload = google_oauth_router.CommentMonitoringSetting(
					enabled=True,
					comment_fetch_interval_minutes=valid_interval,
				)
				self.assertEqual(
					payload.comment_fetch_interval_minutes, valid_interval
				)

	def test_comments_can_be_fetched_when_ai_replies_are_disabled(self):
		db = Mock()
		selected_video = SimpleNamespace(selected_video_id=22)
		fetched_comments = [
			{
				"youtube_comment_id": "new-comment",
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
			return_value=False,
		), patch.object(
			coments_fetching_service,
			"_get_access_token",
			return_value="access-token",
		), patch.object(
			coments_fetching_service,
			"_get_all_comments",
			return_value=fetched_comments,
		) as fetch_youtube, patch.object(
			coments_fetching_service.coments_feching_repo,
			"save_fetched_comments",
		), patch.object(
			coments_fetching_service.ai_service, "attach_saved_reply_state"
		), patch.object(
			coments_fetching_service.ai_service,
			"generate_and_post_new_video_replies",
		) as generate_replies:
			result = coments_fetching_service.fetch_video_comments(
				db, 12, "channel", "video"
			)

		fetch_youtube.assert_called_once()
		self.assertEqual(result, fetched_comments)
		generate_replies.assert_not_called()

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
			return_value=[(12, "channel", "video", 5)],
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
			return_value=[(12, "channel", "video", 15)],
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

	def test_monitor_interval_helpers_schedule_each_user_independently(self):
		intervals = {1: 60, 2: 900, 3: 86400}
		last_fetch = {1: 100.0, 2: 200.0, 3: 300.0}

		self.assertEqual(
			comment_monitor_service._get_due_user_ids(
				intervals, last_fetch, 250.0
			),
			{1},
		)
		self.assertEqual(
			comment_monitor_service._seconds_until_next_fetch(
				intervals, {1: 250.0, 2: 200.0, 3: 300.0}, 250.0
			),
			60,
		)
		self.assertEqual(
			comment_monitor_service._get_due_user_ids(
				intervals, last_fetch, 1100.0
			),
			{1, 2},
		)


if __name__ == "__main__":
	unittest.main()
