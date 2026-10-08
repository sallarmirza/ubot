from sqlalchemy.orm import Session

from db_model import (
	Analytics,
	Comments,
	TargetChannel,
	TargetVideo,
	Videos,
	YoutubeChannel,
)


def get_selected_videos(db: Session, user_id: int) -> list[TargetVideo]:
	"""Return all selected videos owned by this user, ordered by channel and title."""
	return (
		db.query(TargetVideo)
		.join(Videos, TargetVideo.video_id == Videos.video_id)
		.join(TargetChannel, Videos.target_channel_id == TargetChannel.target_channel_id)
		.join(YoutubeChannel, TargetChannel.channel_id == YoutubeChannel.channel_id)
		.filter(
			TargetVideo.user_id == user_id,
			TargetChannel.user_id == user_id,
			YoutubeChannel.user_id == user_id,
		)
		.order_by(YoutubeChannel.channel_name, Videos.title, Videos.video_id)
		.all()
	)


def get_selected_video(
	db: Session, user_id: int, channel_id: str, video_id: str
) -> TargetVideo | None:
	"""Return an owned selected video matching its YouTube channel and video IDs."""
	return (
		db.query(TargetVideo)
		.join(Videos, TargetVideo.video_id == Videos.video_id)
		.join(TargetChannel, Videos.target_channel_id == TargetChannel.target_channel_id)
		.join(YoutubeChannel, TargetChannel.channel_id == YoutubeChannel.channel_id)
		.filter(
			TargetVideo.user_id == user_id,
			TargetChannel.user_id == user_id,
			YoutubeChannel.user_id == user_id,
			YoutubeChannel.youtube_channel_id == channel_id,
			Videos.youtube_video_id == video_id,
		)
		.first()
	)


def get_video_comments(db: Session, selected_video_id: int) -> list[Comments]:
	"""Return saved comments and replies for a selected video."""
	return (
		db.query(Comments)
		.filter_by(selected_video_id=selected_video_id)
		.order_by(Comments.comment_id)
		.all()
	)


def get_video_analytics(db: Session, selected_video_id: int) -> list[Analytics]:
	"""Return saved analytics snapshots for a selected video."""
	return (
		db.query(Analytics)
		.filter_by(selected_video_id=selected_video_id)
		.order_by(Analytics.created_at.desc(), Analytics.analytics_id.desc())
		.all()
	)
