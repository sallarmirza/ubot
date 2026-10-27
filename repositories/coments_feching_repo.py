from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from db_model import Comments, TargetVideo


def _get_video_name(db: Session, selected_video_id: int) -> str | None:
	selected_video = (
		db.query(TargetVideo)
		.filter_by(selected_video_id=selected_video_id)
		.first()
	)
	return selected_video.video.title if selected_video is not None else None


def get_comments(db: Session, selected_video_id: int) -> list[Comments]:
	"""Return all comments saved for one selected video."""
	return (
		db.query(Comments)
		.filter_by(selected_video_id=selected_video_id)
		.order_by(Comments.comment_id)
		.all()
	)


def get_comment(
	db: Session, selected_video_id: int, youtube_comment_id: str
) -> Comments | None:
	"""Return one comment belonging to the selected video."""
	return (
		db.query(Comments)
		.filter_by(
			selected_video_id=selected_video_id,
			youtube_comment_id=youtube_comment_id,
		)
		.first()
	)


def create_comment(
	db: Session,
	selected_video_id: int,
	youtube_comment_id: str,
	comment_text: str,
	parent_comment_id: int | None = None,
) -> Comments:
	"""Add a comment to a selected video without committing the transaction."""
	_validate_youtube_comment_id(youtube_comment_id)
	_validate_comment_text(comment_text)
	if parent_comment_id is not None:
		parent = (
			db.query(Comments)
			.filter_by(
				comment_id=parent_comment_id,
				selected_video_id=selected_video_id,
			)
			.first()
		)
		if parent is None:
			raise ValueError("Parent comment does not belong to the selected video")
	comment = Comments(
		selected_video_id=selected_video_id,
		youtube_comment_id=youtube_comment_id,
		comment_text=comment_text,
		video_name=_get_video_name(db, selected_video_id),
		parent_comment_id=parent_comment_id,
	)
	db.add(comment)
	db.flush()
	return comment


def save_fetched_comments(
	db: Session,
	selected_video_id: int,
	comments: Sequence[Mapping[str, object]],
) -> list[Comments]:
	"""Insert or refresh fetched comments and replies, preserving saved replies."""
	comment_data = _flatten_fetched_comments(comments)
	if not comment_data:
		return []

	comment_ids = [item[0] for item in comment_data]
	if len(comment_ids) != len(set(comment_ids)):
		raise ValueError("Fetched comments contain duplicate YouTube comment IDs")

	reply_sources = (
		db.query(Comments)
		.filter(
			Comments.selected_video_id == selected_video_id,
			Comments.youtube_reply_id.in_(comment_ids),
		)
		.all()
	)
	source_by_reply_id = {
		comment.youtube_reply_id: comment
		for comment in reply_sources
		if comment.youtube_reply_id
	}
	existing_comments = (
		db.query(Comments)
		.filter(
			Comments.selected_video_id == selected_video_id,
			Comments.youtube_comment_id.in_(
				set(comment_ids)
				| {item[2] for item in comment_data if item[2] is not None}
				| {
					comment.youtube_comment_id
					for comment in reply_sources
				}
			),
		)
		.all()
	)
	by_youtube_id = {comment.youtube_comment_id: comment for comment in existing_comments}
	video_name = _get_video_name(db, selected_video_id)

	saved_comments = []
	for (
		youtube_comment_id,
		comment_text,
		parent_youtube_comment_id,
		thread_youtube_comment_id,
		author_name,
		author_channel_id,
		published_at,
		can_reply,
	) in comment_data:
		comment = by_youtube_id.get(youtube_comment_id)
		answered_comment = source_by_reply_id.get(youtube_comment_id)
		if answered_comment is not None:
			parent_youtube_comment_id = answered_comment.youtube_comment_id
			thread_youtube_comment_id = (
				answered_comment.thread_youtube_comment_id
				or answered_comment.youtube_comment_id.split(".")[0]
			)
		parent_comment = (
			answered_comment
			if answered_comment is not None
			else by_youtube_id[parent_youtube_comment_id]
			if parent_youtube_comment_id in by_youtube_id
			else None
		)
		if comment is None:
			comment = Comments(
				selected_video_id=selected_video_id,
				youtube_comment_id=youtube_comment_id,
				comment_text=comment_text,
				parent_youtube_comment_id=parent_youtube_comment_id,
				thread_youtube_comment_id=thread_youtube_comment_id,
				author_name=author_name,
				published_at=published_at,
				author_channel_id=author_channel_id,
				can_reply=can_reply,
				video_name=video_name,
				parent_comment=parent_comment,
			)
			db.add(comment)
			by_youtube_id[youtube_comment_id] = comment
		elif comment.reply_status == "retained":
			# Keep the minimal ID/status tombstone so old comments cannot be
			# reprocessed after a YouTube refresh restores their text.
			saved_comments.append(comment)
			continue
		else:
			comment.comment_text = comment_text
			comment.parent_youtube_comment_id = parent_youtube_comment_id
			comment.thread_youtube_comment_id = thread_youtube_comment_id
			comment.author_name = author_name
			comment.published_at = published_at
			comment.author_channel_id = author_channel_id
			comment.can_reply = can_reply
			comment.video_name = video_name
			comment.parent_comment = parent_comment
		saved_comments.append(comment)

	db.flush()
	return saved_comments


