import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from router.contact_router import router, submit_contact_message
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

	@patch("router.contact_router.send_contact_message", new_callable=AsyncMock)
	async def test_success_response_exposes_safe_provider_diagnostics(
		self, send_contact_message
	):
		send_contact_message.return_value = ("request-123", "resend-message-123")

		response = await submit_contact_message(self.payload)

		self.assertEqual(response.email_status, "accepted_by_provider")
		self.assertEqual(response.request_id, "request-123")
		self.assertEqual(response.provider_message_id, "resend-message-123")
		self.assertIn("accepted by the email provider", response.message)

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
				Mock(
					status_code=200,
					is_success=True,
					json=lambda: {"id": "resend-message-123"},
				),
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
			with self.assertLogs(
				"services.contact_service", level="INFO"
			) as captured:
				result = await contact_service.send_contact_message(self.payload)

		self.assertIn("accepted contact message (HTTP 200", captured.output[-1])
		self.assertIn("resend-message-123", captured.output[-1])
		self.assertEqual(result[1], "resend-message-123")
		self.assertEqual(client.post.await_count, 2)
		email_request = client.post.await_args_list[1]
		self.assertEqual(email_request.args[0], contact_service.RESEND_EMAILS_URL)
		self.assertEqual(
			email_request.kwargs["json"]["reply_to"], "visitor@example.com"
		)
		self.assertIn("Please contact me.", email_request.kwargs["json"]["text"])
		self.assertEqual(
			email_request.kwargs["headers"]["Authorization"],
			"Bearer resend-secret",
		)

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

	@patch("services.contact_service.get_async_http_client")
	async def test_missing_email_settings_are_reported_without_sending(
		self, get_client
	):
		client = Mock()
		get_client.return_value = client
		with patch.multiple(
			contact_service.settings,
			RECAPTCHA_SECRET_KEY="captcha-secret",
			RESEND_API_KEY="resend-secret",
			RESEND_FROM_EMAIL=None,
			CONTACT_EMAIL_TO=None,
		):
			with self.assertLogs(
				"services.contact_service", level="ERROR"
			) as captured:
				with self.assertRaises(HTTPException) as raised:
					await contact_service.send_contact_message(self.payload)

		self.assertEqual(raised.exception.status_code, 503)
		self.assertIn("RESEND_FROM_EMAIL", captured.output[0])
		self.assertIn("CONTACT_EMAIL_TO", captured.output[0])
		get_client.assert_not_called()

	@patch("services.contact_service.get_async_http_client")
	async def test_logs_email_provider_rejection_reason(self, get_client):
		client = Mock()
		client.post = AsyncMock(
			side_effect=[
				Mock(status_code=200, json=lambda: {"success": True}),
				Mock(
					status_code=403,
					is_success=False,
					json=lambda: {
						"name": "validation_error",
						"message": "The sender domain is not verified",
					},
				),
			]
		)
		get_client.return_value = client
		with patch.multiple(
			contact_service.settings,
			RECAPTCHA_SECRET_KEY="captcha-secret",
			RESEND_API_KEY="resend-secret",
			RESEND_FROM_EMAIL="Leadhive <leads@leadhive-ai.com>",
			CONTACT_EMAIL_TO="Leads@leadhive-ai.com",
		):
			with self.assertLogs(
				"services.contact_service", level="ERROR"
			) as captured:
				with self.assertRaises(HTTPException) as raised:
					await contact_service.send_contact_message(self.payload)

		self.assertEqual(raised.exception.status_code, 502)
		self.assertIn("HTTP 403", captured.output[0])
		self.assertIn("The sender domain is not verified", captured.output[0])

	@patch("services.contact_service.get_async_http_client")
	async def test_missing_provider_message_id_is_logged_without_false_failure(
		self, get_client
	):
		client = Mock()
		client.post = AsyncMock(
			side_effect=[
				Mock(status_code=200, json=lambda: {"success": True}),
				Mock(
					status_code=200,
					is_success=True,
					json=lambda: {"unexpected": "response"},
				),
			]
		)
		get_client.return_value = client
		with patch.multiple(
			contact_service.settings,
			RECAPTCHA_SECRET_KEY="captcha-secret",
			RESEND_API_KEY="resend-secret",
			RESEND_FROM_EMAIL="Leadhive <leads@leadhive-ai.com>",
			CONTACT_EMAIL_TO="Leads@leadhive-ai.com",
		):
			with self.assertLogs(
				"services.contact_service", level="WARNING"
			) as captured:
				result = await contact_service.send_contact_message(self.payload)

		self.assertIsNone(result[1])
		self.assertIn("without a message ID", captured.output[0])

	def test_contact_payload_rejects_blank_and_invalid_fields(self):
		with self.assertRaises(ValueError):
			ContactRequest(
				name=" ",
				email="not-an-email",
				message="A message",
				recaptcha_token="token",
			)
