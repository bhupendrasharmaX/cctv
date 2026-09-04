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

# Server Config
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
