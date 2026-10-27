"""Scheduled cleanup of expired comment content and analytics snapshots."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from db_manager import db_manager
from repositories import retention_repository


RETENTION_DAYS = 30
RETENTION_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60
logger = logging.getLogger(__name__)


def run_data_retention_cleanup() -> dict[str, int]:
	"""Redact 30-day-old comment content and prune expired analytics."""
	cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
		days=RETENTION_DAYS
	)
	with db_manager.SessionLocal() as db:
		try:
			result = retention_repository.prune_expired_data(db, cutoff)
			db.commit()
		except Exception:
			db.rollback()
			raise
	logger.info(
		"Data-retention cleanup complete: comments_redacted=%s analytics_deleted=%s",
		result["comments_redacted"],
		result["analytics_deleted"],
	)
	return result


async def run_data_retention_cleanup_loop() -> None:
	"""Run cleanup at startup and then once every 24 hours."""
	while True:
		try:
			await asyncio.to_thread(run_data_retention_cleanup)
		except Exception:
			logger.exception("Data-retention cleanup failed")
		await asyncio.sleep(RETENTION_CLEANUP_INTERVAL_SECONDS)
