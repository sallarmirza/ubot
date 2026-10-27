from fastapi import APIRouter

from schema.contact_schema import ContactRequest, ContactResponse
from services.contact_service import send_contact_message


router = APIRouter(tags=["contact"])


@router.post("/api/contact.php", response_model=ContactResponse)
async def submit_contact_message(payload: ContactRequest) -> ContactResponse:
	await send_contact_message(payload)
	return ContactResponse(message="Your message has been sent.")
