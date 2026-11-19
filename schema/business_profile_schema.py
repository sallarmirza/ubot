from pydantic import BaseModel, Field, field_validator


class BusinessProfileRequest(BaseModel):
    """Fields the frontend sends when saving a channel profile."""

    channel_id: str = Field(min_length=1, max_length=100)
    business_name: str = Field(default="", max_length=255)
    services: str = Field(default="", max_length=800)
    brand_tone: str = Field(default="", max_length=50)
    ai_rules: str = Field(default="", max_length=300)
    comment_fetch_interval_minutes: int | None = Field(
        default=None, strict=True, ge=1, le=1440
    )

    @field_validator("comment_fetch_interval_minutes", mode="before")
    @classmethod
    def reject_null_interval(cls, value):
        if value is None:
            raise ValueError("comment_fetch_interval_minutes must be an integer")
        return value