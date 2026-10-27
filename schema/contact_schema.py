import re

from pydantic import (
	AliasChoices,
	BaseModel,
	ConfigDict,
	Field,
	field_validator,
	model_validator,
)


class ContactRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str = Field(min_length=1, max_length=100)
	email: str = Field(min_length=3, max_length=254)
	message: str = Field(default="", max_length=5000)
	company: str = Field(default="", max_length=255)
	channels: str = Field(default="", max_length=500)
	volume: str = Field(default="", max_length=100)
	website: str = Field(default="", max_length=255)
	recaptcha_token: str = Field(
		default="",
		max_length=4096,
		validation_alias=AliasChoices(
			"recaptcha_token", "recaptchaToken"
		),
	)
	captcha_token: str | None = Field(
		default=None, min_length=1, max_length=4096, validation_alias="captchaToken"
	)

	@field_validator("name")
	@classmethod
	def strip_required_text(cls, value: str) -> str:
		value = value.strip()
		if not value:
			raise ValueError("Field cannot be blank")
		return value

	@field_validator("message", "company", "channels", "volume", "website")
	@classmethod
	def strip_optional_text(cls, value: str) -> str:
		return value.strip()

	@model_validator(mode="after")
	def normalize_captcha_token(self) -> "ContactRequest":
		if self.recaptcha_token and self.captcha_token:
			if self.recaptcha_token != self.captcha_token:
				raise ValueError("CAPTCHA token fields do not match")
		elif self.captcha_token:
			self.recaptcha_token = self.captcha_token
		if not self.recaptcha_token:
			raise ValueError("A reCAPTCHA token is required")
		return self

	@field_validator("email")
	@classmethod
	def validate_email(cls, value: str) -> str:
		value = value.strip()
		if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
			raise ValueError("A valid email address is required")
		return value


class ContactResponse(BaseModel):
	message: str
