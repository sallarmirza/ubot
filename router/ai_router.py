from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from db_manager import db_manager
from db_model import User
from repositories import auth_repository
from schema.ai_schema import ReplyDraftBatch, ReplyDraftResult
from services import ai_service, coments_fetching_service


router = APIRouter(prefix="/ai", tags=["AI replies"])


def _require_comment_monitoring_enabled(db: Session, user_id: int) -> None:
	if not auth_repository.is_comment_monitoring_enabled(db, user_id):
		raise HTTPException(
			status_code=409,
			detail="Turn on automatic comment replies to generate or post replies",
		)


@router.post("/{channel_id}/{video_id}/generate-and-post-replies")
def generate_and_post_replies(
	channel_id: str,
	video_id: str,
	db: Session = Depends(db_manager.get_db),
	user: User = Depends(get_current_user),
):
	_require_comment_monitoring_enabled(db, user.user_id)
	fetched_comments = coments_fetching_service.fetch_video_comments(
		db,
		user.user_id,
		channel_id,
		video_id,
		max_comments=None,
		max_replies=None,
	)
	return ai_service.generate_and_post_video_replies(
		db,
		user.user_id,
		channel_id,
		video_id,
		coments_fetching_service.collect_youtube_comment_ids(fetched_comments),
		already_replied_comment_ids=(
			coments_fetching_service.collect_replied_youtube_comment_ids(
				fetched_comments, channel_id
			)
		),
	)


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
	_require_comment_monitoring_enabled(db, user.user_id)
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
	_require_comment_monitoring_enabled(db, user.user_id)
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
	_require_comment_monitoring_enabled(db, user.user_id)
	return ai_service.post_video_comment_reply(
		db, user.user_id, channel_id, video_id, youtube_comment_id
	)
