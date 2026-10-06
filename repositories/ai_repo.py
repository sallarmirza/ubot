from sqlalchemy.orm import Session
from sqlalchemy import func, update
from sqlalchemy.orm.attributes import set_committed_value

from db_model import (
	BusinessSetup,
	Comments,
	TargetChannel,
	TargetVideo,
	Videos,
	YoutubeChannel,
)


def get_selected_video(
	db: Session,
	user_id: int,
	youtube_channel_id: str,
	youtube_video_id: str,
) -> TargetVideo | None:
	"""Return a selected video only when it belongs to the signed-in user."""
	return (
		db.query(TargetVideo)
		.join(Videos, TargetVideo.video_id == Videos.video_id)
		.join(TargetChannel, TargetChannel.target_channel_id == Videos.target_channel_id)
		.join(YoutubeChannel, YoutubeChannel.channel_id == TargetChannel.channel_id)
		.filter(
			YoutubeChannel.user_id == user_id,
			YoutubeChannel.youtube_channel_id == youtube_channel_id,
			TargetChannel.user_id == user_id,
			TargetVideo.user_id == user_id,
			Videos.youtube_video_id == youtube_video_id,
		)
		.first()
	)


def get_business_profile(
	db: Session, user_id: int, target_channel_id: int
) -> BusinessSetup | None:
	return (
		db.query(BusinessSetup)
		.filter_by(user_id=user_id, target_channel_id=target_channel_id)
		.first()
	)


def save_prompt_context(
	db: Session, selected_video: TargetVideo, prompt_context: str
) -> None:
	selected_video.prompt_context = prompt_context
	db.flush()


def get_top_level_comments(db: Session, selected_video_id: int) -> list[Comments]:
	return (
		db.query(Comments)
		.filter_by(selected_video_id=selected_video_id, parent_comment_id=None)
		.order_by(Comments.comment_id)
		.all()
	)


def get_video_comments(db: Session, selected_video_id: int) -> list[Comments]:
	return (
		db.query(Comments)
		.filter_by(selected_video_id=selected_video_id)
		.all()
	)


def get_top_level_comment(
	db: Session, selected_video_id: int, youtube_comment_id: str
) -> Comments | None:
	return (
		db.query(Comments)
		.filter_by(
			selected_video_id=selected_video_id,
			youtube_comment_id=youtube_comment_id,
			parent_comment_id=None,
		)
		.first()
	)


def save_reply_draft(db: Session, comment: Comments, ai_reply: str) -> None:
	if not ai_reply or len(ai_reply) > 800:
		raise ValueError("AI reply must contain between 1 and 800 characters")
	if comment.is_replied:
		raise ValueError("A reply has already been posted for this comment")
	result = db.execute(
		update(Comments)
		.where(
			Comments.comment_id == comment.comment_id,
			Comments.is_replied.is_(False),
			Comments.reply_status == "draft",
		)
		.values(ai_reply=ai_reply)
		.execution_options(synchronize_session=False)
	)
	if result.rowcount != 1:
		raise ValueError("Reply posting is in progress or has an uncertain outcome")
	set_committed_value(comment, "ai_reply", ai_reply)


def claim_reply_posting(db: Session, comment_id: int) -> bool:
	"""Atomically claim a draft so only one server process can post it."""
	result = db.execute(
		update(Comments)
		.where(
			Comments.comment_id == comment_id,
			Comments.is_replied.is_(False),
			Comments.ai_reply.is_not(None),
			Comments.reply_status == "draft",
		)
		.values(reply_status="posting", reply_posting_started_at=func.now())
		.execution_options(synchronize_session=False)
	)
	if result.rowcount != 1:
		db.rollback()
		return False
	db.commit()
	return True


def release_reply_posting(db: Session, comment_id: int) -> None:
	"""Make a draft retryable when YouTube definitively did not accept it."""
	db.execute(
		update(Comments)
		.where(Comments.comment_id == comment_id, Comments.reply_status == "posting")
		.values(reply_status="draft", reply_posting_started_at=None)
		.execution_options(synchronize_session=False)
	)
	db.commit()


def mark_reply_posting_unknown(db: Session, comment_id: int) -> None:
	"""Prevent unsafe retries when YouTube may have accepted an uncertain request."""
	db.execute(
		update(Comments)
		.where(Comments.comment_id == comment_id, Comments.reply_status == "posting")
		.values(reply_status="unknown")
		.execution_options(synchronize_session=False)
	)
	db.commit()


def mark_reply_posted(
	db: Session, comment: Comments, youtube_reply_id: str
) -> None:
	if not youtube_reply_id or len(youtube_reply_id) > 100:
		raise ValueError("YouTube reply ID is empty or exceeds the database limit")
	if comment.is_replied:
		raise ValueError("A reply has already been posted for this comment")
	if comment.reply_status != "posting":
		raise ValueError("Reply posting was not claimed")
	if not comment.ai_reply:
		raise ValueError("Generate or save a reply draft before posting")
	comment.youtube_reply_id = youtube_reply_id
	comment.is_replied = True
	comment.reply_status = "posted"
	comment.reply_posting_started_at = None
	db.flush()
