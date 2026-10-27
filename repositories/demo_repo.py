"""In-memory content for the public interactive demo."""

import re
from urllib.parse import parse_qs, urlsplit


DEMO_VIDEO: dict[str, str] = {
	"id": "demo-video-001",
	"title": "A Simple Guide to Choosing the Right Coffee Beans",
	"description": (
		"Learn how roast level, origin, and freshness affect the flavor in your "
		"cup, and find a coffee that fits your daily routine."
	),
	"embed_url": "https://www.youtube.com/watch?v=BIek57Kj3ag",
}

DEMO_BUSINESS_PERSONA: dict[str, str] = {
	"business_name": "Nourdoc",
	"tone": "Friendly, knowledgeable, and welcoming",
	"offers": "NourDoc transforms clinical conversations into structured, actionable healthcare information, supporting clinical documentation, coding and downstream healthcare workflows.",
	"reply_rules": (
		"Be helpful and honest. Do not invent product details, prices, or "
		"promises. Invite viewers to explore only when it naturally fits."
	),
}

DEMO_COMMENTS: list[dict[str, str]] = [
	{
		"author": "Jamie",
		"text": "I'm new to Nourdoc. Give me an introduction?",
	},
	{
		"author": "Morgan",
		"text": "What are the benefits of using Nourdoc in my practice?",
	},
	{
		"author": "Taylor",
		"text": "How does Nourdoc ensure data privacy and security?",
	},
	{
		"author": "Riley",
		"text": "Is it real that Nourdoc make the life of doctor easy ",
	},
	{
		"author": "Casey",
		"text": "Can I use the Nourdoc for our practice?",
	},
]


def get_demo_video() -> dict[str, str]:
	"""Return demo video details with the player ID derived from its URL."""
	video = DEMO_VIDEO.copy()
	video["embed_video_id"] = _get_youtube_video_id(video["embed_url"])
	return video


def _get_youtube_video_id(video_url: str) -> str:
	"""Extract and validate a video ID from common YouTube URL formats."""
	parsed_url = urlsplit(video_url)
	host = (parsed_url.hostname or "").lower()

	if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
		if parsed_url.path == "/watch":
			video_id = parse_qs(parsed_url.query).get("v", [""])[0]
		elif parsed_url.path.startswith(("/embed/", "/shorts/", "/live/")):
			video_id = parsed_url.path.split("/")[2]
		else:
			video_id = ""
	elif host in {
		"youtu.be",
		"www.youtu.be",
		"youtube-nocookie.com",
		"www.youtube-nocookie.com",
	}:
		path_parts = parsed_url.path.strip("/").split("/")
		video_id = (
			path_parts[1]
			if host.endswith("youtube-nocookie.com")
			and len(path_parts) == 2
			and path_parts[0] == "embed"
			else path_parts[0]
			if not host.endswith("youtube-nocookie.com")
			else ""
		)
	else:
		video_id = ""

	if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
		raise ValueError("Demo video URL must contain a valid YouTube video ID")
	return video_id


def get_persona_summary() -> dict[str, str]:
	"""Return only the public persona fields used in the demo."""
	return DEMO_BUSINESS_PERSONA.copy()


def get_sample_comments() -> list[dict[str, str]]:
	"""Return copies of the fixed sample comments."""
	return [comment.copy() for comment in DEMO_COMMENTS]
