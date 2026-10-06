from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from db_manager import db_manager
from db_model import User
from schema.business_profile_schema import BusinessProfileRequest
from services import business_profile_service


router = APIRouter(prefix="/business-profile", tags=["business profile"])


@router.post("")
def save_profile(
    payload: BusinessProfileRequest,
    db: Session = Depends(db_manager.get_db),
    user: User = Depends(get_current_user),
):
    """Save or update the signed-in user's channel profile."""
    return business_profile_service.save_business_profile(db, user.user_id, payload)


@router.get("/{channel_id}")
def get_profile(
    channel_id: str,
    db: Session = Depends(db_manager.get_db),
    user: User = Depends(get_current_user),
):
    """Load a profile for one of the signed-in user's channels."""
    return business_profile_service.get_business_profile(db, user.user_id, channel_id)