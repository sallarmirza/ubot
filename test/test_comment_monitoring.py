import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services import ai_service, comment_monitor_service, coments_fetching_service


class LeafCommentReplyTests(unittest.TestCase):
	def test_worker_replies_only_to_leaf_viewer_comments(self):
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
			"viewer-reply-1",
			"viewer-reply-2",
			"unanswered-top-level",
		])
		self.assertEqual(posted_ids, regenerated_ids)
		self.assertEqual(result["attempted"], 3)
		self.assertEqual(result["posted"], 3)
		self.assertEqual(result["skipped"], 4)


class FullCommentFetchTests(unittest.TestCase):
	def test_unbounded_fetch_reads_every_thread_and_reply_page(self):
		thread_calls = 0
		reply_calls = 0

		def thread(top_comment_id, *, reply_count):
			return {
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
					return {"items": [thread("top-2", reply_count=0)]}
				return {
					"items": [thread("top-1", reply_count=101)],
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
		self.assertEqual(
			result[0]["replies"][100]["author_channel_id"], "viewer-channel"
		)
		self.assertEqual(result[1]["youtube_comment_id"], "top-2")
		self.assertEqual(result[1]["replies"], [])


class PeriodicMonitorCycleTests(unittest.TestCase):
	def test_cycle_fetches_all_threads_then_processes_leaf_comments(self):
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
			comment_monitor_service.ai_service,
			"generate_and_post_video_replies",
			return_value={
				"attempted": 2,
				"posted": 2,
				"skipped": 1,
				"failed": 0,
			},
		) as reply:
			comment_monitor_service.run_comment_monitoring_cycle()

		fetch.assert_called_once_with(
			db,
			12,
			"our-channel",
			"video-5",
			max_comments=None,
			max_replies=None,
		)
		reply.assert_called_once_with(db, 12, "our-channel", "video-5")


if __name__ == "__main__":
	unittest.main()
