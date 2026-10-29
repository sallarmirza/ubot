import asyncio
import logging

from fastapi import HTTPException

from db_manager import db_manager
from repositories import ai_repo, auth_repository
from services import ai_service, coments_fetching_service


COMMENT_FETCH_INTERVAL_SECONDS = 5 * 60
logger = logging.getLogger(__name__)


def run_comment_monitoring_cycle() -> None:
	"""Fetch selected videos and automatically reply to eligible viewer comments."""
	# Read the work list in a short session; don't hold a database connection
	# while waiting on YouTube or the AI provider.
	with db_manager.SessionLocal() as db:
		selected_videos = ai_repo.get_selected_videos_for_monitoring(db)

	paused_user_ids = set()
	for user_id, channel_id, video_id in selected_videos:
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
	while True:
		cycle_started_at = asyncio.get_running_loop().time()
		cycle = asyncio.create_task(
			asyncio.to_thread(run_comment_monitoring_cycle)
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

		cycle_duration = asyncio.get_running_loop().time() - cycle_started_at
		await asyncio.sleep(
			max(0, COMMENT_FETCH_INTERVAL_SECONDS - cycle_duration)
		)
