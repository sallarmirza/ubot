# main.py 
import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from core.config import settings
from db_manager import db_manager                      # <- add

from router.business_profile_router import router as business_profile_router
from router.ai_router import router as ai_router
from router.analytics_router import router as analytics_router
from router.demo_router import router as demo_router
from router.comments_fetching_router import router as comments_fetching_router
from router.contact_router import router as contact_router
from router.google_oauth_router import router as oauth_router
from router.selection_video_router import router as selection_video_router
from services.http_clients import (
    close_http_clients,
    get_async_http_client,
    get_sync_http_client,
)
from services.comment_monitor_service import run_comment_monitoring_loop
from services.data_retention_service import run_data_retention_cleanup_loop
from core.token_encryption import encrypt_legacy_oauth_tokens


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    comment_monitor_task = None
    retention_cleanup_task = None
    try:
        # Fail startup rather than serving requests with OAuth tokens left in plaintext.
        encrypted_rows = encrypt_legacy_oauth_tokens(db_manager.engine)
        if encrypted_rows:
            logger.info("Encrypted legacy OAuth tokens for %s accounts", encrypted_rows)
        app.state.http_clients = (
            get_sync_http_client(),
            get_async_http_client(),
        )
        comment_monitor_task = asyncio.create_task(
            run_comment_monitoring_loop(),
            name="comment-monitor",
        )
        retention_cleanup_task = asyncio.create_task(
            run_data_retention_cleanup_loop(),
            name="data-retention-cleanup",
        )
        yield
    finally:
        try:
            background_tasks = [
                task
                for task in (
                    comment_monitor_task,
                    retention_cleanup_task,
                )
                if task is not None
            ]
            for task in background_tasks:
                task.cancel()
            for task in background_tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            try:
                await close_http_clients()
            finally:
                try:
                    db_manager.close()
                finally:
                    if hasattr(app.state, "http_clients"):
                        del app.state.http_clients


app=FastAPI(title="Fastapi Backend", lifespan=lifespan)
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
app.include_router(ai_router)
app.include_router(analytics_router)
app.include_router(demo_router)
app.include_router(selection_video_router)
app.include_router(comments_fetching_router)
app.include_router(contact_router)
app.mount("/test", StaticFiles(directory="test", html=True), name="test")


@app.get('/')
def get_heath():
    return "Backend is up and running"
