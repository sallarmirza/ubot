import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db_model import Comments
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
			return [
				{
					"youtube_comment_id": "thread-root",
					"replies": [
						{
							"youtube_comment_id": "viewer-child",
							"replies": [
								{
									"youtube_comment_id": "viewer-grandchild",
									"replies": [],
								}
							],
						}
					],
				}
			]

		def generate_and_post(*args, **kwargs):
			self.assertEqual(
				args,
				(
					db,
					7,
					"our-channel",
					"video-1",
					{"thread-root", "viewer-child", "viewer-grandchild"},
				),
			)
			self.assertEqual(kwargs, {"already_replied_comment_ids": set()})
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
		process.assert_called_once_with(
			db,
			7,
			"our-channel",
			"video-1",
			{"thread-root", "viewer-child", "viewer-grandchild"},
			already_replied_comment_ids=set(),
		)
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


class AIReplyPromptTests(unittest.TestCase):
	def test_pre_llm_claim_allows_one_worker_and_enforces_thread_limit(self):
		engine = create_engine("sqlite:///:memory:")
		Comments.__table__.create(engine)
		session_factory = sessionmaker(bind=engine)
		db = session_factory()
		root = Comments(
			selected_video_id=11,
			youtube_comment_id="root",
			thread_youtube_comment_id="root",
			comment_text="hi",
			author_channel_id="viewer",
		)
		first = Comments(
			selected_video_id=11,
			youtube_comment_id="viewer-1",
			thread_youtube_comment_id="root",
			parent_youtube_comment_id="bot-parent",
			comment_text="Question one",
			author_channel_id="viewer",
			published_at=datetime(2026, 1, 1),
		)
		second = Comments(
			selected_video_id=11,
			youtube_comment_id="viewer-2",
			thread_youtube_comment_id="root",
			parent_youtube_comment_id="bot-parent",
			comment_text="Question two",
			author_channel_id="viewer",
			published_at=datetime(2026, 1, 2),
		)
		other_branch = Comments(
			selected_video_id=11,
			youtube_comment_id="viewer-3",
			thread_youtube_comment_id="root",
			parent_youtube_comment_id="other-bot-parent",
			comment_text="Question on another branch",
			author_channel_id="viewer",
			published_at=datetime(2026, 1, 3),
		)
		db.add_all([root, first, second, other_branch])
		db.commit()
		stale_before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)

		self.assertEqual(
			ai_service.ai_repo.claim_reply_processing(
				db, first, "our-channel", 1, stale_before
			),
			"claimed",
		)
		self.assertEqual(
			ai_service.ai_repo.claim_reply_processing(
				db, first, "our-channel", 1, stale_before
			),
			"already_claimed",
		)
		self.assertEqual(
			ai_service.ai_repo.claim_reply_processing(
				db, second, "our-channel", 20, stale_before
			),
			"older_pending",
		)
		self.assertEqual(
			ai_service.ai_repo.claim_reply_processing(
				db, other_branch, "our-channel", 1, stale_before
			),
			"limit",
		)
		db.close()
		engine.dispose()

	def test_posting_child_reply_uses_thread_root_and_keeps_author_mention(self):
		root = SimpleNamespace(
			comment_id=1,
			youtube_comment_id="thread-root-youtube-id",
			parent_comment=None,
		)
		child = SimpleNamespace(
			comment_id=2,
			youtube_comment_id="thread-root-youtube-id.reply-id",
			parent_comment=root,
			thread_youtube_comment_id="thread-root-youtube-id",
			can_reply=True,
			author_channel_id="viewer-channel",
			author_name="Viewer Name",
			is_replied=False,
			ai_reply="@Viewer Name A response",
			reply_status="draft",
		)
		response = Mock(status_code=200)
		response.json.return_value = {"id": "posted-reply-id"}
		client = Mock()
		client.post.return_value = response
		db = Mock()

		with patch.object(
			ai_service,
			"_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service.ai_repo, "get_comment", return_value=child
		), patch.object(
			ai_service.ai_repo, "get_comments", return_value=[]
		), patch.object(
			ai_service, "_get_access_token", return_value="access-token"
		), patch.object(
			ai_service, "_get_direct_comment_replies", return_value=[]
		) as get_direct_replies, patch.object(
			ai_service.ai_repo, "claim_reply_posting", return_value=True
		), patch.object(
			ai_service, "get_sync_http_client", return_value=client
		), patch.object(
			ai_service.time, "sleep"
		), patch.object(
			ai_service.ai_repo, "mark_reply_posted"
		):
			result = ai_service.post_video_comment_reply(
				db, 7, "our-channel", "video-1", "thread-root-youtube-id.reply-id"
			)

		self.assertEqual(
			client.post.call_args.kwargs["json"]["snippet"]["parentId"],
			"thread-root-youtube-id",
		)
		self.assertEqual(
			client.post.call_args.kwargs["json"]["snippet"]["textOriginal"],
			"@Viewer Name A response",
		)
		get_direct_replies.assert_called_once_with(
			"access-token", "thread-root-youtube-id"
		)
		self.assertEqual(result["reply_status"], "posted")

	def test_branch_context_contains_ancestors_but_not_sibling_comments(self):
		root = SimpleNamespace(
			comment_id=1,
			author_channel_id="viewer-channel",
			comment_text="hi",
			parent_comment=None,
		)
		first_bot_reply = SimpleNamespace(
			comment_id=2,
			author_channel_id="our-channel",
			comment_text="@viewer Hello",
			parent_comment=root,
		)
		target = SimpleNamespace(
			comment_id=3,
			author_channel_id="viewer-channel",
			comment_text="Thanks, one question",
			parent_comment=first_bot_reply,
		)
		sibling = SimpleNamespace(
			comment_id=4,
			author_channel_id="viewer-channel",
			comment_text="A separate branch",
			parent_comment=first_bot_reply,
		)

		context = ai_service._build_comment_branch_context(target, "our-channel")

		self.assertIn("Viewer: hi", context)
		self.assertIn("Channel: @viewer Hello", context)
		self.assertIn("Viewer: Thanks, one question", context)
		self.assertNotIn(sibling.comment_text, context)

	def test_flat_reply_reconciliation_uses_author_mention_not_api_parent(self):
		comments = [
			{
				"youtube_comment_id": "thread-root",
				"author_name": "Root Viewer",
				"author_channel_id": "viewer",
				"replies": [
					{
						"youtube_comment_id": "viewer-followup",
						"author_name": "Branch Viewer",
						"author_channel_id": "viewer",
						"parent_youtube_comment_id": "thread-root",
						"youtube_reply_id": "bot-reply",
						"text": "A follow-up",
					},
					{
						"youtube_comment_id": "viewer-followup-2",
						"author_name": "Branch Viewer",
						"author_channel_id": "viewer",
						"parent_youtube_comment_id": "thread-root",
						"text": "Another follow-up",
					},
					{
						"youtube_comment_id": "bot-reply",
						"author_name": "Our Channel",
						"author_channel_id": "our-channel",
						"parent_youtube_comment_id": "thread-root",
						"text": "@Branch Viewer Here is the answer",
					},
					{
						"youtube_comment_id": "untracked-bot-reply",
						"author_name": "Our Channel",
						"author_channel_id": "our-channel",
						"parent_youtube_comment_id": "thread-root",
						"text": "@Branch Viewer Another answer",
					},
				],
			}
		]

		self.assertEqual(
			coments_fetching_service.collect_replied_youtube_comment_ids(
				comments, "our-channel"
			),
			{"viewer-followup"},
		)

	def test_reply_reconciliation_prefers_the_saved_answered_comment_mapping(self):
		comment = SimpleNamespace(
			youtube_comment_id="viewer-target",
			thread_youtube_comment_id="thread-root",
			author_name="Same Viewer",
			ai_reply="@Same Viewer Original draft",
		)
		saved_comment = SimpleNamespace(
			youtube_comment_id="viewer-target",
			youtube_reply_id="reply-for-target",
			thread_youtube_comment_id="thread-root",
			author_name="Same Viewer",
			author_channel_id="viewer",
		)
		replies = [
			{
				"youtube_comment_id": "reply-for-another-comment",
				"author_channel_id": "our-channel",
				"text": "@Same Viewer A different answer",
			},
			{
				"youtube_comment_id": "reply-for-target",
				"author_channel_id": "our-channel",
				"text": "@Same Viewer A manually edited answer",
			},
		]

		with patch.object(
			ai_service.ai_repo, "get_comments", return_value=[saved_comment]
		):
			existing = ai_service._find_existing_reply_for_comment(
				Mock(), 11, replies, "our-channel", comment
			)

		self.assertEqual(existing["youtube_comment_id"], "reply-for-target")

	def test_simultaneous_followups_are_each_processed_under_their_own_comment(self):
		root = SimpleNamespace(
			comment_id=1, youtube_comment_id="root", parent_comment=None,
			author_channel_id="viewer", comment_text="hi", thread_youtube_comment_id="root",
			reply_status="draft", is_replied=False, can_reply=True,
			published_at=datetime(2026, 1, 1),
		)
		first_bot_reply = SimpleNamespace(
			comment_id=2, youtube_comment_id="bot-1", parent_comment=root,
			author_channel_id="our-channel", comment_text="Hello",
			parent_youtube_comment_id="root", thread_youtube_comment_id="root", reply_status="draft",
			is_replied=False, can_reply=True, published_at=datetime(2026, 1, 1, 0, 1),
		)
		answered_viewer = SimpleNamespace(
			comment_id=3, youtube_comment_id="viewer-0", parent_comment=first_bot_reply,
			author_channel_id="viewer", comment_text="Earlier question",
			parent_youtube_comment_id="bot-1", thread_youtube_comment_id="root", reply_status="draft",
			is_replied=False, can_reply=True, published_at=datetime(2026, 1, 1, 0, 2),
		)
		followup_one = SimpleNamespace(
			comment_id=4, youtube_comment_id="viewer-1", parent_comment=first_bot_reply,
			author_channel_id="viewer", comment_text="Question one",
			parent_youtube_comment_id="bot-1", thread_youtube_comment_id="root", reply_status="draft",
			is_replied=False, can_reply=True, published_at=datetime(2026, 1, 1, 0, 3),
		)
		followup_two = SimpleNamespace(
			comment_id=5, youtube_comment_id="viewer-2", parent_comment=first_bot_reply,
			author_channel_id="viewer", comment_text="Question two",
			parent_youtube_comment_id="bot-1", thread_youtube_comment_id="root", reply_status="draft",
			is_replied=False, can_reply=True, published_at=datetime(2026, 1, 1, 0, 3),
		)
		second_bot_reply = SimpleNamespace(
			comment_id=6, youtube_comment_id="bot-2", parent_comment=answered_viewer,
			author_channel_id="our-channel", comment_text="Answer one",
			parent_youtube_comment_id="viewer-0", thread_youtube_comment_id="root", reply_status="draft",
			is_replied=False, can_reply=True, published_at=datetime(2026, 1, 1, 0, 4),
		)
		second_branch_followup = SimpleNamespace(
			comment_id=7, youtube_comment_id="viewer-3", parent_comment=second_bot_reply,
			author_channel_id="viewer", comment_text="Follow-up to answer one",
			parent_youtube_comment_id="bot-2", thread_youtube_comment_id="root", reply_status="draft",
			is_replied=False, can_reply=True, published_at=datetime(2026, 1, 1, 0, 5),
		)
		comments = [
			root, first_bot_reply, answered_viewer, followup_one, followup_two,
			second_bot_reply, second_branch_followup,
		]
		db = Mock()
		posted_ids = []
		acquired_branch_ids = []

		def acquire_branch(_db, comment):
			branch_id = comment.parent_youtube_comment_id or comment.youtube_comment_id
			acquired_branch_ids.append(branch_id)
			return branch_id

		with patch.object(
			ai_service, "_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service.ai_repo, "get_comments", return_value=comments,
		), patch.object(
			ai_service, "regenerate_reply_draft",
			return_value={"ai_reply": "generated", "skipped": False},
		), patch.object(
			ai_service, "post_video_comment_reply",
			side_effect=lambda _db, _user, _channel, _video, comment_id:
				posted_ids.append(comment_id),
		), patch.object(
			ai_service.ai_repo, "acquire_comment_branch_lock",
			side_effect=acquire_branch,
		), patch.object(
			ai_service.ai_repo, "release_comment_branch_lock",
		):
			result = ai_service._generate_and_post_video_replies(
				db, 7, "our-channel", "video-1",
				{comment.youtube_comment_id for comment in comments},
				retry_skipped_comments=False,
			)

		self.assertCountEqual(
			posted_ids, ["viewer-1", "viewer-2", "viewer-3"]
		)
		self.assertEqual(len(posted_ids), len(set(posted_ids)))
		self.assertEqual(result["posted"], 3)
		self.assertEqual(acquired_branch_ids, ["bot-1", "bot-1", "bot-2"])

	def test_prompt_replies_to_genuine_comments_and_limits_skips_to_abuse(self):
		request = ai_service._build_ai_request(
			"test-model", "Business: Example", "Aoa"
		)
		system_prompt = request["messages"][0]["content"]

		self.assertIn("Always respond warmly to greetings", system_prompt)
		self.assertIn("Respond to every genuine viewer comment", system_prompt)
		self.assertIn("short, vague", system_prompt)
		self.assertIn("Return SKIP only for obvious spam", system_prompt)
		self.assertNotIn("clearly unrelated", system_prompt)
		self.assertIn('"Aoa"', request["messages"][1]["content"])
		thread_request = ai_service._build_ai_request(
			"test-model", "Business: Example", "tell me something", True
		)
		self.assertIn(
			"questions about why the channel replied",
			thread_request["messages"][0]["content"],
		)
		self.assertNotIn("clearly unrelated", thread_request["messages"][0]["content"])
		self.assertIn(
			"reply in an existing YouTube thread",
			thread_request["messages"][1]["content"],
		)


