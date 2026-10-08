"""In-memory content for the public interactive demo."""

DEMO_VIDEO: dict[str, str] = {
	"id": "demo-video-001",
	"title": "A Simple Guide to Choosing the Right Coffee Beans",
	"description": (
		"Learn how roast level, origin, and freshness affect the flavor in your "
		"cup, and find a coffee that fits your daily routine."
	),
	"embed_video_id": "dQw4w9WgXcQ",
	"embed_url": "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
}

DEMO_BUSINESS_PERSONA: dict[str, str] = {
	"business_name": "Northstar Coffee",
	"tone": "Friendly, knowledgeable, and welcoming",
	"offers": "Small-batch coffee beans and practical brewing guidance",
	"reply_rules": (
		"Be helpful and honest. Do not invent product details, prices, or "
		"promises. Invite viewers to explore only when it naturally fits."
	),
}

DEMO_COMMENTS: list[dict[str, str]] = [
	{
		"author": "Jamie",
		"text": "I'm new to coffee. Which roast is usually the least bitter?",
	},
	{
		"author": "Morgan",
		"text": "Does a darker roast always have more caffeine?",
	},
	{
		"author": "Taylor",
		"text": "How should I store beans after opening the bag?",
	},
	{
		"author": "Riley",
		"text": "I like fruity coffee. What should I look for?",
	},
	{
		"author": "Casey",
		"text": "Can I use the same beans for espresso and a pour-over?",
	},
]


def get_demo_video() -> dict[str, str]:
	"""Return a copy of the fixed sample video's public details."""
	return DEMO_VIDEO.copy()


def get_persona_summary() -> dict[str, str]:
	"""Return only the public persona fields used in the demo."""
	return DEMO_BUSINESS_PERSONA.copy()


def get_sample_comments() -> list[dict[str, str]]:
	"""Return copies of the fixed sample comments."""
	return [comment.copy() for comment in DEMO_COMMENTS]
