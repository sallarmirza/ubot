import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from router import ai_router, comments_fetching_router, selection_video_router
from schema.selection_video_schema import SelectedVideosRequest
from services import (
	ai_service,
	comment_monitor_service,
	coments_fetching_service,
	selection_video_service,
)


class ExplicitReplyEndpointTests(unittest.TestCase):
	def test_comments_get_only_fetches_and_persists_comments(self):
		db = Mock()
		user = SimpleNamespace(user_id=7)
		with patch.object(
			coments_fetching_service, "fetch_video_comments", return_value=[]
		) as fetch, patch.object(
			ai_service, "generate_and_post_video_replies"
		) as generate_and_post, patch.object(
			ai_service, "post_video_comment_reply"
		) as post_reply:
			result = comments_fetching_router.get_comments(
				"our-channel", "video-1", 100, 50, db, user
			)

		self.assertEqual(result, [])
		fetch.assert_called_once_with(db, 7, "our-channel", "video-1", 100, 50)
		generate_and_post.assert_not_called()
		post_reply.assert_not_called()

	def test_explicit_post_fetches_full_comment_history_then_processes_replies(self):
		db = Mock()
		user = SimpleNamespace(user_id=7)
		call_order = []

		def fetch(*args, **kwargs):
			self.assertEqual(len(args), 4)
			self.assertEqual(
				kwargs,
				{"max_comments": None, "max_replies": None},
			)
			call_order.append("fetch")

		def generate_and_post(*args):
			self.assertEqual(args, (db, 7, "our-channel", "video-1"))
			call_order.append("generate-and-post")
			return {
				"total": 1,
				"attempted": 1,
				"posted": 1,
				"skipped": 0,
				"failed": 0,
				"failures": [],
			}

		with patch.object(
			coments_fetching_service, "fetch_video_comments", side_effect=fetch
		) as fetch_comments, patch.object(
			ai_service,
			"generate_and_post_video_replies",
			side_effect=generate_and_post,
		) as process:
			result = ai_router.generate_and_post_replies(
				"our-channel", "video-1", db, user
			)

		self.assertEqual(call_order, ["fetch", "generate-and-post"])
		fetch_comments.assert_called_once_with(
			db,
			7,
			"our-channel",
			"video-1",
			max_comments=None,
			max_replies=None,
		)
		process.assert_called_once_with(db, 7, "our-channel", "video-1")
		self.assertEqual(result["posted"], 1)
		self.assertTrue(
			any(
				route.path
				== "/ai/{channel_id}/{video_id}/generate-and-post-replies"
				and "POST" in route.methods
				for route in ai_router.router.routes
			)
		)

	def test_selecting_and_saving_videos_do_not_generate_or_post_replies(self):
		db = Mock()
		user = SimpleNamespace(user_id=7)
		payload = SelectedVideosRequest(channel_id="our-channel", videos=[])
		with patch.object(
			selection_video_router.selection_video_service,
			"list_channel_videos",
			return_value=[],
		), patch.object(
			selection_video_router.selection_video_service,
			"save_selected_videos",
			return_value=[],
		), patch.object(
			ai_service, "generate_and_post_video_replies"
		) as generate_and_post, patch.object(
			ai_service, "post_video_comment_reply"
		) as post_reply:
			selection_video_router.get_channel_videos(
				"our-channel", 5, db, user
			)
			selection_video_router.save_selected_videos(payload, db, user)

		generate_and_post.assert_not_called()
		post_reply.assert_not_called()