class GenerateReplyDraftTests(unittest.IsolatedAsyncioTestCase):
	async def test_generates_drafts_for_top_level_and_viewer_reply_comments(self):
		root = SimpleNamespace(
			comment_id=1,
			youtube_comment_id="thread-root",
			parent_comment_id=None,
			comment_text="Aoa",
			author_channel_id="viewer-channel",
			can_reply=True,
			ai_reply=None,
			is_replied=False,
			reply_status="draft",
		)
		viewer_reply = SimpleNamespace(
			comment_id=2,
			youtube_comment_id="viewer-reply",
			parent_comment_id=1,
			comment_text="Hello",
			author_channel_id="another-viewer-channel",
			can_reply=True,
			ai_reply=None,
			is_replied=False,
			reply_status="draft",
		)
		bot_reply = SimpleNamespace(
			comment_id=3,
			youtube_comment_id="our-own-reply",
			parent_comment_id=1,
			comment_text="Our previous response",
			author_channel_id="our-channel",
			can_reply=True,
			ai_reply=None,
			is_replied=False,
			reply_status="draft",
		)
		db = Mock()
		with patch.object(
			ai_service,
			"_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service, "_build_prompt_context", return_value="Business: Example"
		), patch.object(
			ai_service.ai_repo,
			"get_video_comments",
			return_value=[root, viewer_reply, bot_reply],
		), patch.object(
			ai_service, "_get_ai_provider_config", return_value=("key", "url", "model")
		), patch.object(
			ai_service, "get_async_http_client", return_value=Mock()
		), patch.object(
			ai_service, "_generate_ai_reply_async", new_callable=AsyncMock
		) as generate_reply, patch.object(
			ai_service.ai_repo, "save_reply_draft"
		) as save_draft:
			generate_reply.return_value = "Wa alaikum assalam!"
			result = await ai_service.generate_video_reply_drafts(
				db, 7, "our-channel", "video-1"
			)

		self.assertEqual(generate_reply.await_count, 2)
		self.assertTrue(
			generate_reply.await_args_list[1].kwargs["is_thread_reply"]
		)
		self.assertEqual(save_draft.call_count, 2)
		self.assertEqual(
			result["results"],
			[
				{
					"youtube_comment_id": "thread-root",
					"ai_reply": "Wa alaikum assalam!",
					"is_replied": False,
					"skipped": False,
					"error": None,
				},
				{
					"youtube_comment_id": "viewer-reply",
					"ai_reply": "Wa alaikum assalam!",
					"is_replied": False,
					"skipped": False,
					"error": None,
				},
			],
		)
		self.assertEqual(result["next_offset"], 2)
		self.assertFalse(result["has_more"])


