import logging

from fastapi import HTTPException

from db_manager import db_manager
from repositories import ai_repo
from services import coments_fetching_service


COMMENT_FETCH_INTERVAL_SECONDS = 10
logger = logging.getLogger(__name__)


def run_comment_monitoring_cycle() -> None:
	"""Fetch comments for selected videos without generating or posting replies."""
	# Read the work list in a short session; don't hold a database connection
	# while waiting on YouTube or the AI provider.
	with db_manager.SessionLocal() as db:
		selected_videos = ai_repo.get_selected_videos_for_monitoring(db)

	for user_id, channel_id, video_id in selected_videos:
		try:
			# Isolate each video so one user's auth/quota problem doesn't block
			# fetching comments for other selected videos.
			with db_manager.SessionLocal() as db:
				coments_fetching_service.fetch_video_comments(
					db,
					user_id,
					channel_id,
					video_id,
				)
				logger.info(
					"Comment refresh complete: user_id=%s channel_id=%s video_id=%s",
					user_id,
					channel_id,
					video_id,
				)
		except HTTPException as error:
			logger.warning(
				"Comment monitor failed: user_id=%s channel_id=%s video_id=%s "
				"status=%s detail=%s",
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
