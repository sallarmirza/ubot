from hashlib import sha256

from sqlalchemy import and_, func, or_, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from db_model import (
	BusinessSetup,
	Comments,
	TargetChannel,
	TargetVideo,
	UserOAuth,
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


def get_comments(db: Session, selected_video_id: int) -> list[Comments]:
	"""Return top-level comments and all fetched replies in stable order."""
	return (
		db.query(Comments)
		.filter_by(selected_video_id=selected_video_id)
		.order_by(Comments.comment_id)
		.all()
	)


def get_selected_videos_for_monitoring(db: Session) -> list[tuple[int, str, str]]:
	"""List selected videos with the owner and YouTube channel needed to poll."""
	rows = (
		db.query(
			YoutubeChannel.user_id,
			YoutubeChannel.youtube_channel_id,
			Videos.youtube_video_id,
		)
		.join(TargetChannel, TargetChannel.channel_id == YoutubeChannel.channel_id)
		.join(Videos, Videos.target_channel_id == TargetChannel.target_channel_id)
		.join(TargetVideo, TargetVideo.video_id == Videos.video_id)
		.join(UserOAuth, UserOAuth.user_id == YoutubeChannel.user_id)
		.filter(
			TargetChannel.user_id == YoutubeChannel.user_id,
			TargetVideo.user_id == YoutubeChannel.user_id,
			UserOAuth.comment_monitoring_enabled.is_(True),
		)
		.order_by(YoutubeChannel.user_id, Videos.video_id)
		.all()
	)
	return [(row[0], row[1], row[2]) for row in rows]


def get_video_comments(db: Session, selected_video_id: int) -> list[Comments]:
	return (
		db.query(Comments)
		.filter_by(selected_video_id=selected_video_id)
		.order_by(Comments.comment_id)
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


def get_comment(
	db: Session, selected_video_id: int, youtube_comment_id: str
) -> Comments | None:
	"""Find either a top-level comment or a reply in this selected video."""
	return (
		db.query(Comments)
		.filter_by(
			selected_video_id=selected_video_id,
			youtube_comment_id=youtube_comment_id,
		)
		.first()
	)


def has_replies(db: Session, comment_id: int) -> bool:
	"""Return whether the comment has children and therefore is not a leaf."""
	return (
		db.query(Comments.comment_id)
		.filter(Comments.parent_comment_id == comment_id)
		.first()
		is not None
	)



def save_reply_draft(db: Session, comment: Comments, ai_reply: str) -> None:
	# Treat explicit SKIP replies from the AI as a decision not to reply.
	if isinstance(ai_reply, str) and ai_reply.strip().upper() == "SKIP":
		# Atomically mark the comment as skipped so it won't be retried.
		result = db.execute(
			update(Comments)
			.where(
				Comments.comment_id == comment.comment_id,
				Comments.is_replied.is_(False),
				Comments.reply_status.in_(("draft", "processing")),
			)
			.values(ai_reply=None, is_replied=False, reply_status="skipped")
			.execution_options(synchronize_session=False)
		)
		if result.rowcount != 1:
			raise ValueError("Reply posting is in progress or has an uncertain outcome")
		set_committed_value(comment, "ai_reply", None)
		set_committed_value(comment, "is_replied", False)
		set_committed_value(comment, "reply_status", "skipped")
		return

	if not ai_reply or len(ai_reply) > 800:
		raise ValueError("AI reply must contain between 1 and 800 characters")
	if comment.is_replied:
		raise ValueError("A reply has already been posted for this comment")
	result = db.execute(
		update(Comments)
		.where(
			Comments.comment_id == comment.comment_id,
			Comments.is_replied.is_(False),
			Comments.reply_status == "processing",
		)
		.values(ai_reply=ai_reply)
		.execution_options(synchronize_session=False)
	)
	if result.rowcount != 1:
		raise ValueError("Reply posting is in progress or has an uncertain outcome")
	set_committed_value(comment, "ai_reply", ai_reply)


def claim_reply_processing(
	db: Session,
	comment: Comments,
	author_channel_id: str,
	max_replies_per_thread: int,
	stale_before,
) -> str:
	"""Claim a viewer comment before LLM work and enforce the thread limit atomically."""
	thread_id = comment.thread_youtube_comment_id or comment.youtube_comment_id
	root = (
		db.query(Comments)
		.filter(
			Comments.selected_video_id == comment.selected_video_id,
			Comments.youtube_comment_id == thread_id,
		)
		.with_for_update()
		.first()
	)
	if root is None:
		raise ValueError("Comment thread root is missing")

	if comment.parent_youtube_comment_id and comment.published_at:
		older_unanswered = (
			db.query(Comments.comment_id)
			.filter(
				Comments.selected_video_id == comment.selected_video_id,
				Comments.thread_youtube_comment_id == thread_id,
				Comments.parent_youtube_comment_id
				== comment.parent_youtube_comment_id,
				or_(
					Comments.published_at < comment.published_at,
					and_(
						Comments.published_at == comment.published_at,
						Comments.comment_id < comment.comment_id,
					),
					and_(
						Comments.published_at.is_(None),
						Comments.comment_id < comment.comment_id,
					),
				),
				or_(
					Comments.author_channel_id.is_(None),
					Comments.author_channel_id != author_channel_id,
				),
				Comments.is_replied.is_(False),
				~Comments.reply_status.in_(("posted", "skipped", "retained")),
			)
			.first()
		)
		if older_unanswered is not None:
			db.rollback()
			return "older_pending"

	active_sources = db.query(
		Comments.comment_id, Comments.youtube_reply_id
	).filter(
		Comments.selected_video_id == comment.selected_video_id,
		Comments.thread_youtube_comment_id == thread_id,
		Comments.reply_status.in_(("processing", "posting", "unknown", "posted")),
	).all()
	active_source_ids = {
		row.comment_id
		for row in active_sources
		if row.comment_id != comment.comment_id
	}
	linked_reply_ids = {
		row.youtube_reply_id for row in active_sources if row.youtube_reply_id
	}
	existing_bot_reply_ids = {
		row.youtube_comment_id
		for row in db.query(Comments.youtube_comment_id)
		.filter(
			Comments.selected_video_id == comment.selected_video_id,
			Comments.thread_youtube_comment_id == thread_id,
			Comments.author_channel_id == author_channel_id,
			Comments.parent_youtube_comment_id.is_not(None),
		)
		.all()
		if row.youtube_comment_id not in linked_reply_ids
	}
	active_count = len(active_source_ids) + len(existing_bot_reply_ids)
	if active_count >= max_replies_per_thread:
		db.rollback()
		return "limit"

	retryable = or_(
		Comments.reply_status.in_(("draft", "failed")),
		(
			Comments.reply_status.in_(("processing", "posting", "unknown"))
			& (Comments.reply_posting_started_at < stale_before)
		),
	)
	result = db.execute(
		update(Comments)
		.where(
			Comments.comment_id == comment.comment_id,
			Comments.is_replied.is_(False),
			or_(
				Comments.author_channel_id.is_(None),
				Comments.author_channel_id != author_channel_id,
			),
			retryable,
		)
		.values(reply_status="processing", reply_posting_started_at=func.now())
		.execution_options(synchronize_session=False)
	)
	if result.rowcount != 1:
		db.rollback()
		return "already_claimed"
	db.commit()
	return "claimed"


def acquire_comment_branch_lock(
	db: Session, comment: Comments
) -> tuple[Connection, int]:
	"""Serialize work on one reply branch while allowing other branches to run."""
	branch_id = (
		getattr(comment, "parent_youtube_comment_id", None)
		or getattr(comment, "thread_youtube_comment_id", None)
		or comment.youtube_comment_id
	)
	lock_id = int.from_bytes(
		sha256(
			f"{getattr(comment, 'selected_video_id', 0)}:{branch_id}".encode("utf-8")
		).digest()[:8],
		byteorder="big",
		signed=True,
	)
	connection = db.get_bind().connect()
	connection.execute(
		text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id}
	)
	return connection, lock_id


def release_comment_branch_lock(lock: tuple[Connection, int]) -> None:
	connection, _ = lock
	connection.rollback()
	connection.close()


def mark_reply_failed(db: Session, comment_id: int) -> None:
	"""Make a definitively unsuccessful generation or post retryable."""
	db.execute(
		update(Comments)
		.where(
			Comments.comment_id == comment_id,
			Comments.reply_status.in_(("processing", "posting")),
		)
		.values(reply_status="failed", reply_posting_started_at=None)
		.execution_options(synchronize_session=False)
	)
	db.commit()


def mark_reply_skipped(db: Session, comment_id: int) -> None:
	db.execute(
		update(Comments)
		.where(
			Comments.comment_id == comment_id,
			Comments.reply_status.in_(("draft", "failed", "processing")),
		)
		.values(reply_status="skipped", reply_posting_started_at=None)
		.execution_options(synchronize_session=False)
	)
	db.commit()


def mark_reply_found(
	db: Session, comment_id: int, youtube_reply_id: str
) -> None:
	db.execute(
		update(Comments)
		.where(Comments.comment_id == comment_id, Comments.is_replied.is_(False))
		.values(
			youtube_reply_id=youtube_reply_id,
			is_replied=True,
			reply_status="posted",
			reply_posting_started_at=None,
		)
		.execution_options(synchronize_session=False)
	)
	db.commit()


def retry_skipped_reply(db: Session, comment: Comments) -> bool:
	"""Reopen a skipped comment for a new explicit reply attempt."""
	result = db.execute(
		update(Comments)
		.where(
			Comments.comment_id == comment.comment_id,
			Comments.reply_status == "skipped",
			Comments.youtube_reply_id.is_(None),
		)
		.values(
			ai_reply=None,
			is_replied=False,
			can_reply=True,
			reply_status="draft",
			reply_posting_started_at=None,
		)
		.execution_options(synchronize_session=False)
	)
	if result.rowcount != 1:
		db.rollback()
		return False
	set_committed_value(comment, "ai_reply", None)
	set_committed_value(comment, "is_replied", False)
	set_committed_value(comment, "can_reply", True)
	set_committed_value(comment, "reply_status", "draft")
	set_committed_value(comment, "reply_posting_started_at", None)
	db.commit()
	return True


def claim_reply_posting(db: Session, comment_id: int) -> bool:
	"""Atomically claim a draft so only one server process can post it."""
	result = db.execute(
		update(Comments)
		.where(
			Comments.comment_id == comment_id,
			Comments.is_replied.is_(False),
			Comments.ai_reply.is_not(None),
			Comments.reply_status.in_(("draft", "processing")),
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
	"""Mark a definitively unsuccessful YouTube post as retryable."""
	db.execute(
		update(Comments)
		.where(Comments.comment_id == comment_id, Comments.reply_status == "posting")
		.values(reply_status="failed", reply_posting_started_at=None)
		.execution_options(synchronize_session=False)
	)
	db.commit()


def mark_reply_posting_unknown(db: Session, comment_id: int) -> None:
	"""Prevent unsafe retries when YouTube may have accepted an uncertain request."""
	db.execute(
		update(Comments)
		.where(
			Comments.comment_id == comment_id,
			Comments.reply_status.in_(("processing", "posting", "unknown")),
		)
		.values(reply_status="unknown", reply_posting_started_at=func.now())
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
