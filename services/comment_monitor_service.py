import asyncio
import logging

from fastapi import HTTPException

from db_manager import db_manager
from repositories import ai_repo, auth_repository
from services import ai_service, coments_fetching_service


COMMENT_SCHEDULER_POLL_SECONDS = 60
logger = logging.getLogger(__name__)


def _get_due_user_ids(
	intervals_seconds: dict[int, int],
	last_fetch_at: dict[int, float],
	now: float,
) -> set[int]:
	return {
		user_id
		for user_id, interval_seconds in intervals_seconds.items()
		if user_id not in last_fetch_at
		or now - last_fetch_at[user_id] >= interval_seconds
	}


def _seconds_until_next_fetch(
	intervals_seconds: dict[int, int],
	last_fetch_at: dict[int, float],
	now: float,
) -> float:
	return min(
		(
			max(0, interval_seconds - (now - last_fetch_at[user_id]))
			for user_id, interval_seconds in intervals_seconds.items()
			if user_id in last_fetch_at
		),
		default=COMMENT_SCHEDULER_POLL_SECONDS,
	)


def run_comment_monitoring_cycle(
	due_user_ids: set[int] | None = None,
	selected_videos: list[tuple[int, str, str, int]] | None = None,
) -> None:
	"""Fetch selected videos and automatically reply to eligible viewer comments."""
	# Read the work list in a short session; don't hold a database connection
	# while waiting on YouTube or the AI provider.
	if selected_videos is None:
		with db_manager.SessionLocal() as db:
			selected_videos = ai_repo.get_selected_videos_for_monitoring(db)

	paused_user_ids = set()
	for user_id, channel_id, video_id, _interval_minutes in selected_videos:
		if due_user_ids is not None and user_id not in due_user_ids:
			continue
		if user_id in paused_user_ids:
			continue
		try:
			# Isolate each video so one user's auth/quota problem doesn't block
			# fetching comments for other selected videos.
			with db_manager.SessionLocal() as db:
				if not auth_repository.is_comment_monitoring_enabled(db, user_id):
					continue
				fetched_comments = coments_fetching_service.fetch_video_comments(
					db,
					user_id,
					channel_id,
					video_id,
					max_comments=None,
					max_replies=None,
				)
				if not auth_repository.is_comment_monitoring_enabled(db, user_id):
					continue
				result = ai_service.generate_and_post_new_video_replies(
					db,
					user_id,
					channel_id,
					video_id,
					coments_fetching_service.collect_youtube_comment_ids(
						fetched_comments
					),
					already_replied_comment_ids=(
						coments_fetching_service.collect_replied_youtube_comment_ids(
							fetched_comments, channel_id
						)
					),
				)
				logger.info(
					"Automatic comment replies complete: user_id=%s channel_id=%s "
					"video_id=%s attempted=%s posted=%s skipped=%s failed=%s",
					user_id,
					channel_id,
					video_id,
					result["attempted"],
					result["posted"],
					result["skipped"],
					result["failed"],
				)
		except HTTPException as error:
			if error.status_code == 401:
				with db_manager.SessionLocal() as db:
					auth_repository.set_comment_monitoring_enabled(
						db, user_id, False
					)
					db.commit()
				paused_user_ids.add(user_id)
			logger.warning(
				"Comment monitor paused: user_id=%s channel_id=%s video_id=%s "
				"status=%s detail=%s; sign in again to resume",
				user_id,
				channel_id,
				video_id,
				error.status_code,
				error.detail,
			)
		except Exception:
			logger.exception(
				"Unexpected comment monitor failure: user_id=%s "
				"channel_id=%s video_id=%s",
				user_id,
				channel_id,
				video_id,
			)


async def run_comment_monitoring_loop() -> None:
	"""Continuously scan all selected-video comments and reply to eligible ones."""
	last_fetch_at: dict[int, float] = {}
	loop = asyncio.get_running_loop()
	while True:
		try:
			with db_manager.SessionLocal() as db:
				selected_videos = ai_repo.get_selected_videos_for_monitoring(db)
		except Exception:
			logger.exception("Could not load comment-monitoring schedule")
			await asyncio.sleep(COMMENT_SCHEDULER_POLL_SECONDS)
			continue

		now = loop.time()
		intervals_seconds = {
			user_id: interval_minutes * 60
			for user_id, _channel_id, _video_id, interval_minutes in selected_videos
		}
		active_user_ids = set(intervals_seconds)
		last_fetch_at = {
			user_id: last_fetch_at[user_id]
			for user_id in active_user_ids
			if user_id in last_fetch_at
		}
		due_user_ids = _get_due_user_ids(
			intervals_seconds, last_fetch_at, now
		)

		if due_user_ids:
			cycle = asyncio.create_task(
				asyncio.to_thread(
					run_comment_monitoring_cycle,
					due_user_ids,
					selected_videos,
				)
			)
			try:
				await asyncio.shield(cycle)
			except asyncio.CancelledError:
				try:
					await cycle
				except Exception:
					logger.exception("Comment monitor cycle failed during shutdown")
				raise
			except Exception:
				logger.exception("Unexpected comment monitor cycle failure")
			finally:
				completed_at = loop.time()
				for user_id in due_user_ids:
					last_fetch_at[user_id] = completed_at

		next_due_seconds = _seconds_until_next_fetch(
			intervals_seconds, last_fetch_at, loop.time()
		)
		await asyncio.sleep(
			min(COMMENT_SCHEDULER_POLL_SECONDS, max(1, next_due_seconds))
		)
