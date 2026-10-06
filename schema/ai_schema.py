from pydantic import BaseModel, ConfigDict, Field


class ReplyDraftResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	youtube_comment_id: str
	ai_reply: str | None
	is_replied: bool
	skipped: bool = False
	error: str | None = None


class ReplyDraftBatch(BaseModel):
	model_config = ConfigDict(extra="forbid")

	results: list[ReplyDraftResult]
	next_offset: int = Field(ge=0)
	has_more: bool