def delete_comment(
	db: Session, selected_video_id: int, youtube_comment_id: str
) -> bool:
	"""Delete a comment belonging to the selected video."""
	comment = get_comment(db, selected_video_id, youtube_comment_id)
	if comment is None:
		return False

	db.delete(comment)
	db.flush()
	return True


def _flatten_fetched_comments(
	comments: Sequence[Mapping[str, object]],
) -> list[tuple[str, str, str | None, str | None, str | None, str | None, datetime | None, bool | None]]:
	flattened = []

	def visit(
		items: Sequence[Mapping[str, object]],
		parent_youtube_comment_id: str | None,
		thread_youtube_comment_id: str | None,
	) -> None:
		for item in items:
			if not isinstance(item, Mapping):
				raise ValueError("Fetched comment must be a mapping")
			youtube_comment_id, comment_text, author_channel_id = _comment_fields(item)
			explicit_parent_id = item.get("parent_youtube_comment_id")
			parent_id = (
				explicit_parent_id
				if isinstance(explicit_parent_id, str) and explicit_parent_id
				else parent_youtube_comment_id
			)
			thread_id = thread_youtube_comment_id or youtube_comment_id
			author_name = item.get("author_name")
			if author_name is not None and not isinstance(author_name, str):
				raise ValueError("Fetched comment author name must be a string")
			published_at = _parse_published_at(item.get("published_at"))
			can_reply = item.get("can_reply")
			if can_reply is not None and not isinstance(can_reply, bool):
				raise ValueError("Fetched comment replyability must be a boolean")
			flattened.append(
				(
					youtube_comment_id,
					comment_text,
					parent_id,
					thread_id,
					author_name,
					author_channel_id,
					published_at,
					can_reply,
				)
			)
			replies = item.get("replies", [])
			if not isinstance(replies, Sequence) or isinstance(replies, (str, bytes)):
				raise ValueError("Fetched comment replies must be a sequence")
			visit(replies, youtube_comment_id, thread_id)

	visit(comments, None, None)
	return flattened


def _parse_published_at(value: object) -> datetime | None:
	if not isinstance(value, str) or not value:
		return None
	try:
		return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
			tzinfo=None
		)
	except ValueError:
		return None


def _comment_fields(
	comment: Mapping[str, object],
) -> tuple[str, str, str | None]:
	youtube_comment_id = comment.get("youtube_comment_id")
	comment_text = comment.get("text")
	author_channel_id = comment.get("author_channel_id")
	if not isinstance(youtube_comment_id, str) or not youtube_comment_id:
		raise ValueError("Fetched comment is missing a YouTube comment ID")
	if not isinstance(comment_text, str):
		raise ValueError("Fetched comment text must be a string")
	if author_channel_id is not None and not isinstance(author_channel_id, str):
		raise ValueError("Fetched comment author channel ID must be a string")
	_validate_youtube_comment_id(youtube_comment_id)
	_validate_comment_text(comment_text)
	return youtube_comment_id, comment_text, author_channel_id


def _validate_youtube_comment_id(youtube_comment_id: str) -> None:
	if not youtube_comment_id:
		raise ValueError("YouTube comment ID cannot be empty")
	if len(youtube_comment_id) > 100:
		raise ValueError("YouTube comment ID exceeds the database column limit")


def _validate_comment_text(comment_text: str) -> None:
	if len(comment_text) > 800:
		raise ValueError("Comment text exceeds the database column limit")