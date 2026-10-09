from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from db_manager import db_manager
from db_model import User
from schema.selection_video_schema import SelectedVideosRequest, VideoResponse
from services import selection_video_service


DEFAULT_VIDEO_LIMIT = selection_video_service.DEFAULT_VIDEO_LIMIT
MAX_VIDEO_LIMIT = selection_video_service.MAX_VIDEO_LIMIT


router = APIRouter(prefix="/selection-videos", tags=["video selection"])


@router.get("/{channel_id}", response_model=list[VideoResponse])
def get_channel_videos(
	channel_id: str,
	limit: int = Query(default=DEFAULT_VIDEO_LIMIT, ge=1, le=MAX_VIDEO_LIMIT),
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	"""Fetch and return the uploads for one of the user's channels."""
	return selection_video_service.list_channel_videos(db, user.user_id, channel_id, limit)


@router.post("/save", response_model=list[VideoResponse])
def save_selected_videos(
	payload: SelectedVideosRequest,
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	"""Persist selections from the local video catalog."""
	return selection_video_service.save_selected_videos(db, user.user_id, payload)
