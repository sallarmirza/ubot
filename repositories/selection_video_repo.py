from sqlalchemy.orm import Session

from db_model import TargetChannel, TargetVideo, Videos, YoutubeChannel


def get_user_channel(db: Session, user_id: int, youtube_channel_id: str) -> YoutubeChannel | None:
	"""Return this user's channel, or None when it does not belong to them."""
	return (
		db.query(YoutubeChannel)
		.filter_by(user_id=user_id, youtube_channel_id=youtube_channel_id)
		.first()
	)


def get_target_channel(
	db: Session, user_id: int, channel: YoutubeChannel
) -> TargetChannel | None:
	"""Find the selected-channel row for an owned YouTube channel."""
	return (
		db.query(TargetChannel)
		.filter_by(user_id=user_id, channel_id=channel.channel_id)
		.first()
	)


def get_or_create_target_channel(
	db: Session, user_id: int, channel: YoutubeChannel
) -> TargetChannel:
	"""Create the selected-channel row when it does not exist yet."""
	target = get_target_channel(db, user_id, channel)
	if target is None:
		target = TargetChannel(user_id=user_id, channel_id=channel.channel_id)
		db.add(target)
		db.flush()
	return target


def save_video_catalog(
	db: Session, user_id: int, target: TargetChannel, video_data: list[dict]
) -> None:
	"""Insert fetched videos or update their titles in the channel catalog."""
	for item in video_data:
		video = (
			db.query(Videos)
			.filter_by(
				user_id=user_id,
				target_channel_id=target.target_channel_id,
				youtube_video_id=item["youtube_video_id"],
			)
			.first()
		)
		if video is None:
			video = Videos(
				user_id=user_id,
				target_channel_id=target.target_channel_id,
				youtube_video_id=item["youtube_video_id"],
			)
			db.add(video)
		video.title = item["title"]


def get_video_catalog(
	db: Session, user_id: int, target: TargetChannel, youtube_video_ids: list[str]
) -> list[Videos]:
	"""Return only requested videos from this user's channel catalog."""
	return (
		db.query(Videos)
		.filter(
			Videos.user_id == user_id,
			Videos.target_channel_id == target.target_channel_id,
			Videos.youtube_video_id.in_(youtube_video_ids),
		)
		.all()
	)


def get_selected_video_descriptions(
	db: Session, user_id: int, target: TargetChannel
) -> dict[str, str | None]:
	"""Return saved descriptions keyed by YouTube video ID."""
	rows = (
		db.query(Videos.youtube_video_id, TargetVideo.description)
		.join(TargetVideo, TargetVideo.video_id == Videos.video_id)
		.filter(
			Videos.target_channel_id == target.target_channel_id,
			TargetVideo.user_id == user_id,
		)
		.all()
	)
	return {row.youtube_video_id: row.description for row in rows}


def save_selected_video(
	db: Session, user_id: int, video: Videos, video_data: dict
) -> None:
	"""Insert or update a selected video and its latest stats and description."""
	video.title = video_data["title"]
	selected = (
		db.query(TargetVideo)
		.filter_by(user_id=user_id, video_id=video.video_id)
		.first()
	)
	if selected is None:
		selected = TargetVideo(user_id=user_id, video_id=video.video_id)
		db.add(selected)
	selected.views = video_data["views"]
	selected.likes = video_data["likes"]
	selected.comments = video_data["comments"]
	selected.description = video_data["description"]
