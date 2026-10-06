from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from db_manager import db_manager
from db_model import User
from schema.analytics_schema import SelectedVideoAnalytics
from services import analytics_service


router = APIRouter(prefix="/analytics", tags=["analytics"])


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
