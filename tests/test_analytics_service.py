import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services import analytics_service


class AnalyticsRefreshTests(unittest.TestCase):
	def setUp(self):
		self.db = MagicMock()
		self.channel = SimpleNamespace(
			youtube_channel_id="youtube-channel",
			channel_name="Old channel name",
			channel_subscribers=20,
			channel_views=200,
			updated_at=None,
		)
		self.selected_video = SimpleNamespace(
			selected_video_id=12,
			video=SimpleNamespace(
				youtube_video_id="youtube-video",
				target_channel=SimpleNamespace(channel=self.channel),
			),
			views=100,
			likes=10,
			comments=5,
			updated_at=None,
		)

	@patch(
		"services.analytics_service.selection_video_service.fetch_video_statistics"
	)
	@patch(
		"services.analytics_service.selection_video_service.fetch_channel_statistics"
	)
	@patch("services.analytics_service.analytics_repo.get_latest_analytics_snapshots")
	def test_refresh_updates_existing_metrics_row_without_inserting(
		self, latest_snapshots, fetch_channel_statistics, fetch_statistics
	):
		snapshot = SimpleNamespace(
			user_id=3,
			selected_video_id=12,
			views=100,
			likes=10,
			comments=5,
		)
		latest_snapshots.return_value = {12: snapshot}
		fetch_statistics.return_value = {
			"youtube-video": {"views": 101, "likes": 11, "comments": 6}
		}
		fetch_channel_statistics.return_value = {
			"youtube-channel": {
				"channel_name": "Updated channel",
				"channel_subscribers": 21,
				"channel_views": 201,
			}
		}

		analytics_service._refresh_selected_statistics(
			self.db, 3, [self.selected_video]
		)

		self.assertEqual(
			(
				self.selected_video.views,
				self.selected_video.likes,
				self.selected_video.comments,
			),
			(101, 11, 6),
		)
		self.assertIsNotNone(self.selected_video.updated_at)
		self.assertEqual(self.channel.channel_name, "Updated channel")
		self.assertEqual(
			(self.channel.channel_subscribers, self.channel.channel_views),
			(21, 201),
		)
		self.assertIsNotNone(self.channel.updated_at)
		self.assertEqual(
			(
				snapshot.user_id,
				snapshot.selected_video_id,
				snapshot.views,
				snapshot.likes,
				snapshot.comments,
			),
			(3, 12, 101, 11, 6),
		)
		self.db.add.assert_not_called()
		self.db.commit.assert_called_once()

	@patch(
		"services.analytics_service.selection_video_service.fetch_video_statistics"
	)
	@patch(
		"services.analytics_service.selection_video_service.fetch_channel_statistics"
	)
	@patch("services.analytics_service.analytics_repo.get_latest_analytics_snapshots")
	def test_refresh_updates_existing_row_when_metrics_are_unchanged(
		self, latest_snapshots, fetch_channel_statistics, fetch_statistics
	):
		snapshot = SimpleNamespace(views=100, likes=10, comments=5)
		latest_snapshots.return_value = {12: snapshot}
		fetch_statistics.return_value = {
			"youtube-video": {"views": 100, "likes": 10, "comments": 5}
		}
		fetch_channel_statistics.return_value = {
			"youtube-channel": {
				"channel_name": "Old channel name",
				"channel_subscribers": 20,
				"channel_views": 200,
			}
		}

		analytics_service._refresh_selected_statistics(
			self.db, 3, [self.selected_video]
		)

		self.db.add.assert_not_called()
		self.db.commit.assert_called_once()
		self.assertEqual(
			(snapshot.views, snapshot.likes, snapshot.comments),
			(100, 10, 5),
		)

	@patch("services.analytics_service.analytics_repo.get_video_analytics")
	@patch("services.analytics_service.analytics_repo.get_video_comments")
	def test_analytics_counts_unanswered_viewer_replies_inside_threads(
		self, get_comments, get_history
	):
		channel = SimpleNamespace(
			youtube_channel_id="youtube-channel",
			channel_name="Channel",
			channel_subscribers=20,
			channel_views=200,
		)
		selected_video = SimpleNamespace(
			selected_video_id=12,
			video=SimpleNamespace(
				youtube_video_id="youtube-video",
				title="Video",
				target_channel=SimpleNamespace(channel=channel),
			),
			channel_name="Channel",
			description=None,
			prompt_context=None,
			views=100,
			likes=10,
			comments=5,
			created_at=None,
			updated_at=None,
		)
		comments = [
			SimpleNamespace(
				comment_id=1,
				youtube_comment_id="viewer-root",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				comment_text="Question",
				ai_reply=None,
				is_replied=False,
				can_reply=True,
				youtube_reply_id=None,
				reply_status="draft",
				video_name="Video",
				created_at=None,
				updated_at=None,
			),
			SimpleNamespace(
				comment_id=2,
				youtube_comment_id="viewer-follow-up",
				parent_comment_id=1,
				author_channel_id="another-viewer",
				comment_text="Follow-up",
				ai_reply=None,
				is_replied=False,
				can_reply=True,
				youtube_reply_id=None,
				reply_status="failed",
				video_name="Video",
				created_at=None,
				updated_at=None,
			),
			SimpleNamespace(
				comment_id=3,
				youtube_comment_id="channel-reply",
				parent_comment_id=1,
				author_channel_id="youtube-channel",
				comment_text="Our channel reply",
				ai_reply=None,
				is_replied=False,
				can_reply=True,
				youtube_reply_id=None,
				reply_status="posted",
				video_name="Video",
				created_at=None,
				updated_at=None,
			),
			SimpleNamespace(
				comment_id=4,
				youtube_comment_id="already-answered",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				comment_text="Already answered",
				ai_reply="Thanks",
				is_replied=True,
				can_reply=True,
				youtube_reply_id="channel-reply-id",
				reply_status="posted",
				video_name="Video",
				created_at=None,
				updated_at=None,
			),
		]
		get_comments.return_value = comments
		get_history.return_value = []

		analytics = analytics_service._build_video_analytics(
			self.db, selected_video
		)

		self.assertEqual(analytics.awaiting_replies, 2)
		self.assertEqual(
			[comment.awaiting_reply for comment in analytics.comments],
			[True, True, False, False],
		)

	@patch("services.analytics_service._build_video_analytics")
	@patch("services.analytics_service.analytics_repo.get_selected_videos")
	@patch(
		"services.analytics_service.selection_video_service.fetch_video_statistics"
	)
	@patch(
		"services.analytics_service.selection_video_service.fetch_channel_statistics"
	)
	@patch("services.analytics_service.analytics_repo.get_latest_analytics_snapshots")
	def test_analytics_request_returns_fresh_metrics(
		self,
		latest_snapshots,
		fetch_channel_statistics,
		fetch_statistics,
		get_selected_videos,
		build_analytics,
	):
		get_selected_videos.return_value = [self.selected_video]
		fetch_statistics.return_value = {
			"youtube-video": {"views": 101, "likes": 11, "comments": 6}
		}
		fetch_channel_statistics.return_value = {
			"youtube-channel": {
				"channel_name": "Updated channel",
				"channel_subscribers": 21,
				"channel_views": 201,
			}
		}
		latest_snapshots.return_value = {}
		build_analytics.side_effect = lambda db, video: video.views

		result = analytics_service.get_selected_video_analytics(self.db, 3)

		self.assertEqual(result, [101])
		self.db.commit.assert_called_once()


if __name__ == "__main__":
	unittest.main()
