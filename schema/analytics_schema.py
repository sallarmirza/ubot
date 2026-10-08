from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AnalyticsComment(BaseModel):
	model_config = ConfigDict(extra="forbid")

	comment_id: int
	youtube_comment_id: str
	parent_youtube_comment_id: str | None
	comment_text: str
	ai_reply: str | None
	is_replied: bool
	youtube_reply_id: str | None
	reply_status: str
	created_at: datetime | None
	updated_at: datetime | None


class AnalyticsSnapshot(BaseModel):
	model_config = ConfigDict(extra="forbid")

	analytics_id: int
	views: int
	likes: int
	comments: int
	created_at: datetime | None
	updated_at: datetime | None


class SelectedVideoAnalytics(BaseModel):
	model_config = ConfigDict(extra="forbid")

	selected_video_id: int
	youtube_channel_id: str
	channel_name: str
	youtube_video_id: str
	title: str | None
	description: str | None
	prompt_context: str | None
	views: int
	likes: int
	youtube_comment_count: int
	saved_top_level_comments: int
	saved_replies: int
	generated_drafts: int
	posted_replies: int
	uncertain_replies: int
	created_at: datetime | None
	updated_at: datetime | None
	comments: list[AnalyticsComment]
	history: list[AnalyticsSnapshot]
