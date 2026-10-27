"""Database operations for periodic personal-data retention cleanup."""

from datetime import datetime

from sqlalchemy.orm import Session

from db_model import Analytics, Comments


def prune_expired_data(db: Session, cutoff: datetime) -> dict[str, int]:
	"""Redact old comment content and delete old analytics snapshots."""
	redacted_comments = (
		db.query(Comments)
		.filter(
			Comments.created_at < cutoff,
			Comments.reply_status != "retained",
			Comments.reply_status.notin_(("posting", "unknown")),
		)
		.update(
			{
				Comments.comment_text: "",
				Comments.ai_reply: None,
				Comments.author_channel_id: None,
				Comments.can_reply: None,
				Comments.video_name: None,
				Comments.reply_status: "retained",
				Comments.reply_posting_started_at: None,
			},
			synchronize_session=False,
		)
	)
	deleted_analytics = (
		db.query(Analytics)
		.filter(Analytics.created_at < cutoff)
		.delete(synchronize_session=False)
	)
	return {
		"comments_redacted": redacted_comments,
		"analytics_deleted": deleted_analytics,
	}
