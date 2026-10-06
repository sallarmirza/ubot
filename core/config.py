# config.py
import os
from dotenv import load_dotenv

load_dotenv(override=True)


class Settings:
    DATABASE_URL = os.getenv("DATABASE_URL")

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
    FRONTEND_URL=os.getenv('FRONTEND_URL')
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "7"))
    COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    AI_API_KEY = os.getenv("AI_API_KEY")
    AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")


settings = Settings()