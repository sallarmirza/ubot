from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from db_manager import db_manager
from db_model import User
from schema.analytics_schema import SelectedVideoAnalytics
from schema.pinned_analytics_schema import (
	PinEnabledRequest,
	PinStatusResponse,
	PinVideoRequest,
	PinnedAnalyticsResponse,
)
from services import analytics_service
from services import pinned_analytics_service


router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/pin", response_model=PinStatusResponse)
def get_pin_status(
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	return pinned_analytics_service.get_pin_status(db, user.user_id)


@router.put("/pin", response_model=PinStatusResponse)
def configure_pin(
	payload: PinVideoRequest,
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	return pinned_analytics_service.configure_pin(
		db, user.user_id, payload.channel_id, payload.video_id
	)


@router.patch("/pin", response_model=PinStatusResponse)
def set_pin_enabled(
	payload: PinEnabledRequest,
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	return pinned_analytics_service.set_pin_enabled(
		db, user.user_id, payload.enabled
	)


@router.get("/pinned", response_model=PinnedAnalyticsResponse)
def get_pinned_analytics(
	max_comments: int = Query(default=100, ge=1, le=100),
	max_replies: int = Query(default=50, ge=0, le=200),
	db: Session = Depends(db_manager.get_db),
):
	"""Return the latest enabled pinned analytics without login."""
	return pinned_analytics_service.get_public_pinned_analytics(
		db, max_comments, max_replies
	)


@router.get("/public-pinned", response_model=PinnedAnalyticsResponse)
def get_public_pinned_analytics(
	max_comments: int = Query(default=100, ge=1, le=100),
	max_replies: int = Query(default=50, ge=0, le=200),
	db: Session = Depends(db_manager.get_db),
):
	"""Return analytics for the latest enabled pin without login."""
	return pinned_analytics_service.get_public_pinned_analytics(
		db, max_comments, max_replies
	)


@router.get("/selected-videos", response_model=list[SelectedVideoAnalytics])
def get_selected_video_analytics(
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	"""Return the analytics and saved comment activity for all selected videos."""
	return analytics_service.get_selected_video_analytics(db, user.user_id)


@router.get(
	"/selected-videos/{channel_id}/{video_id}",
	response_model=SelectedVideoAnalytics,
)
def get_video_analytics(
	channel_id: str,
	video_id: str,
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	"""Return analytics and saved comment activity for one selected video."""
	return analytics_service.get_video_analytics(
		db, user.user_id, channel_id, video_id
	)
