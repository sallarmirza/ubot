import logging

from fastapi import HTTPException

from db_manager import db_manager
from repositories import ai_repo
from services import ai_service, coments_fetching_service


COMMENT_FETCH_INTERVAL_SECONDS = 10
logger = logging.getLogger(__name__)


def run_comment_monitoring_cycle() -> None:
	"""Fetch all selected-video threads and auto-reply to eligible comments."""
	# Read the work list in a short session; don't hold a database connection
	# while waiting on YouTube or the AI provider.
	with db_manager.SessionLocal() as db:
		selected_videos = ai_repo.get_selected_videos_for_monitoring(db)

	for user_id, channel_id, video_id in selected_videos:
		try:
			# Isolate each video so one user's auth/quota problem doesn't block
			# monitoring of the other selected videos.
			with db_manager.SessionLocal() as db:
				# Unlimited here means page through every top-level comment and
				# every reply; the interactive UI endpoint remains bounded.
				coments_fetching_service.fetch_video_comments(
					db,
					user_id,
					channel_id,
					video_id,
					max_comments=None,
					max_replies=None,
				)
				result = ai_service.generate_and_post_video_replies(
					db, user_id, channel_id, video_id
				)
				logger.info(
					"Comment monitor cycle complete: user_id=%s channel_id=%s "
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
