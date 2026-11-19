import logging
from uuid import uuid4

import httpx
from fastapi import HTTPException

from core.config import settings
from schema.contact_schema import ContactRequest
from services.http_clients import get_async_http_client


logger = logging.getLogger(__name__)
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
RESEND_EMAILS_URL = "https://api.resend.com/emails"


async def send_contact_message(payload: ContactRequest) -> tuple[str, str | None]:
	request_id = uuid4().hex
	logger.info("Contact request started (request_id=%s)", request_id)

	if payload.website:
		logger.warning(
			"Contact request rejected by honeypot (request_id=%s)", request_id
		)
		raise HTTPException(
			status_code=400,
			detail=f"Contact form submission rejected (reference: {request_id})",
		)

	required_settings = {
		"RECAPTCHA_SECRET_KEY": settings.RECAPTCHA_SECRET_KEY,
		"RESEND_API_KEY": settings.RESEND_API_KEY,
		"RESEND_FROM_EMAIL": settings.RESEND_FROM_EMAIL,
		"CONTACT_EMAIL_TO": settings.CONTACT_EMAIL_TO,
	}
	missing_settings = [
		name for name, value in required_settings.items() if not value
	]
	if missing_settings:
		logger.error(
			"Contact endpoint is missing required settings: %s (request_id=%s)",
			", ".join(missing_settings),
			request_id,
		)
		raise HTTPException(
			status_code=503,
			detail=f"Contact form is temporarily unavailable (reference: {request_id})",
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
		logger.error(
			"Could not reach the reCAPTCHA verification service "
			"(error=%s, request_id=%s)",
			type(error).__name__,
			request_id,
		)
		raise HTTPException(
			status_code=503,
			detail=f"Could not verify the contact form (reference: {request_id})",
		) from error
	if captcha_response.status_code != 200:
		logger.error(
			"reCAPTCHA verification returned HTTP %s (request_id=%s)",
			captcha_response.status_code,
			request_id,
		)
		raise HTTPException(
			status_code=503,
			detail=f"Could not verify the contact form (reference: {request_id})",
		)
	try:
		captcha_result = captcha_response.json()
	except ValueError as error:
		logger.error(
			"reCAPTCHA verification returned invalid JSON (request_id=%s)",
			request_id,
		)
		raise HTTPException(
			status_code=503,
			detail=f"Could not verify the contact form (reference: {request_id})",
		) from error
	if not isinstance(captcha_result, dict):
		logger.error(
			"reCAPTCHA verification returned an unexpected response "
			"(request_id=%s)",
			request_id,
		)
		raise HTTPException(
			status_code=503,
			detail=f"Could not verify the contact form (reference: {request_id})",
		)
	if captcha_result.get("success") is not True:
		error_codes = captcha_result.get("error-codes", [])
		if not isinstance(error_codes, list):
			error_codes = []
		safe_error_codes = [
			code[:100] for code in error_codes if isinstance(code, str)
		][:10]
		logger.warning(
			"reCAPTCHA verification failed (error_codes=%s, request_id=%s)",
			safe_error_codes or "none",
			request_id,
		)
		raise HTTPException(
			status_code=400,
			detail=f"reCAPTCHA verification failed (reference: {request_id})",
		)

	logger.info("reCAPTCHA verified (request_id=%s)", request_id)

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
		logger.error(
			"Could not reach the email delivery service "
			"(error=%s, request_id=%s)",
			type(error).__name__,
			request_id,
		)
		raise HTTPException(
			status_code=502,
			detail=f"Could not send the contact message (reference: {request_id})",
		) from error
	if not email_response.is_success:
		try:
			error_body = email_response.json()
		except ValueError:
			error_body = {}
		error_details = ""
		if isinstance(error_body, dict):
			error_details = " ".join(
				value.strip()
				for key in ("name", "message")
				if isinstance((value := error_body.get(key)), str) and value.strip()
			)
		if error_details:
			error_details = " ".join(error_details.split())[:500]
		logger.error(
			"Email delivery service returned HTTP %s: %s (request_id=%s)",
			email_response.status_code,
			error_details or "no provider error details",
			request_id,
		)
		raise HTTPException(
			status_code=502,
			detail=f"Could not send the contact message (reference: {request_id})",
		)

	try:
		provider_response = email_response.json()
	except ValueError:
		provider_response = {}
	provider_message_id = (
		provider_response.get("id")
		if isinstance(provider_response, dict)
		and isinstance(provider_response.get("id"), str)
		else None
	)
	if provider_message_id is None:
		logger.warning(
			"Email provider accepted request without a message ID "
			"(HTTP %s, request_id=%s)",
			email_response.status_code,
			request_id,
		)
	else:
		logger.info(
			"Email delivery service accepted contact message "
			"(HTTP %s, provider_message_id=%s, request_id=%s)",
			email_response.status_code,
			provider_message_id,
			request_id,
		)
	return request_id, provider_message_id
