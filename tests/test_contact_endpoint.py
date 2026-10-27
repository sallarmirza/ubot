import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from router.contact_router import router
from schema.contact_schema import ContactRequest
from services import contact_service


class ContactEndpointTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.payload = ContactRequest(
			name="Test Visitor",
			email="visitor@example.com",
			message="Please contact me.",
			recaptcha_token="captcha-token",
		)

	def test_endpoint_uses_requested_url(self):
		self.assertTrue(
			any(
				route.path == "/api/contact.php" and "POST" in route.methods
				for route in router.routes
			)
		)

	def test_accepts_frontend_camel_case_captcha_and_lead_fields(self):
		payload = ContactRequest.model_validate(
			{
				"name": "Visitor",
				"email": "visitor@example.com",
				"company": "Example company",
				"channels": "WhatsApp",
				"volume": "Under 1,000",
				"website": "",
				"recaptchaToken": "captcha-token",
				"captchaToken": "captcha-token",
			}
		)

		self.assertEqual(payload.recaptcha_token, "captcha-token")
		self.assertEqual(payload.company, "Example company")
		self.assertEqual(payload.channels, "WhatsApp")
		self.assertEqual(payload.volume, "Under 1,000")

	@patch("services.contact_service.get_async_http_client")
	async def test_verifies_captcha_then_sends_email(self, get_client):
		client = Mock()
		client.post = AsyncMock(
			side_effect=[
				Mock(status_code=200, json=lambda: {"success": True}),
				Mock(status_code=200, is_success=True),
			]
		)
		get_client.return_value = client
		with patch.multiple(
			contact_service.settings,
			RECAPTCHA_SECRET_KEY="captcha-secret",
			RESEND_API_KEY="resend-secret",
			RESEND_FROM_EMAIL="LeadHive <support@example.com>",
			CONTACT_EMAIL_TO="contact@example.com",
		):
			await contact_service.send_contact_message(self.payload)

		self.assertEqual(client.post.await_count, 2)
		email_request = client.post.await_args_list[1]
		self.assertEqual(email_request.args[0], contact_service.RESEND_EMAILS_URL)
		self.assertEqual(
			email_request.kwargs["json"]["reply_to"], "visitor@example.com"
		)
		self.assertIn("Please contact me.", email_request.kwargs["json"]["text"])

	@patch("services.contact_service.get_async_http_client")
	async def test_invalid_captcha_does_not_send_email(self, get_client):
		client = Mock()
		client.post = AsyncMock(
			return_value=Mock(status_code=200, json=lambda: {"success": False})
		)
		get_client.return_value = client
		with patch.multiple(
			contact_service.settings,
			RECAPTCHA_SECRET_KEY="captcha-secret",
			RESEND_API_KEY="resend-secret",
			RESEND_FROM_EMAIL="LeadHive <support@example.com>",
			CONTACT_EMAIL_TO="contact@example.com",
		):
			with self.assertRaises(HTTPException) as raised:
				await contact_service.send_contact_message(self.payload)

		self.assertEqual(raised.exception.status_code, 400)
		client.post.assert_awaited_once()

	def test_contact_payload_rejects_blank_and_invalid_fields(self):
		with self.assertRaises(ValueError):
			ContactRequest(
				name=" ",
				email="not-an-email",
				message="A message",
				recaptcha_token="token",
			)
