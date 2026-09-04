import os
import sys
import argparse
import uvicorn
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

def main():
    parser = argparse.ArgumentParser(description="Gujarat Police Unified CCTV & Analytics Platform")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    parser.add_argument("--gateway-host", default="localhost", help="Government CCTV gateway host IP/domain")
    parser.add_argument("--simulate-demo", action="store_true", help="Pre-load a simulated cross-camera journey for demo")
    args = parser.parse_args()

    os.environ["GOVT_GATEWAY_HOST"] = args.gateway_host
    os.environ["SERVER_HOST"] = args.host
    os.environ["SERVER_PORT"] = str(args.port)

    print("\n" + "=" * 65)
    print("  GUJARAT POLICE UNIFIED CCTV & VIDEO ANALYTICS PLATFORM")
    print("  Model 2 (Unified Viewing & Analytics) + Model 1 (Registry & GIS)")
    print("=" * 65)
    print(f"  • Gateway Host:      {args.gateway_host}")
    print(f"  • Server Interface:  http://{args.host}:{args.port}")
    print(f"  • Command Dashboard: http://127.0.0.1:{args.port}")
    print("=" * 65 + "\n")

    # Initialize database & catalogue
    from backend.app.database import init_db, SessionLocal
    from backend.app.services.catalogue import sync_catalogue_with_db
    from backend.app.routers.watchlist import seed_watchlist

    init_db()
    db = SessionLocal()
    try:
        print("[INIT] Seeding police watchlist and camera catalogue...")
        seed_watchlist(db)
        sync_catalogue_with_db(db, host=args.gateway_host)

        if args.simulate_demo:
            from scripts.simulate_feed import simulate_cross_camera_journey
            simulate_cross_camera_journey("GJ01AB1234")
    finally:
        db.close()

    print("\n[READY] Launching high-performance FastAPI server...\n")
    uvicorn.run("backend.app.main:app", host=args.host, port=args.port, reload=False)

if __name__ == "__main__":
    main()
