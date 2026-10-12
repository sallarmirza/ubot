from pydantic import BaseModel, ConfigDict, Field, field_validator


class VideoResponse(BaseModel):
	"""Video fields returned by YouTube and saved for a selected video."""

	model_config = ConfigDict(extra="forbid")

	youtube_video_id: str = Field(min_length=1, max_length=50)
	title: str = Field(default="", max_length=255)
	channel_name: str = Field(default="", max_length=255)
	description: str = Field(default="", max_length=800)
	views: int = Field(default=0, ge=0)
	likes: int = Field(default=0, ge=0)
	comments: int = Field(default=0, ge=0)
	selected: bool = False
	description_required: bool = False


class SelectedVideoInput(BaseModel):
	"""One selected video and a description if YouTube has none."""

	model_config = ConfigDict(extra="forbid")

	youtube_video_id: str = Field(min_length=1, max_length=50)
	description: str = Field(default="", max_length=800)

	@field_validator("youtube_video_id", "description")
	@classmethod
	def strip_text(cls, value: str) -> str:
		return value.strip()


class SelectedVideosRequest(BaseModel):
	"""Video IDs selected by the user for one of their channels."""

	model_config = ConfigDict(extra="forbid")

	channel_id: str = Field(min_length=1, max_length=100)
	# A channel has exactly one active monitored video.
	videos: list[SelectedVideoInput] = Field(min_length=1, max_length=1)

	@field_validator("videos")
	@classmethod
	def validate_videos(cls, videos: list[SelectedVideoInput]) -> list[SelectedVideoInput]:
		video_ids = [video.youtube_video_id for video in videos]
		if len(video_ids) != len(set(video_ids)):
			raise ValueError("Video IDs must not contain duplicates")
		return videos
