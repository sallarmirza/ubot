from sqlalchemy import func
from sqlalchemy.orm import Session

from db_model import (
	Analytics,
	Comments,
	PinnedVideo,
	TargetChannel,
	TargetVideo,
	Videos,
	YoutubeChannel,
)


def get_pinned_video(db: Session, user_id: int) -> PinnedVideo | None:
	"""Return this user's saved pinned-video configuration."""
	return db.get(PinnedVideo, user_id)


def get_latest_enabled_pinned_video(db: Session) -> PinnedVideo | None:
	"""Return the most recently configured active pin across all users."""
	return (
		db.query(PinnedVideo)
		.filter(PinnedVideo.enabled.is_(True))
		.order_by(PinnedVideo.updated_at.desc(), PinnedVideo.user_id.desc())
		.first()
	)


def save_pinned_video(
	db: Session, user_id: int, channel_id: str, video_id: str
) -> PinnedVideo:
	"""Save and enable a pin without changing the selected-video records."""
	pinned_video = get_pinned_video(db, user_id)
	if pinned_video is None:
		pinned_video = PinnedVideo(
			user_id=user_id,
			youtube_channel_id=channel_id,
			youtube_video_id=video_id,
			enabled=True,
		)
		db.add(pinned_video)
	else:
		pinned_video.youtube_channel_id = channel_id
		pinned_video.youtube_video_id = video_id
		pinned_video.enabled = True
	db.commit()
	db.refresh(pinned_video)
	return pinned_video


def set_pinned_video_enabled(
	db: Session, pinned_video: PinnedVideo, enabled: bool
) -> PinnedVideo:
	"""Toggle a pin while preserving its channel and video IDs."""
	pinned_video.enabled = enabled
	db.commit()
	db.refresh(pinned_video)
	return pinned_video


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


def get_latest_analytics_snapshots(
	db: Session, selected_video_ids: list[int]
) -> dict[int, Analytics]:
	"""Return only the newest stored snapshot for each selected video."""
	if not selected_video_ids:
		return {}

	latest_ids = (
		db.query(func.max(Analytics.analytics_id).label("analytics_id"))
		.filter(Analytics.selected_video_id.in_(selected_video_ids))
		.group_by(Analytics.selected_video_id)
		.subquery()
	)
	snapshots = (
		db.query(Analytics)
		.join(latest_ids, Analytics.analytics_id == latest_ids.c.analytics_id)
		.all()
	)
	return {snapshot.selected_video_id: snapshot for snapshot in snapshots}


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
