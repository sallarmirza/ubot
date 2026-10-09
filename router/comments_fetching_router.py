from fastapi import Query
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from db_manager import db_manager
from db_model import User
from services import coments_fetching_service


router = APIRouter(prefix="/comments", tags=["comments"])


@router.get("/{channel_id}/{video_id}")
def get_comments(
	channel_id: str,
	video_id: str,
	max_comments: int = Query(50, ge=1, le=100),
	max_replies: int = Query(0, ge=0, le=5),
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	return coments_fetching_service.fetch_video_comments(
		db, user.user_id, channel_id, video_id, max_comments, max_replies
	)
