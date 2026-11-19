from fastapi import APIRouter

from schema.contact_schema import ContactRequest, ContactResponse
from services.contact_service import send_contact_message


router = APIRouter(tags=["contact"])


@router.post("/api/contact.php", response_model=ContactResponse)
async def submit_contact_message(payload: ContactRequest) -> ContactResponse:
	request_id, provider_message_id = await send_contact_message(payload)
	return ContactResponse(
		message=(
			"Your message was accepted by the email provider."
			if provider_message_id
			else "The email provider accepted the message but returned no message ID."
		),
		email_status="accepted_by_provider",
		request_id=request_id,
		provider_message_id=provider_message_id,
	)
