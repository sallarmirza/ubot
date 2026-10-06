# main.py 
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from core.config import settings
from db_manager import db_manager                      # <- add

from router.business_profile_router import router as business_profile_router
from router.google_oauth_router import router as oauth_router

app=FastAPI(title="Fastapi Backend")
db_manager.create_tables()                             # <- add

allowed_origins = ["http://localhost:5500", "http://127.0.0.1:5500"]
if settings.FRONTEND_URL:
    frontend_url = urlsplit(settings.FRONTEND_URL)
    if frontend_url.scheme and frontend_url.netloc:
        frontend_origin = f"{frontend_url.scheme}://{frontend_url.netloc}"
        if frontend_origin not in allowed_origins:
            allowed_origins.append(frontend_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(oauth_router, prefix="/auth")
app.include_router(business_profile_router)
app.mount("/test", StaticFiles(directory="test", html=True), name="test")


@app.get('/')
def get_heath():
    return "Backend is up and running"

