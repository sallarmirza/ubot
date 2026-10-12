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
from router.google_oauth_router import router as oauth_router
from router.selection_video_router import router as selection_video_router
from services.http_clients import (
    close_http_clients,
    get_async_http_client,
    get_sync_http_client,
)
from services.comment_monitor_service import (
    COMMENT_FETCH_INTERVAL_SECONDS,
    run_comment_monitoring_cycle,
)


logger = logging.getLogger(__name__)


async def _periodic_comment_monitor(stop_event: asyncio.Event) -> None:
    """Poll immediately and then repeat every five minutes without blocking ASGI."""
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(run_comment_monitoring_cycle)
        except Exception:
            logger.exception("Unexpected periodic comment-monitor failure")
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=COMMENT_FETCH_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    monitor_stop = asyncio.Event()
    monitor_task = None
    try:
        app.state.http_clients = (
            get_sync_http_client(),
            get_async_http_client(),
        )
        # The worker belongs to this FastAPI process and shuts down with it.
        monitor_task = asyncio.create_task(_periodic_comment_monitor(monitor_stop))
        yield
    finally:
        # Stop the monitor before closing the clients it uses.
        monitor_stop.set()
        if monitor_task is not None:
            await monitor_task
        try:
            await close_http_clients()
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
app.mount("/test", StaticFiles(directory="test", html=True), name="test")


@app.get('/')
def get_heath():
    return "Backend is up and running"
