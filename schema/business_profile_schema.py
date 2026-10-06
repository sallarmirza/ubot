from pydantic import BaseModel, Field


class BusinessProfileRequest(BaseModel):
    """Fields the frontend sends when saving a channel profile."""

    channel_id: str = Field(min_length=1, max_length=100)
    business_name: str = Field(default="", max_length=255)
    services: str = Field(default="", max_length=800)
    brand_tone: str = Field(default="", max_length=50)
    ai_rules: str = Field(default="", max_length=300)