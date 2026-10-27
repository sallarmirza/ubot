import logging

import httpx
from fastapi import HTTPException

from core.config import settings
from schema.contact_schema import ContactRequest
from services.http_clients import get_async_http_client


logger = logging.getLogger(__name__)
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
RESEND_EMAILS_URL = "https://api.resend.com/emails"


async def send_contact_message(payload: ContactRequest) -> None:
	if payload.website:
		raise HTTPException(status_code=400, detail="Contact form submission rejected")

	if not all(
		(
			settings.RECAPTCHA_SECRET_KEY,
			settings.RESEND_API_KEY,
			settings.RESEND_FROM_EMAIL,
			settings.CONTACT_EMAIL_TO,
		)
	):
		logger.error("Contact endpoint is missing required email or reCAPTCHA settings")
		raise HTTPException(
			status_code=503, detail="Contact form is temporarily unavailable"
		)

	client = get_async_http_client()
	try:
		captcha_response = await client.post(
			RECAPTCHA_VERIFY_URL,
			data={
				"secret": settings.RECAPTCHA_SECRET_KEY,
				"response": payload.recaptcha_token,
			},
			timeout=10,
		)
	except httpx.RequestError as error:
		logger.error("Could not reach the reCAPTCHA verification service")
		raise HTTPException(
			status_code=503, detail="Could not verify the contact form"
		) from error
	if captcha_response.status_code != 200:
		logger.error(
			"reCAPTCHA verification returned HTTP %s",
			captcha_response.status_code,
		)
		raise HTTPException(
			status_code=503, detail="Could not verify the contact form"
		)
	try:
		captcha_valid = captcha_response.json().get("success") is True
	except ValueError as error:
		logger.error("reCAPTCHA verification returned invalid JSON")
		raise HTTPException(
			status_code=503, detail="Could not verify the contact form"
		) from error
	if not captcha_valid:
		raise HTTPException(status_code=400, detail="reCAPTCHA verification failed")

	message_lines = [
		f"Name: {payload.name}",
		f"Email: {payload.email}",
	]
	if payload.company:
		message_lines.append(f"Company: {payload.company}")
	if payload.channels:
		message_lines.append(f"Channels: {payload.channels}")
	if payload.volume:
		message_lines.append(f"Monthly volume: {payload.volume}")
	if payload.message:
		message_lines.extend(["", payload.message])
	message = "\n".join(message_lines)
	try:
		email_response = await client.post(
			RESEND_EMAILS_URL,
			headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
			json={
				"from": settings.RESEND_FROM_EMAIL,
				"to": [settings.CONTACT_EMAIL_TO],
				"reply_to": payload.email,
				"subject": "New website contact message",
				"text": message,
			},
			timeout=15,
		)
	except httpx.RequestError as error:
		logger.error("Could not reach the email delivery service")
		raise HTTPException(
			status_code=502, detail="Could not send the contact message"
		) from error
	if not email_response.is_success:
		logger.error(
			"Email delivery service returned HTTP %s",
			email_response.status_code,
		)
		raise HTTPException(
			status_code=502, detail="Could not send the contact message"
		)