class CommentsFetchBehaviorTests(unittest.TestCase):
	def test_fetch_comments_attaches_state_without_generating_or_posting(self):
		db = Mock()
		selected_video = SimpleNamespace(selected_video_id=11)
		with patch.object(
			coments_fetching_service.ai_repo,
			"get_selected_video",
			return_value=selected_video,
		), patch.object(
			coments_fetching_service,
			"_get_access_token",
			return_value="test-token",
		), patch.object(
			coments_fetching_service,
			"_get_all_comments",
			return_value=[],
		), patch.object(
			coments_fetching_service.coments_feching_repo,
			"save_fetched_comments",
		), patch.object(
			ai_service, "attach_saved_reply_state"
		), patch.object(
			ai_service, "_generate_ai_reply"
		) as generate_reply, patch.object(
			ai_service, "post_video_comment_reply"
		) as post_reply, patch.object(
			ai_service, "generate_and_post_video_replies"
		) as generate_and_post:
			result = coments_fetching_service.fetch_video_comments(
				db, 7, "our-channel", "video-1"
			)

		self.assertEqual(result, [])
		generate_reply.assert_not_called()
		post_reply.assert_not_called()
		generate_and_post.assert_not_called()


class ExplicitCommentReplyTests(unittest.TestCase):
	def test_explicit_action_skips_already_replied_comments(self):
		comments = [
			SimpleNamespace(
				comment_id=1,
				youtube_comment_id="top-with-replies",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
			),
			SimpleNamespace(
				comment_id=2,
				youtube_comment_id="viewer-reply-1",
				parent_comment_id=1,
				author_channel_id="viewer-channel",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
			),
			SimpleNamespace(
				comment_id=3,
				youtube_comment_id="viewer-reply-2",
				parent_comment_id=1,
				author_channel_id="viewer-channel",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
			),
			SimpleNamespace(
				comment_id=4,
				youtube_comment_id="top-without-replies",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
			),
			SimpleNamespace(
				comment_id=5,
				youtube_comment_id="bot-reply",
				parent_comment_id=4,
				author_channel_id="our-channel",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
			),
			SimpleNamespace(
				comment_id=6,
				youtube_comment_id="already-answered",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				youtube_reply_id=None,
				is_replied=True,
				reply_status="posted",
			),
			SimpleNamespace(
				comment_id=7,
				youtube_comment_id="unanswered-top-level",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
			),
			SimpleNamespace(
				comment_id=8,
				youtube_comment_id="cannot-reply-thread",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
				can_reply=False,
			),
		]
		regenerated_ids = []
		posted_ids = []

		def regenerate(*args):
			regenerated_ids.append(args[4])
			return {"ai_reply": "A contextual answer"}

		def post(*args):
			posted_ids.append(args[4])
			return {"is_replied": True}

		with patch.object(
			ai_service,
			"_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service.ai_repo, "get_comments", return_value=comments
		), patch.object(
			ai_service, "regenerate_reply_draft", side_effect=regenerate
		), patch.object(
			ai_service, "post_video_comment_reply", side_effect=post
		):
			result = ai_service.generate_and_post_video_replies(
				Mock(), 7, "our-channel", "video-1"
			)

		self.assertEqual(regenerated_ids, [
			"top-with-replies",
			"viewer-reply-1",
			"viewer-reply-2",
			"top-without-replies",
			"unanswered-top-level",
		])
		self.assertEqual(posted_ids, regenerated_ids)
		self.assertEqual(result["attempted"], 5)
		self.assertEqual(result["posted"], 5)
		self.assertEqual(result["skipped"], 3)


