import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.path_normalization import NormalizeLeadingSlashesMiddleware
from router.analytics_router import router as analytics_router


class NormalizeLeadingSlashesMiddlewareTests(unittest.IsolatedAsyncioTestCase):
	def test_double_slash_pinned_analytics_request_reaches_endpoint(self):
		app = FastAPI()
		app.add_middleware(NormalizeLeadingSlashesMiddleware)
		app.include_router(analytics_router)
		expected = {
			"channel_id": "channel-1",
			"channel_name": "Channel",
			"channel_subscribers": 1,
			"channel_total_videos": 1,
			"video_id": "video-1",
			"video_title": "Video",
			"video_views": 1,
			"video_likes": 1,
			"video_comment_count": 0,
			"comments_fetched": 0,
			"max_comments": 100,
			"max_replies_per_comment": 50,
			"replied_comments": [],
			"unanswered_comments": [],
		}

		with patch(
			"services.pinned_analytics_service.get_public_pinned_analytics",
			return_value=expected,
		) as get_analytics:
			with TestClient(app) as client:
				response = client.get(
					"http://testserver//analytics/pinned"
					"?max_comments=100&max_replies=50"
				)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json(), expected)
		self.assertEqual(get_analytics.call_args.args[1:], (100, 50))

	async def test_normalizes_double_leading_slash_before_routing(self):
		routed_scope = None

		async def app(scope, receive, send):
			nonlocal routed_scope
			routed_scope = scope

		middleware = NormalizeLeadingSlashesMiddleware(app)
		scope = {
			"type": "http",
			"path": "//analytics/pinned",
			"raw_path": b"//analytics/pinned",
			"query_string": b"max_comments=100&max_replies=50",
		}

		await middleware(scope, None, None)

		self.assertEqual(routed_scope["path"], "/analytics/pinned")
		self.assertEqual(routed_scope["raw_path"], b"/analytics/pinned")
		self.assertEqual(
			routed_scope["query_string"], b"max_comments=100&max_replies=50"
		)
		self.assertEqual(scope["path"], "//analytics/pinned")

	async def test_leaves_single_leading_slash_unchanged(self):
		routed_scope = None

		async def app(scope, receive, send):
			nonlocal routed_scope
			routed_scope = scope

		scope = {"type": "http", "path": "/analytics/pinned"}
		await NormalizeLeadingSlashesMiddleware(app)(scope, None, None)

		self.assertIs(routed_scope, scope)