class ExplicitCommentReplyTests(unittest.TestCase):
	def test_manual_action_retries_a_previously_skipped_viewer_child(self):
		parent = SimpleNamespace(
			comment_id=10,
			youtube_comment_id="thread-root",
			parent_comment_id=None,
			parent_comment=None,
			author_channel_id="viewer-channel",
			comment_text="Original comment",
			youtube_reply_id=None,
			is_replied=True,
			reply_status="posted",
			can_reply=True,
		)
		child = SimpleNamespace(
			comment_id=11,
			youtube_comment_id="viewer-child",
			parent_comment_id=10,
			parent_comment=parent,
			author_channel_id="viewer-channel",
			comment_text="Follow-up comment",
			youtube_reply_id=None,
			is_replied=False,
			reply_status="skipped",
			can_reply=True,
		)
		db = Mock()
		regenerated_ids = []
		posted_ids = []

		def retry_skipped(_db, comment):
			comment.reply_status = "draft"
			return True

		def regenerate(*args):
			regenerated_ids.append(args[4])
			return {"ai_reply": "Here is something interesting.", "skipped": False}

		def post(*args):
			posted_ids.append(args[4])
			return {"is_replied": True}

		with patch.object(
			ai_service,
			"_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service.ai_repo, "get_comments", return_value=[parent, child]
		), patch.object(
			ai_service.ai_repo,
			"retry_skipped_reply",
			side_effect=retry_skipped,
		) as retry, patch.object(
			ai_service, "regenerate_reply_draft", side_effect=regenerate
		), patch.object(
			ai_service, "post_video_comment_reply", side_effect=post
		):
			result = ai_service.generate_and_post_video_replies(
				db,
				7,
				"our-channel",
				"video-1",
				{"thread-root", "viewer-child"},
			)

		retry.assert_called_once_with(db, child)
		self.assertEqual(regenerated_ids, ["viewer-child"])
		self.assertEqual(posted_ids, ["viewer-child"])
		self.assertEqual(result["posted"], 1)
		self.assertEqual(result["skipped"], 1)

	def test_manual_action_retries_a_previously_skipped_top_level_comment(self):
		comment = SimpleNamespace(
			comment_id=10,
			youtube_comment_id="viewer-root",
			parent_comment_id=None,
			parent_comment=None,
			author_channel_id="viewer-channel",
			comment_text="Original comment",
			youtube_reply_id=None,
			is_replied=False,
			reply_status="skipped",
			can_reply=True,
		)
		db = Mock()

		def retry_skipped(_db, skipped_comment):
			skipped_comment.reply_status = "draft"
			return True

		with patch.object(
			ai_service,
			"_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service.ai_repo, "get_comments", return_value=[comment]
		), patch.object(
			ai_service.ai_repo,
			"retry_skipped_reply",
			side_effect=retry_skipped,
		) as retry, patch.object(
			ai_service,
			"regenerate_reply_draft",
			return_value={
				"ai_reply": "Could you tell me a little more?",
				"skipped": False,
			},
		) as regenerate, patch.object(
			ai_service,
			"post_video_comment_reply",
			return_value={"is_replied": True},
		) as post:
			result = ai_service.generate_and_post_video_replies(
				db, 7, "our-channel", "video-1", {"viewer-root"}
			)

		retry.assert_called_once_with(db, comment)
		regenerate.assert_called_once()
		post.assert_called_once()
		self.assertEqual(result["posted"], 1)

	def test_manual_action_never_posts_saved_comments_absent_from_fresh_fetch(self):
		stale_child = SimpleNamespace(
			comment_id=11,
			youtube_comment_id="deleted-viewer-child",
			parent_comment_id=10,
			author_channel_id="viewer-channel",
			comment_text="Original comment",
			youtube_reply_id=None,
			is_replied=False,
			reply_status="draft",
			can_reply=True,
		)
		with patch.object(
			ai_service,
			"_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service.ai_repo, "get_comments", return_value=[stale_child]
		), patch.object(
			ai_service, "regenerate_reply_draft"
		) as regenerate, patch.object(
			ai_service, "post_video_comment_reply"
		) as post:
			result = ai_service.generate_and_post_video_replies(
				Mock(), 7, "our-channel", "video-1", set()
			)

		regenerate.assert_not_called()
		post.assert_not_called()
		self.assertEqual(result["total"], 0)
		self.assertEqual(result["attempted"], 0)

	def test_automatic_action_processes_saved_pending_comments_absent_from_fetch(self):
		saved_comment = SimpleNamespace(
			comment_id=11,
			youtube_comment_id="saved-viewer-comment",
			parent_comment_id=None,
			parent_comment=None,
			author_channel_id="viewer-channel",
			comment_text="A saved comment awaiting a reply",
			youtube_reply_id=None,
			is_replied=False,
			reply_status="draft",
			can_reply=True,
		)
		db = Mock()
		with patch.object(
			ai_service,
			"_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service.ai_repo, "get_comments", return_value=[saved_comment]
		), patch.object(
			ai_service.ai_repo, "acquire_comment_branch_lock", return_value=None
		), patch.object(
			ai_service, "regenerate_reply_draft",
			return_value={"ai_reply": "A reply", "skipped": False},
		) as regenerate, patch.object(
			ai_service, "post_video_comment_reply"
		) as post:
			result = ai_service.generate_and_post_new_video_replies(
				db, 7, "our-channel", "video-1", set()
			)

		regenerate.assert_called_once_with(
			db, 7, "our-channel", "video-1", "saved-viewer-comment"
		)
		post.assert_called_once()
		self.assertEqual(result["attempted"], 1)
		self.assertEqual(result["posted"], 1)

	def test_automatic_action_does_not_answer_known_bot_replies_again(self):
		root = SimpleNamespace(
			comment_id=1,
			youtube_comment_id="viewer-root",
			parent_comment_id=None,
			parent_comment=None,
			author_channel_id="viewer-channel",
			youtube_reply_id="our-existing-reply",
			is_replied=True,
			reply_status="posted",
			can_reply=True,
		)
		own_reply = SimpleNamespace(
			comment_id=2,
			youtube_comment_id="our-existing-reply",
			parent_comment_id=1,
			parent_comment=root,
			author_channel_id=None,
			youtube_reply_id=None,
			is_replied=False,
			reply_status="draft",
			can_reply=True,
		)
		with patch.object(
			ai_service,
			"_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service.ai_repo, "get_comments", return_value=[root, own_reply]
		), patch.object(
			ai_service, "regenerate_reply_draft"
		) as regenerate, patch.object(
			ai_service, "post_video_comment_reply"
		) as post:
			result = ai_service.generate_and_post_new_video_replies(
				Mock(),
				7,
				"our-channel",
				"video-1",
				{"viewer-root", "our-existing-reply"},
			)

		regenerate.assert_not_called()
		post.assert_not_called()
		self.assertEqual(result["posted"], 0)
		self.assertEqual(result["skipped"], 2)

	def test_automatic_action_skips_answered_comment_but_replies_to_follow_up(self):
		root = SimpleNamespace(
			comment_id=1,
			youtube_comment_id="viewer-root",
			parent_comment_id=None,
			parent_comment=None,
			author_channel_id="viewer-channel",
			comment_text="Follow-up comment",
			youtube_reply_id=None,
			is_replied=False,
			reply_status="draft",
			can_reply=True,
		)
		own_reply = SimpleNamespace(
			comment_id=2,
			youtube_comment_id="our-reply",
			parent_comment_id=1,
			parent_comment=root,
			author_channel_id="our-channel",
			youtube_reply_id=None,
			is_replied=False,
			reply_status="draft",
			can_reply=True,
		)
		follow_up = SimpleNamespace(
			comment_id=3,
			youtube_comment_id="viewer-follow-up",
			parent_comment_id=1,
			parent_comment=root,
			author_channel_id="viewer-channel",
			comment_text="Original comment",
			youtube_reply_id=None,
			is_replied=False,
			reply_status="draft",
			can_reply=True,
		)
		processed = []

		def regenerate(*args):
			processed.append(args[4])
			return {"ai_reply": "A contextual response", "skipped": False}

		with patch.object(
			ai_service,
			"_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service.ai_repo,
			"get_comments",
			return_value=[root, own_reply, follow_up],
		), patch.object(
			ai_service, "regenerate_reply_draft", side_effect=regenerate
		), patch.object(
			ai_service, "post_video_comment_reply"
		) as post:
			result = ai_service.generate_and_post_new_video_replies(
				Mock(),
				7,
				"our-channel",
				"video-1",
				{"viewer-root", "our-reply", "viewer-follow-up"},
				already_replied_comment_ids={"viewer-root"},
			)

		self.assertEqual(processed, ["viewer-follow-up"])
		post.assert_called_once()
		self.assertEqual(result["posted"], 1)
		self.assertEqual(result["skipped"], 2)

	def test_automatic_action_processes_every_unanswered_comment_depth(self):
		root = SimpleNamespace(
			comment_id=1,
			youtube_comment_id="viewer-root",
			parent_comment_id=None,
			parent_comment=None,
			author_channel_id="viewer-channel",
			comment_text="Follow-up comment",
			youtube_reply_id=None,
			is_replied=False,
			reply_status="draft",
			can_reply=True,
		)
		child = SimpleNamespace(
			comment_id=2,
			youtube_comment_id="viewer-child",
			parent_comment_id=1,
			parent_comment=root,
			author_channel_id="viewer-channel",
			comment_text="Follow-up comment",
			youtube_reply_id=None,
			is_replied=False,
			reply_status="draft",
			can_reply=True,
		)
		grandchild = SimpleNamespace(
			comment_id=3,
			youtube_comment_id="viewer-grandchild",
			parent_comment_id=2,
			parent_comment=child,
			author_channel_id="viewer-channel",
			comment_text="Viewer comment",
			youtube_reply_id=None,
			is_replied=False,
			reply_status="draft",
			can_reply=True,
		)
		processed = []

		def regenerate(*args):
			processed.append(args[4])
			return {"ai_reply": "Contextual response", "skipped": False}

		with patch.object(
			ai_service,
			"_get_selected_video",
			return_value=SimpleNamespace(selected_video_id=11),
		), patch.object(
			ai_service.ai_repo,
			"get_comments",
			return_value=[root, child, grandchild],
		), patch.object(
			ai_service, "regenerate_reply_draft", side_effect=regenerate
		), patch.object(
			ai_service, "post_video_comment_reply", side_effect=lambda *args: None
		) as post:
			result = ai_service.generate_and_post_new_video_replies(
				Mock(),
				7,
				"our-channel",
				"video-1",
				{"viewer-root", "viewer-child", "viewer-grandchild"},
			)

		self.assertEqual(
			processed, ["viewer-root", "viewer-child", "viewer-grandchild"]
		)
		self.assertEqual(post.call_count, 3)
		self.assertEqual(result["posted"], 3)

	def test_explicit_action_skips_already_replied_comments(self):
		comments = [
			SimpleNamespace(
				comment_id=1,
				youtube_comment_id="top-with-replies",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				comment_text="Viewer reply",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
			),
			SimpleNamespace(
				comment_id=2,
				youtube_comment_id="viewer-reply-1",
				parent_comment_id=1,
				author_channel_id="viewer-channel",
				comment_text="Viewer reply",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
			),
			SimpleNamespace(
				comment_id=3,
				youtube_comment_id="viewer-reply-2",
				parent_comment_id=1,
				author_channel_id="viewer-channel",
				comment_text="Viewer comment",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
			),
			SimpleNamespace(
				comment_id=4,
				youtube_comment_id="top-without-replies",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				comment_text="Viewer comment",
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
				comment_text="Viewer comment",
				youtube_reply_id=None,
				is_replied=True,
				reply_status="posted",
			),
			SimpleNamespace(
				comment_id=7,
				youtube_comment_id="unanswered-top-level",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				comment_text="A new viewer comment",
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
			SimpleNamespace(
				comment_id=9,
				youtube_comment_id="skipped-by-ai",
				parent_comment_id=None,
				author_channel_id="viewer-channel",
				comment_text="A comment to skip",
				youtube_reply_id=None,
				is_replied=False,
				reply_status="draft",
			),
		]
		comments_by_id = {comment.comment_id: comment for comment in comments}
		for comment in comments:
			comment.parent_comment = comments_by_id.get(comment.parent_comment_id)
		regenerated_ids = []
		posted_ids = []

		def regenerate(*args):
			regenerated_ids.append(args[4])
			if args[4] == "skipped-by-ai":
				return {"ai_reply": None, "skipped": True}
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
				Mock(),
				7,
				"our-channel",
				"video-1",
				{comment.youtube_comment_id for comment in comments},
			)

		self.assertEqual(regenerated_ids, [
			"top-with-replies",
			"viewer-reply-1",
			"viewer-reply-2",
			"unanswered-top-level",
			"skipped-by-ai",
		])
		self.assertEqual(posted_ids, regenerated_ids[:-1])
		self.assertEqual(result["attempted"], 5)
		self.assertEqual(result["posted"], 4)
		self.assertEqual(result["skipped"], 5)


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
					"items": [thread("top-1", reply_count=1001, can_reply=False)],
					"nextPageToken": "next-thread-page",
				}

			reply_calls += 1
			page_index = int(params.get("pageToken", 0))
			start = page_index * 100
			end = min(start + 100, 1001)
			return {
				"items": [
					{
						"id": f"reply-{index}",
						"snippet": {
							"textDisplay": f"Reply {index}",
							"authorChannelId": {"value": "viewer-channel"},
						},
					}
					for index in range(start, end)
				],
				**(
					{"nextPageToken": str(page_index + 1)}
					if end < 1001
					else {}
				),
			}

		with patch.object(coments_fetching_service, "_youtube_get", side_effect=fetch):
			result = coments_fetching_service._get_all_comments(
				"access-token",
				"video-1",
				max_comments=None,
				max_replies=None,
			)

		self.assertEqual(thread_calls, 2)
		self.assertEqual(reply_calls, 11)
		self.assertEqual(len(result), 2)
		self.assertEqual(len(result[0]["replies"]), 1001)
		self.assertEqual(result[0]["author_channel_id"], "viewer-channel")
		self.assertFalse(result[0]["can_reply"])
		self.assertFalse(result[0]["replies"][0]["can_reply"])
		self.assertEqual(
			result[0]["replies"][1000]["author_channel_id"], "viewer-channel"
		)
		self.assertEqual(result[1]["youtube_comment_id"], "top-2")
		self.assertEqual(result[1]["replies"], [])
		self.assertFalse(result[1]["can_reply"])

	def test_reply_detection_handles_threads_with_one_thousand_replies(self):
		start = datetime(2026, 10, 21, tzinfo=timezone.utc)

		def published_at(minutes):
			return (start + timedelta(minutes=minutes)).isoformat()

		root = {
			"youtube_comment_id": "root",
			"author_name": "root-viewer",
			"author_channel_id": "viewer-channel",
			"published_at": published_at(0),
		}
		replies = [
			{
				"youtube_comment_id": "first-ai-reply",
				"author_channel_id": "our-channel",
				"text": "@root-viewer welcome",
				"published_at": published_at(1),
			}
		]
		expected_replied_ids = {"root"}
		for index in range(499):
			viewer_id = f"viewer-{index}"
			expected_replied_ids.add(viewer_id)
			replies.extend(
				[
					{
						"youtube_comment_id": viewer_id,
						"author_name": viewer_id,
						"author_channel_id": "viewer-channel",
						"published_at": published_at(2 + index * 2),
					},
					{
						"youtube_comment_id": f"ai-{index}",
						"author_channel_id": "our-channel",
						"text": f"@{viewer_id} answer",
						"published_at": published_at(3 + index * 2),
					},
				]
			)
		replies.append(
			{
				"youtube_comment_id": "latest-viewer",
				"author_channel_id": "viewer-channel",
				"published_at": published_at(1000),
			}
		)

		result = coments_fetching_service.collect_replied_youtube_comment_ids(
			[{**root, "replies": replies}], "our-channel"
		)

		self.assertEqual(len(replies), 1000)
		self.assertEqual(result, expected_replied_ids)
		self.assertNotIn("latest-viewer", result)


