import sys
import time
import datetime
import random
import requests
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.database import SessionLocal, init_db
from backend.app.models import Camera, Detection, Watchlist, utcnow
from backend.app.services.alert_engine import check_and_generate_alert
from backend.app.services.catalogue import sync_catalogue_with_db

def simulate_cross_camera_journey(target_plate: str = "GJ01AB1234"):
    """
    Simulates a target suspect vehicle traveling across 5 consecutive
    departmental CCTV checkpoints along the SG Highway corridor in Ahmedabad.
    Generates realistic PTS timestamps, elapsed transit times, and database records.
    """
    print(f"\n=======================================================")
    print(f" SIMULATING CROSS-CAMERA JOURNEY FOR: {target_plate}")
    print(f"=======================================================")

    init_db()
    db = SessionLocal()

    # Ensure catalogue is seeded
    if db.query(Camera).count() == 0:
        sync_catalogue_with_db(db)

    cameras = db.query(Camera).filter(Camera.district == "Ahmedabad").order_by(Camera.camera_id).limit(5).all()
    if not cameras:
        print("[ERROR] No cameras found in database to simulate route.")
        return

    # Delete previous detections for this target plate for clean demonstration
    db.query(Detection).filter(Detection.plate_number == target_plate).delete()
    db.commit()

    base_time = utcnow() - datetime.timedelta(minutes=25)
    current_time = base_time

    total_simulated = 0
    for i, cam in enumerate(cameras):
        # 3 to 5 minutes travel time between successive intersections
        transit_minutes = random.randint(3, 5) if i > 0 else 0
        current_time += datetime.timedelta(minutes=transit_minutes)

        # Vehicle is captured across 3-4 consecutive frames as it passes
        dwell_frames = random.randint(3, 5)
        for frame_idx in range(dwell_frames):
            frame_time = current_time + datetime.timedelta(seconds=frame_idx * 2)
            pts_ms = int(frame_time.timestamp() * 1000)

            det = Detection(
                camera_id=cam.camera_id,
                plate_number=target_plate,
                plate_raw=target_plate,
                confidence=round(random.uniform(0.88, 0.98), 2),
                vehicle_type="CAR",
                pts_timestamp_ms=pts_ms,
                capture_timestamp=frame_time,
                snapshot_path=None
            )
            db.add(det)
            db.commit()
            db.refresh(det)
            total_simulated += 1

            # Check for alert trigger on final sighting
            if i == len(cameras) - 1 and frame_idx == 0:
                alert = check_and_generate_alert(db, det, cam)
                if alert:
                    print(f"  [ALERT FIRED] Watchlist match for {target_plate} at {cam.name}!")

        print(f"  Checkpoint #{i+1}: Sighted at {cam.name} ({cam.department}) at {current_time.strftime('%H:%M:%S UTC')}")

    db.close()
    print(f"\n[SUCCESS] Simulated {total_simulated} detection events across {len(cameras)} cameras.")
    print(f"Open dashboard at http://127.0.0.1:8000 and enter '{target_plate}' to view instant GIS route!\n")

if __name__ == "__main__":
    plate = sys.argv[1] if len(sys.argv) > 1 else "GJ01AB1234"
    simulate_cross_camera_journey(plate)
