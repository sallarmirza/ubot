"""Public HTTP endpoints for the isolated interactive demo."""

import ipaddress
import threading
from collections import deque
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from repositories import demo_repo
from services import demo_service
from services.demo_service import DemoUnavailableError


DEMO_REQUESTS_PER_IP_PER_MINUTE = 5
DEMO_REPLIES_PER_DAY = 200
RATE_LIMIT_WINDOW = timedelta(minutes=1)
GENERIC_UNAVAILABLE_MESSAGE = "Demo temporarily unavailable. Please try again later."

router = APIRouter(prefix="/demo", tags=["demo"])
_quota_lock = threading.Lock()
_requests_by_ip: dict[str, deque[datetime]] = {}
_daily_count = 0
_daily_count_date: date | None = None


class DemoComment(BaseModel):
	"""One public comment used in the demo conversation."""

	model_config = ConfigDict(extra="forbid")

	author: str
	text: str


class DemoVideoResponse(BaseModel):
	"""Fixed public video, persona summary, and example comments."""

	model_config = ConfigDict(extra="forbid")

	video: dict[str, str]
	persona: dict[str, str]
	comments: list[DemoComment]


class DemoReplyRequest(BaseModel):
	"""Visitor's comment for the AI demo."""

	model_config = ConfigDict(extra="forbid")

	comment: str = Field(min_length=1, max_length=400)


class DemoReplyResponse(BaseModel):
	"""Visitor comment paired with its generated demo reply."""

	model_config = ConfigDict(extra="forbid")

	comment: str
	reply: str


def _get_client_ip(request: Request) -> str:
	"""Read a valid forwarded client IP, falling back to the direct peer."""
	# Trusted reverse proxies should append the client address or replace this
	# header; prefer the right-most valid address to avoid caller-supplied prefixes.
	for candidate in reversed(request.headers.get("x-forwarded-for", "").split(",")):
		try:
			return str(ipaddress.ip_address(candidate.strip()))
		except ValueError:
			continue
	if request.client is not None:
		try:
			return str(ipaddress.ip_address(request.client.host))
		except ValueError:
			pass
	return "unknown"


def _consume_quota(client_ip: str, now: datetime) -> None:
	"""Enforce per-IP sliding-window and UTC daily demo limits."""
	global _daily_count, _daily_count_date

	today = now.date()
	window_start = now - RATE_LIMIT_WINDOW
	with _quota_lock:
		if _daily_count_date != today:
			_daily_count = 0
			_daily_count_date = today
		if _daily_count >= DEMO_REPLIES_PER_DAY:
			raise HTTPException(status_code=429, detail="Demo daily limit reached.")

		for known_ip, timestamps in list(_requests_by_ip.items()):
			while timestamps and timestamps[0] <= window_start:
				timestamps.popleft()
			if not timestamps:
				del _requests_by_ip[known_ip]

		requests = _requests_by_ip.setdefault(client_ip, deque())
		if len(requests) >= DEMO_REQUESTS_PER_IP_PER_MINUTE:
			raise HTTPException(status_code=429, detail="Demo request limit reached.")

		requests.append(now)
		_daily_count += 1


@router.get("/video", response_model=DemoVideoResponse)
def get_demo_video() -> dict[str, object]:
	"""Return fixed demo content without requiring authentication."""
	return {
		"video": demo_repo.get_demo_video(),
		"persona": demo_repo.get_persona_summary(),
		"comments": demo_repo.get_sample_comments(),
	}


@router.post("/reply", response_model=DemoReplyResponse)
def generate_demo_reply(
	payload: DemoReplyRequest,
	request: Request,
) -> DemoReplyResponse:
	"""Return one bounded AI reply without touching production data."""
	try:
		comment = demo_service.normalize_demo_comment(payload.comment)
	except ValueError as error:
		raise HTTPException(status_code=422, detail=str(error)) from error

	_consume_quota(_get_client_ip(request), datetime.now(timezone.utc))
	try:
		reply = demo_service.generate_demo_reply(comment)
	except DemoUnavailableError as error:
		raise HTTPException(
			status_code=503,
			detail=GENERIC_UNAVAILABLE_MESSAGE,
		) from error
	return DemoReplyResponse(comment=comment, reply=reply)
