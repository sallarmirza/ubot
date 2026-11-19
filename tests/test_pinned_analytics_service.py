import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from services import pinned_analytics_service


class PinnedAnalyticsServiceTests(unittest.TestCase):
	def setUp(self):
		self.db = object()
		self.pin = SimpleNamespace(
			enabled=True,
			youtube_channel_id="channel-1",
			youtube_video_id="video-1",
		)
		self.selected_video = SimpleNamespace(
			video=SimpleNamespace(
				title="Saved video title",
				target_channel=SimpleNamespace(
					channel=SimpleNamespace(channel_name="Saved channel name")
				),
			)
		)

	@patch("services.pinned_analytics_service.selection_video_service")
	@patch("services.pinned_analytics_service.analytics_repo")
	def test_returns_current_stats_and_splits_channel_replies(
		self, analytics_repo, selection_video_service
	):
		analytics_repo.get_pinned_video.return_value = self.pin
		analytics_repo.get_selected_video.return_value = self.selected_video
		selection_video_service.fetch_video_statistics.return_value = {
			"video-1": {
				"title": "Current video title",
				"views": 120,
				"likes": 18,
				"comments": 7,
			}
		}
		selection_video_service.fetch_channel_statistics.return_value = {
			"channel-1": {
				"channel_name": "Current channel name",
				"channel_subscribers": 31,
				"channel_views": 200,
				"channel_video_count": 4,
			}
		}
		comments = [
			{
				"youtube_comment_id": "answered",
				"author_name": "Viewer",
				"author_channel_id": "viewer-1",
				"text": "Thanks",
				"published_at": "2026-01-01T00:00:00Z",
				"like_count": 2,
				"replies": [
					{
						"youtube_comment_id": "reply-1",
						"author_name": "My channel",
						"author_channel_id": "channel-1",
						"text": "You're welcome",
						"published_at": "2026-01-01T01:00:00Z",
						"like_count": 0,
					}
				],
			},
			{
				"youtube_comment_id": "unanswered",
				"author_name": "Another viewer",
				"author_channel_id": "viewer-2",
				"text": "Question",
				"published_at": "2026-01-02T00:00:00Z",
				"like_count": 0,
				"replies": [],
			},
			{
				"youtube_comment_id": "own-comment",
				"author_name": "My channel",
				"author_channel_id": "channel-1",
				"text": "Our own comment",
				"published_at": "2026-01-03T00:00:00Z",
				"like_count": 0,
				"replies": [],
			},
		]
		with patch(
			"services.pinned_analytics_service.coments_fetching_service"
		) as comments_service:
			comments_service.fetch_video_comments.return_value = comments

			result = pinned_analytics_service.get_pinned_analytics(
				self.db, user_id=5, max_comments=100, max_replies=50
			)

		self.assertEqual(
			(
				result.channel_name,
				result.channel_subscribers,
				result.channel_total_videos,
				result.video_title,
				result.video_views,
				result.video_likes,
				result.video_comment_count,
			),
			("Current channel name", 31, 4, "Current video title", 120, 18, 7),
		)
		self.assertEqual(
			[comment.comment_id for comment in result.replied_comments],
			["answered"],
		)
		self.assertEqual(
			[comment.comment_id for comment in result.unanswered_comments],
			["unanswered"],
		)
		self.assertEqual(
			result.replied_comments[0].replies[0].author_channel_id, "channel-1"
		)
		self.assertEqual(result.comments_fetched, 2)

	@patch("services.pinned_analytics_service.selection_video_service")
	@patch("services.pinned_analytics_service.analytics_repo")
	def test_disabled_pin_does_not_fetch_anything(
		self, analytics_repo, selection_video_service
	):
		self.pin.enabled = False
		analytics_repo.get_pinned_video.return_value = self.pin

		with self.assertRaises(HTTPException) as raised:
			pinned_analytics_service.get_pinned_analytics(
				self.db, user_id=5, max_comments=100, max_replies=50
			)

		self.assertEqual(raised.exception.status_code, 409)
		selection_video_service.fetch_video_statistics.assert_not_called()

	@patch("services.pinned_analytics_service.analytics_repo")
	def test_disabling_pin_keeps_the_saved_channel_and_video(self, analytics_repo):
		analytics_repo.get_pinned_video.return_value = self.pin

		def disable_pin(_db, pin, enabled):
			pin.enabled = enabled
			return pin

		analytics_repo.set_pinned_video_enabled.side_effect = disable_pin

		result = pinned_analytics_service.set_pin_enabled(
			self.db, user_id=5, enabled=False
		)

		self.assertFalse(self.pin.enabled)
		self.assertFalse(result["enabled"])
		self.assertEqual(result["channel_id"], "channel-1")
		self.assertEqual(result["video_id"], "video-1")
		analytics_repo.set_pinned_video_enabled.assert_called_once_with(
			self.db, self.pin, False
		)

	@patch("services.pinned_analytics_service._load_pinned_analytics")
	@patch("services.pinned_analytics_service.analytics_repo")
	def test_public_endpoint_uses_owner_of_latest_enabled_pin(
		self, analytics_repo, load_pinned_analytics
	):
		self.pin.user_id = 17
		analytics_repo.get_latest_enabled_pinned_video.return_value = self.pin
		expected = object()
		load_pinned_analytics.return_value = expected

		result = pinned_analytics_service.get_public_pinned_analytics(
			self.db, max_comments=20, max_replies=10
		)

		self.assertIs(result, expected)
		load_pinned_analytics.assert_called_once_with(
			self.db, 17, self.pin, 20, 10
		)


if __name__ == "__main__":
	unittest.main()
