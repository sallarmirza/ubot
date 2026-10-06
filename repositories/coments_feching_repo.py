from collections.abc import Mapping, Sequence

from sqlalchemy.orm import Session

from db_model import Comments


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

	comment_ids = [youtube_comment_id for youtube_comment_id, _, _ in comment_data]
	if len(comment_ids) != len(set(comment_ids)):
		raise ValueError("Fetched comments contain duplicate YouTube comment IDs")

	existing_comments = (
		db.query(Comments)
		.filter(
			Comments.selected_video_id == selected_video_id,
			Comments.youtube_comment_id.in_(comment_ids),
		)
		.all()
	)
	by_youtube_id = {comment.youtube_comment_id: comment for comment in existing_comments}

	saved_comments = []
	for youtube_comment_id, comment_text, parent_youtube_comment_id in comment_data:
		comment = by_youtube_id.get(youtube_comment_id)
		parent_comment = (
			by_youtube_id[parent_youtube_comment_id]
			if parent_youtube_comment_id is not None
			else None
		)
		if comment is None:
			comment = Comments(
				selected_video_id=selected_video_id,
				youtube_comment_id=youtube_comment_id,
				comment_text=comment_text,
				parent_comment=parent_comment,
			)
			db.add(comment)
			by_youtube_id[youtube_comment_id] = comment
		else:
			comment.comment_text = comment_text
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
) -> list[tuple[str, str, str | None]]:
	flattened = []

	def visit(
		items: Sequence[Mapping[str, object]],
		parent_youtube_comment_id: str | None,
	) -> None:
		for item in items:
			if not isinstance(item, Mapping):
				raise ValueError("Fetched comment must be a mapping")
			youtube_comment_id, comment_text = _comment_fields(item)
			flattened.append(
				(youtube_comment_id, comment_text, parent_youtube_comment_id)
			)
			replies = item.get("replies", [])
			if not isinstance(replies, Sequence) or isinstance(replies, (str, bytes)):
				raise ValueError("Fetched comment replies must be a sequence")
			visit(replies, youtube_comment_id)

	visit(comments, None)
	return flattened


def _comment_fields(comment: Mapping[str, object]) -> tuple[str, str]:
	youtube_comment_id = comment.get("youtube_comment_id")
	comment_text = comment.get("text")
	if not isinstance(youtube_comment_id, str) or not youtube_comment_id:
		raise ValueError("Fetched comment is missing a YouTube comment ID")
	if not isinstance(comment_text, str):
		raise ValueError("Fetched comment text must be a string")
	_validate_youtube_comment_id(youtube_comment_id)
	_validate_comment_text(comment_text)
	return youtube_comment_id, comment_text


def _validate_youtube_comment_id(youtube_comment_id: str) -> None:
	if not youtube_comment_id:
		raise ValueError("YouTube comment ID cannot be empty")
	if len(youtube_comment_id) > 100:
		raise ValueError("YouTube comment ID exceeds the database column limit")


def _validate_comment_text(comment_text: str) -> None:
	if len(comment_text) > 800:
		raise ValueError("Comment text exceeds the database column limit")