class PeriodicMonitorCycleTests(unittest.TestCase):
	def test_comment_monitor_fetches_all_pages_then_generates_and_posts(self):
		db = Mock()
		db.__enter__ = Mock(return_value=db)
		db.__exit__ = Mock(return_value=False)
		fetched_comments = [
			{
				"youtube_comment_id": "root-1",
				"replies": [{"youtube_comment_id": "reply-1", "replies": []}],
			}
		]
		reply_summary = {
			"attempted": 2,
			"posted": 2,
			"skipped": 0,
			"failed": 0,
		}
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
			return_value=fetched_comments,
		) as fetch, patch.object(
			ai_service,
			"generate_and_post_new_video_replies",
			return_value=reply_summary,
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
		reply.assert_called_once_with(
			db,
			12,
			"our-channel",
			"video-5",
			{"root-1", "reply-1"},
			already_replied_comment_ids=set(),
		)
		self.assertEqual(comment_monitor_service.COMMENT_FETCH_INTERVAL_SECONDS, 10)

	def test_unauthorized_user_is_paused_for_remaining_videos(self):
		initial_db, fetch_db, pause_db = [Mock() for _ in range(3)]
		for db in (initial_db, fetch_db, pause_db):
			db.__enter__ = Mock(return_value=db)
			db.__exit__ = Mock(return_value=False)

		with patch.object(
			comment_monitor_service.db_manager,
			"SessionLocal",
			side_effect=[initial_db, fetch_db, pause_db],
		), patch.object(
			comment_monitor_service.ai_repo,
			"get_selected_videos_for_monitoring",
			return_value=[
				(12, "our-channel", "video-1"),
				(12, "our-channel", "video-2"),
			],
		), patch.object(
			comment_monitor_service.coments_fetching_service,
			"fetch_video_comments",
			side_effect=HTTPException(status_code=401, detail="Sign in to Google again"),
		) as fetch, patch.object(
			comment_monitor_service.auth_repository,
			"set_comment_monitoring_enabled",
		) as pause_monitoring:
			comment_monitor_service.run_comment_monitoring_cycle()

		fetch.assert_called_once()
		pause_monitoring.assert_called_once_with(pause_db, 12, False)
		pause_db.commit.assert_called_once()


class PeriodicMonitorLoopTests(unittest.IsolatedAsyncioTestCase):
	async def test_loop_runs_full_scan_each_cycle(self):
		with patch.object(
			comment_monitor_service,
			"run_comment_monitoring_cycle",
		) as run_cycle, patch.object(
			comment_monitor_service.asyncio,
			"sleep",
			new_callable=AsyncMock,
			side_effect=[None, asyncio.CancelledError],
		) as sleep:
			with self.assertRaises(asyncio.CancelledError):
				await comment_monitor_service.run_comment_monitoring_loop()

		self.assertEqual(
			run_cycle.call_args_list,
			[call(), call()],
		)
		self.assertTrue(
			all(
				0 <= sleep_call.args[0] <= 10
				for sleep_call in sleep.call_args_list
			)
		)


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
