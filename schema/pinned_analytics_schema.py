from pydantic import BaseModel, ConfigDict, Field


class PinVideoRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")

	channel_id: str = Field(min_length=1, max_length=100)
	video_id: str = Field(min_length=1, max_length=50)


class PinEnabledRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")

	enabled: bool


class PinStatusResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	configured: bool
	enabled: bool
	channel_id: str | None
	video_id: str | None


class PinnedReply(BaseModel):
	model_config = ConfigDict(extra="forbid")

	comment_id: str
	author_name: str
	author_channel_id: str | None
	text: str
	published_at: str
	like_count: int


class PinnedComment(PinnedReply):
	replies: list[PinnedReply]


class PinnedAnalyticsResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	channel_id: str
	channel_name: str
	channel_subscribers: int
	channel_total_videos: int
	video_id: str
	video_title: str | None
	video_views: int
	video_likes: int
	video_comment_count: int
	comments_fetched: int
	max_comments: int
	max_replies_per_comment: int
	replied_comments: list[PinnedComment]
	unanswered_comments: list[PinnedComment]
