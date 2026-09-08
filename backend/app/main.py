import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.config import SNAPSHOT_DIR, DATA_DIR, CORS_ALLOW_ORIGINS
from backend.app.database import init_db, SessionLocal
from backend.app.services.catalogue import sync_catalogue_with_db
from backend.app.services.alert_engine import ws_manager, register_event_loop
from backend.app.routers import registry, search, watchlist, alerts, stream_control

# Configure system-wide logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
)
logger = logging.getLogger("cctv.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    logger.info("Initializing Gujarat CCTV Unified Analytics & Command Platform...")

    # Hand the running loop to the alert engine. Detections are produced from
    # threads (stream workers, and FastAPI's threadpool for sync endpoints), so
    # without this handle every real-time broadcast is silently discarded.
    register_event_loop(asyncio.get_running_loop())

    init_db()

    # Pre-populate watchlist & camera catalogue if not present
    db = SessionLocal()
    try:
        from backend.app.models import Watchlist, Camera
        # Seed watchlist
        if db.query(Watchlist).count() == 0:
            logger.info("Seeding initial police watchlist records...")
            from backend.app.routers.watchlist import seed_watchlist
            seed_watchlist(db)

        # Onboard government CCTV feeds catalogue
        if db.query(Camera).count() == 0:
            logger.info("Synchronizing initial Gujarat CCTV camera catalogue...")
            sync_catalogue_with_db(db)
    except Exception as e:
        logger.error(f"Error during startup data initialization: {e}")
    finally:
        db.close()

    yield

    # Shutdown sequence
    logger.info("Shutting down CCTV platform services...")
    from ai_engine.multi_stream_runner import stream_pool
    stream_pool.stop_all()


app = FastAPI(
    title="Gujarat Police Unified CCTV & Video Analytics Platform",
    description="Unified Viewing, AI ANPR, Cross-Camera Vehicle Tracking & Real-Time Alert Command Center (Model 2 + Model 1)",
    version="2.1.0",
    lifespan=lifespan
)

# CORS. The dashboard is served by this same app, so same-origin needs no CORS
# entry at all; additional origins are opt-in through CORS_ALLOW_ORIGINS.
# A wildcard combined with allow_credentials is rejected by browsers anyway and
# would expose the camera registry (including RTSP URLs) to any website.
if CORS_ALLOW_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

# Mount API routers
app.include_router(registry.router)
app.include_router(search.router)
app.include_router(watchlist.router)
app.include_router(alerts.router)
app.include_router(stream_control.router)


@app.get("/api/health", tags=["System"])
def health_check():
    """Liveness probe plus live client/worker counts for the dashboard header."""
    from ai_engine.multi_stream_runner import stream_pool
    return {
        "status": "healthy",
        "dashboard_clients": len(ws_manager.active_connections),
        "ai_workers": stream_pool.get_status(),
    }


# Real-time WebSocket connection for live alerts and detections
@app.websocket("/ws/alerts")
async def websocket_alerts_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; accept any ping from client
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

# Mount snapshot static directory
app.mount("/snapshots", StaticFiles(directory=str(SNAPSHOT_DIR)), name="snapshots")

# Mount frontend client
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
