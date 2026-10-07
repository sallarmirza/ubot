from fastapi import HTTPException
from sqlalchemy.orm import Session

from db_model import TargetVideo
from repositories import analytics_repo
from schema.analytics_schema import (
	AnalyticsComment,
	AnalyticsSnapshot,
	SelectedVideoAnalytics,
)


def _build_video_analytics(db: Session, selected_video: TargetVideo) -> SelectedVideoAnalytics:
	video = selected_video.video
	target_channel = video.target_channel
	channel = target_channel.channel
	comments = analytics_repo.get_video_comments(db, selected_video.selected_video_id)
	history = analytics_repo.get_video_analytics(db, selected_video.selected_video_id)
	youtube_comment_ids = {
		comment.comment_id: comment.youtube_comment_id for comment in comments
	}

	comment_rows = [
		AnalyticsComment(
			comment_id=comment.comment_id,
			youtube_comment_id=comment.youtube_comment_id,
			parent_youtube_comment_id=youtube_comment_ids.get(
				comment.parent_comment_id
			),
			comment_text=comment.comment_text,
			ai_reply=comment.ai_reply,
			is_replied=comment.is_replied,
			youtube_reply_id=comment.youtube_reply_id,
			reply_status=comment.reply_status,
			created_at=comment.created_at,
			updated_at=comment.updated_at,
		)
		for comment in comments
	]
	top_level_comments = [
		comment for comment in comments if comment.parent_comment_id is None
	]

	return SelectedVideoAnalytics(
		selected_video_id=selected_video.selected_video_id,
		youtube_channel_id=channel.youtube_channel_id,
		channel_name=channel.channel_name,
		youtube_video_id=video.youtube_video_id,
		title=video.title,
		description=selected_video.description,
		prompt_context=selected_video.prompt_context,
		views=selected_video.views,
		likes=selected_video.likes,
		youtube_comment_count=selected_video.comments,
		saved_top_level_comments=len(top_level_comments),
		saved_replies=len(comments) - len(top_level_comments),
		generated_drafts=sum(bool(comment.ai_reply) for comment in comments),
		posted_replies=sum(comment.is_replied for comment in comments),
		uncertain_replies=sum(comment.reply_status == "unknown" for comment in comments),
		created_at=selected_video.created_at,
		updated_at=selected_video.updated_at,
		comments=comment_rows,
		history=[
			AnalyticsSnapshot(
				analytics_id=snapshot.analytics_id,
				views=snapshot.views,
				likes=snapshot.likes,
				comments=snapshot.comments,
				created_at=snapshot.created_at,
				updated_at=snapshot.updated_at,
			)
			for snapshot in history
		],
	)


def get_selected_video_analytics(
	db: Session, user_id: int
) -> list[SelectedVideoAnalytics]:
	"""Return detailed analytics for every video selected by this user."""
	selected_videos = analytics_repo.get_selected_videos(db, user_id)
	return [_build_video_analytics(db, video) for video in selected_videos]


def get_video_analytics(
	db: Session, user_id: int, channel_id: str, video_id: str
) -> SelectedVideoAnalytics:
	"""Return analytics for one video only when the user selected it."""
	selected_video = analytics_repo.get_selected_video(
		db, user_id, channel_id, video_id
	)
	if selected_video is None:
		raise HTTPException(status_code=404, detail="Selected video not found")
	return _build_video_analytics(db, selected_video)
