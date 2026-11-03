"""Persistent anonymous-session limits for the public interactive demo."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db_model import DemoSession


def consume_demo_comment(
	db: Session,
	session_token_hash: str,
	comment_limit: int,
) -> bool:
	"""Atomically consume one comment allowance for a browser session."""
	demo_session = (
		db.query(DemoSession)
		.filter(DemoSession.session_token_hash == session_token_hash)
		.with_for_update()
		.one_or_none()
	)
	if demo_session is None:
		try:
			with db.begin_nested():
				db.add(DemoSession(session_token_hash=session_token_hash))
				db.flush()
		except IntegrityError:
			demo_session = (
				db.query(DemoSession)
				.filter(DemoSession.session_token_hash == session_token_hash)
				.with_for_update()
				.one_or_none()
			)
			if demo_session is None:
				raise
		else:
			demo_session = (
				db.query(DemoSession)
				.filter(DemoSession.session_token_hash == session_token_hash)
				.with_for_update()
				.one()
			)

	if demo_session.blocked or demo_session.comment_count >= comment_limit:
		demo_session.blocked = True
		db.commit()
		return False

	demo_session.comment_count += 1
	demo_session.blocked = demo_session.comment_count >= comment_limit
	db.commit()
	return True


def ensure_demo_session(db: Session, session_token_hash: str) -> None:
	"""Persist a demo session when the visitor opens the demo video."""
	existing_session = (
		db.query(DemoSession)
		.filter(DemoSession.session_token_hash == session_token_hash)
		.one_or_none()
	)
	if existing_session is not None:
		return

	try:
		with db.begin_nested():
			db.add(DemoSession(session_token_hash=session_token_hash))
			db.flush()
	except IntegrityError:
		existing_session = (
			db.query(DemoSession)
			.filter(DemoSession.session_token_hash == session_token_hash)
			.one_or_none()
		)
		if existing_session is None:
			raise
	else:
		db.commit()
