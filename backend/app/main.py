import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.config import SNAPSHOT_DIR, DATA_DIR
from backend.app.database import init_db, SessionLocal
from backend.app.services.catalogue import sync_catalogue_with_db
from backend.app.services.alert_engine import ws_manager
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
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware for seamless browser communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(registry.router)
app.include_router(search.router)
app.include_router(watchlist.router)
app.include_router(alerts.router)
app.include_router(stream_control.router)

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
