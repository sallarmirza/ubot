from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from db_manager import db_manager
from db_model import User
from schema.ai_schema import ReplyDraftBatch, ReplyDraftResult
from services import ai_service


router = APIRouter(prefix="/ai", tags=["AI replies"])


@router.post(
	"/{channel_id}/{video_id}/generate-replies",
	response_model=ReplyDraftBatch,
)
async def generate_reply_drafts(
	channel_id: str,
	video_id: str,
	offset: int = Query(0, ge=0),
	limit: int = Query(20, ge=1, le=20),
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	return await ai_service.generate_video_reply_drafts(
		db, user.user_id, channel_id, video_id, offset=offset, max_drafts=limit
	)


@router.post(
	"/{channel_id}/{video_id}/comments/{youtube_comment_id}/regenerate-reply",
	response_model=ReplyDraftResult,
)
def regenerate_comment_reply(
	channel_id: str,
	video_id: str,
	youtube_comment_id: str,
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	return ai_service.regenerate_reply_draft(
		db, user.user_id, channel_id, video_id, youtube_comment_id
	)


@router.post("/{channel_id}/{video_id}/comments/{youtube_comment_id}/post-reply")
def post_comment_reply(
	channel_id: str,
	video_id: str,
	youtube_comment_id: str,
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	return ai_service.post_video_comment_reply(
		db, user.user_id, channel_id, video_id, youtube_comment_id
	)
