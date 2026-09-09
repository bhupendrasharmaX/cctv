import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'cctv.db'}")

# Government CCTV Gateway Ingestion Config
# The host IP or domain where http://<host>/api/ingest and rtsp://<host>:8554/stream/<id> live
GOVT_GATEWAY_HOST = os.getenv("GOVT_GATEWAY_HOST", "localhost")
GOVT_INGEST_URL = os.getenv("GOVT_INGEST_URL", f"http://{GOVT_GATEWAY_HOST}/api/ingest")

# AI Processing Throttling
# Process 1 frame every N frames (at 25 FPS stream, N=8 gives ~3 FPS processing, preventing GPU/CPU overload)
AI_FRAME_SKIP = int(os.getenv("AI_FRAME_SKIP", "8"))
VEHICLE_CONF_THRESHOLD = float(os.getenv("VEHICLE_CONF_THRESHOLD", "0.35"))
OCR_CONF_THRESHOLD = float(os.getenv("OCR_CONF_THRESHOLD", "0.40"))

# Watchlist Alerting
# A vehicle dwells in frame across several sampled frames; without a cooldown a
# single pass raises one CRITICAL alert per frame and buries the operator.
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "120"))
# Below this length a single-character edit is too weak a signal to act on.
FUZZY_MATCH_MIN_LENGTH = int(os.getenv("FUZZY_MATCH_MIN_LENGTH", "8"))

# Cross-Camera Route Reconstruction
# Consecutive sightings at the same camera inside this window are one visit;
# beyond it the vehicle has left and returned, which is two distinct hops.
HOP_GROUPING_WINDOW_SECONDS = int(os.getenv("HOP_GROUPING_WINDOW_SECONDS", "120"))
# Inter-camera speeds above this are physically implausible on Gujarat roads and
# usually indicate a misread or cloned plate, so the hop is flagged for review
# rather than presented as fact.
IMPLAUSIBLE_SPEED_KMH = float(os.getenv("IMPLAUSIBLE_SPEED_KMH", "160.0"))

# API Safety Limits
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "500"))

# Access control. Unset means the API is open, which is only acceptable on
# localhost; see backend/app/security.py.
API_TOKEN = os.getenv("SENTINEL_API_TOKEN", "").strip()

# Snapshot retention. Evidence crops accumulate on every detection and nothing
# ever removed them; 0 disables pruning.
SNAPSHOT_RETENTION_DAYS = int(os.getenv("SNAPSHOT_RETENTION_DAYS", "30"))
SNAPSHOT_MAX_FILES = int(os.getenv("SNAPSHOT_MAX_FILES", "20000"))

# CORS: comma-separated origins. Defaults to same-origin only; the dashboard is
# served by this same app, so a wildcard buys nothing and exposes the registry.
CORS_ALLOW_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
]

# Server Config
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
