import hashlib
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from db_manager import Base
from db_model import DemoSession
from router.demo_router import (
	DEMO_COMMENT_LIMIT,
	DEMO_LIMIT_MESSAGE,
	DEMO_SESSION_COOKIE,
	DemoReplyRequest,
	generate_demo_reply,
	get_demo_video,
)


class DemoSessionLimitTests(unittest.TestCase):
	def setUp(self) -> None:
		self.engine = create_engine("sqlite:///:memory:")
		Base.metadata.create_all(self.engine)
		self.session_factory = sessionmaker(bind=self.engine)
		self.db = self.session_factory()
		self.client_ip = "198.51.100.10"

	def tearDown(self) -> None:
		self.db.close()
		self.engine.dispose()

	def make_request(self, cookie: str | None = None) -> Request:
		headers = [(b"x-forwarded-for", self.client_ip.encode("ascii"))]
		if cookie is not None:
			headers.append(
				(b"cookie", f"{DEMO_SESSION_COOKIE}={cookie}".encode("ascii"))
			)
		return Request(
			{
				"type": "http",
				"method": "POST",
				"scheme": "http",
				"path": "/demo/reply",
				"headers": headers,
				"client": (self.client_ip, 12345),
				"server": ("testserver", 80),
				"query_string": b"",
			}
		)

	def reply(self, cookie: str | None = None) -> Response:
		response = Response()
		generate_demo_reply(
			DemoReplyRequest(comment="A useful demo comment"),
			self.make_request(cookie),
			response,
			self.db,
		)
		return response

	@staticmethod
	def cookie_value(response: Response) -> str:
		cookie_header = response.headers["set-cookie"]
		return cookie_header.split(";", 1)[0].split("=", 1)[1]

	@patch("router.demo_router._consume_quota")
	@patch("router.demo_router.demo_service.generate_demo_reply")
	def test_two_comments_are_allowed_and_next_attempt_is_blocked(
		self,
		generate_reply,
		_consume_quota,
	) -> None:
		generate_reply.return_value = "Thanks for your comment."

		first_response = self.reply()
		cookie = self.cookie_value(first_response)
		cookie_header = first_response.headers["set-cookie"]
		self.reply(cookie)

		self.assertTrue(cookie_header.startswith(f"{DEMO_SESSION_COOKIE}="))
		self.assertIn("httponly", cookie_header.lower())
		self.assertIn("max-age=", cookie_header.lower())
		self.assertEqual(generate_reply.call_count, DEMO_COMMENT_LIMIT)
		self.db.close()
		self.db = self.session_factory()

		with self.assertRaises(HTTPException) as raised:
			self.reply(cookie)
		self.assertEqual(raised.exception.status_code, 429)
		self.assertEqual(raised.exception.detail, DEMO_LIMIT_MESSAGE)

		session_hash = hashlib.sha256(cookie.encode("ascii")).hexdigest()
		demo_session = self.db.get(DemoSession, session_hash)
		self.assertIsNotNone(demo_session)
		self.assertNotEqual(demo_session.session_token_hash, cookie)
		self.assertEqual(demo_session.comment_count, DEMO_COMMENT_LIMIT)
		self.assertTrue(demo_session.blocked)

	def test_opening_demo_video_sets_and_persists_session_cookie(self) -> None:
		response = Response()
		content = get_demo_video(self.make_request(), response, self.db)

		cookie = self.cookie_value(response)
		session_hash = hashlib.sha256(cookie.encode("ascii")).hexdigest()
		self.assertIn("video", content)
		self.assertIsNotNone(self.db.get(DemoSession, session_hash))