class FullCommentFetchTests(unittest.TestCase):
	def test_unbounded_fetch_reads_every_thread_and_reply_page(self):
		thread_calls = 0
		reply_calls = 0

		def thread(top_comment_id, *, reply_count, can_reply=True):
			return {
				"canReply": can_reply,
				"snippet": {
					"totalReplyCount": reply_count,
					"topLevelComment": {
						"id": top_comment_id,
						"snippet": {
							"textDisplay": top_comment_id,
							"authorChannelId": {"value": "viewer-channel"},
						},
					},
				}
			}

		def fetch(*args):
			nonlocal thread_calls, reply_calls
			endpoint, params = args[1], args[2]
			if endpoint == "commentThreads":
				thread_calls += 1
				if params.get("pageToken") == "next-thread-page":
					return {
						"items": [thread("top-2", reply_count=0, can_reply=False)]
					}
				return {
					"items": [thread("top-1", reply_count=101, can_reply=False)],
					"nextPageToken": "next-thread-page",
				}

			reply_calls += 1
			if params.get("pageToken") == "next-reply-page":
				return {
					"items": [
						{
							"id": "reply-100",
							"snippet": {
								"textDisplay": "Reply 100",
								"authorChannelId": {"value": "viewer-channel"},
							},
						}
					]
				}
			return {
				"items": [
					{
						"id": f"reply-{index}",
						"snippet": {
							"textDisplay": f"Reply {index}",
							"authorChannelId": {"value": "viewer-channel"},
						},
					}
					for index in range(100)
				],
				"nextPageToken": "next-reply-page",
			}

		with patch.object(coments_fetching_service, "_youtube_get", side_effect=fetch):
			result = coments_fetching_service._get_all_comments(
				"access-token",
				"video-1",
				max_comments=None,
				max_replies=None,
			)

		self.assertEqual(thread_calls, 2)
		self.assertEqual(reply_calls, 2)
		self.assertEqual(len(result), 2)
		self.assertEqual(len(result[0]["replies"]), 101)
		self.assertEqual(result[0]["author_channel_id"], "viewer-channel")
		self.assertFalse(result[0]["can_reply"])
		self.assertFalse(result[0]["replies"][0]["can_reply"])
		self.assertEqual(
			result[0]["replies"][100]["author_channel_id"], "viewer-channel"
		)
		self.assertEqual(result[1]["youtube_comment_id"], "top-2")
		self.assertEqual(result[1]["replies"], [])
		self.assertFalse(result[1]["can_reply"])


class PeriodicMonitorCycleTests(unittest.TestCase):
	def test_comment_refresh_cycle_fetches_without_generating_or_posting(self):
		db = Mock()
		db.__enter__ = Mock(return_value=db)
		db.__exit__ = Mock(return_value=False)
		with patch.object(
			comment_monitor_service.db_manager,
			"SessionLocal",
			side_effect=[db, db],
		), patch.object(
			comment_monitor_service.ai_repo,
			"get_selected_videos_for_monitoring",
			return_value=[(12, "our-channel", "video-5")],
		), patch.object(
			comment_monitor_service.coments_fetching_service,
			"fetch_video_comments",
		) as fetch, patch.object(
			ai_service, "generate_and_post_video_replies"
		) as reply:
			comment_monitor_service.run_comment_monitoring_cycle()

		fetch.assert_called_once_with(
			db,
			12,
			"our-channel",
			"video-5",
		)
		reply.assert_not_called()
		self.assertEqual(comment_monitor_service.COMMENT_FETCH_INTERVAL_SECONDS, 10)


class YouTubeVideoRequestErrorTests(unittest.TestCase):
	def test_quota_error_is_reported_as_actionable_service_unavailable(self):
		response = Mock(
			status_code=403,
			json=Mock(
				return_value={
					"error": {
						"message": "Quota exceeded",
						"errors": [{"reason": "quotaExceeded"}],
					}
				}
			),
		)
		client = Mock()
		client.get.return_value = response

		with patch.object(
			selection_video_service, "get_sync_http_client", return_value=client
		):
			with self.assertRaises(HTTPException) as context:
				selection_video_service._youtube_get("token", "channels", {})

		self.assertEqual(context.exception.status_code, 503)
		self.assertIn("quota", context.exception.detail.lower())

	def test_youtube_error_reason_is_included_for_unmapped_failures(self):
		response = Mock(
			status_code=400,
			json=Mock(
				return_value={
					"error": {
						"message": "Invalid channel identifier",
						"errors": [{"reason": "invalidParameter"}],
					}
				}
			),
		)
		client = Mock()
		client.get.return_value = response

		with patch.object(
			selection_video_service, "get_sync_http_client", return_value=client
		):
			with self.assertRaises(HTTPException) as context:
				selection_video_service._youtube_get("token", "channels", {})

		self.assertEqual(context.exception.status_code, 502)
		self.assertIn("invalidParameter", context.exception.detail)


if __name__ == "__main__":
	unittest.main()
