"""
Sentinel — Phase 1: Minimal Feed Verification Script
-----------------------------------------------------
Performs single-stream RTSP verification over TCP with OpenCV:
1. Queries GET http://<host>/api/ingest to parse camera catalogue (if host provided).
2. Forces RTSP over TCP via OPENCV_FFMPEG_CAPTURE_OPTIONS.
3. Implements reconnect loop with exponential backoff (~2s to ~30s cap).
4. Captures and inspects stream PTS (CAP_PROP_POS_MSEC), resolution, codec, and actual throughput.
5. Runs for ~15 seconds and exits cleanly.

Zero database connections, zero UI, zero AI models.
"""

import os
import sys
import time
import argparse
import logging
from typing import Optional, Dict, Any, List
import requests
import cv2

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("feed_check")

# Force RTSP over TCP as mandated by challenge requirements
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"


def fetch_catalogue(host: str) -> Optional[List[Dict[str, Any]]]:
    """
    Fetches and parses the camera catalogue from GET http://<host>/api/ingest.
    """
    ingest_url = f"http://{host}/api/ingest" if not host.startswith("http") else host
    logger.info(f"Querying CCTV ingestion endpoint: {ingest_url}")

    try:
        resp = requests.get(ingest_url, timeout=5.0)
        logger.info(f"Response HTTP Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            cameras = data if isinstance(data, list) else data.get("cameras", data.get("data", []))
            logger.info(f"Successfully discovered {len(cameras)} cameras in catalogue.")
            print("\n" + "=" * 70)
            print("  DISCOVERED CAMERA CATALOGUE")
            print("=" * 70)
            for idx, c in enumerate(cameras[:10]):
                cid = c.get("camera_id") or c.get("id") or f"CAM-{idx+1}"
                name = c.get("name", "Unnamed Camera")
                rtsp = c.get("rtsp_url") or f"rtsp://{host}:8554/stream/{c.get('stream_id', idx+1)}"
                codec = c.get("codec", "H264")
                print(f"  [{idx+1:02d}] ID: {cid:<18} | Codec: {codec:<5} | Name: {name[:24]:<24} | RTSP: {rtsp}")
            if len(cameras) > 10:
                print(f"  ... and {len(cameras) - 10} more cameras.")
            print("=" * 70 + "\n")
            return cameras
        else:
            logger.error(f"Failed to fetch catalogue: HTTP {resp.status_code} - {resp.text[:200]}")
            return None
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection refused / unable to reach {ingest_url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error querying {ingest_url}: {e}")
        return None


def open_stream_with_backoff(
    rtsp_url: str,
    max_retries: int = 5,
    initial_backoff: float = 2.0,
    max_backoff: float = 30.0
) -> Optional[cv2.VideoCapture]:
    """
    Opens an RTSP stream over TCP with exponential backoff reconnect logic.
    """
    backoff = initial_backoff
    attempt = 0

    while attempt < max_retries:
        attempt += 1
        logger.info(f"Connecting to RTSP stream (Attempt {attempt}/{max_retries}): {rtsp_url}")
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

        if cap.isOpened():
            # Verify we can read at least the first frame
            ret, _ = cap.read()
            if ret:
                logger.info("Successfully connected to RTSP stream and received initial frame.")
                return cap
            else:
                logger.warning("Stream opened but initial frame read returned empty.")
                cap.release()
        else:
            logger.warning(f"Could not open RTSP stream at: {rtsp_url}")

        if attempt < max_retries:
            logger.info(f"Retrying connection in {backoff:.1f}s (exponential backoff)...")
            time.sleep(backoff)
            backoff = min(backoff * 2.0, max_backoff)

    logger.error(f"Exceeded maximum reconnect attempts ({max_retries}) for {rtsp_url}")
    return None


def verify_stream(rtsp_url: str, test_duration_sec: float = 15.0) -> bool:
    """
    Streams from RTSP URL for ~test_duration_sec, analyzing PTS, resolution,
    codec metadata, and throughput.
    """
    print("\n" + "=" * 70)
    print("  SENTINEL — PHASE 1 RTSP STREAM VERIFICATION")
    print("=" * 70)
    print(f"  Target RTSP URL:       {rtsp_url}")
    print(f"  Transport Protocol:    TCP (OPENCV_FFMPEG_CAPTURE_OPTIONS)")
    print(f"  Target Test Duration:  {test_duration_sec:.1f} seconds")
    print("=" * 70 + "\n")

    cap = open_stream_with_backoff(rtsp_url)
    if not cap:
        print(f"\n[FAIL] Unable to establish RTSP connection to: {rtsp_url}\n")
        return False

    # Extract static stream properties reported by demuxer
    reported_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    reported_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    reported_fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = "".join([chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)]) if fourcc_int != -1 else "UNKNOWN"

    logger.info(f"Reported Dimensions: {reported_width}x{reported_height}")
    logger.info(f"Reported Codec/FourCC: {fourcc_str}")
    logger.info(f"Reported FPS: {reported_fps:.2f} (Note: operational timing strictly uses PTS)")

    frame_count = 0
    start_wall_time = time.time()
    last_log_time = start_wall_time
    last_pts = None
    pts_jumps = 0
    actual_width = 0
    actual_height = 0

    try:
        while (time.time() - start_wall_time) < test_duration_sec:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Frame read failed or stream interrupted. Attempting reconnect...")
                cap.release()
                cap = open_stream_with_backoff(rtsp_url, max_retries=3)
                if not cap:
                    logger.error("Failed to recover stream during reconnect.")
                    break
                continue

            frame_count += 1
            actual_height, actual_width = frame.shape[:2]

            # Stream timestamp / PTS
            pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            if last_pts is not None and pts_ms < last_pts:
                pts_jumps += 1
            last_pts = pts_ms

            # Log status periodically (~every 2 seconds)
            current_time = time.time()
            if (current_time - last_log_time) >= 2.0 or frame_count == 1:
                elapsed = current_time - start_wall_time
                fps_now = frame_count / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Frame #{frame_count:04d} | Elapsed: {elapsed:04.1f}s | "
                    f"PTS: {pts_ms:10.1f}ms | Resolution: {actual_width}x{actual_height} | "
                    f"Throughput: {fps_now:5.1f} FPS"
                )
                last_log_time = current_time

    finally:
        total_wall_time = time.time() - start_wall_time
        cap.release()

    avg_fps = (frame_count / total_wall_time) if total_wall_time > 0 else 0.0

    print("\n" + "=" * 70)
    print("  VERIFICATION RUN SUMMARY")
    print("=" * 70)
    print(f"  Frames Successfully Read: {frame_count}")
    print(f"  Total Duration:            {total_wall_time:.2f} seconds")
    print(f"  Actual Stream Throughput:  {avg_fps:.2f} FPS")
    print(f"  Validated Resolution:      {actual_width}x{actual_height}")
    print(f"  Final Stream PTS:          {last_pts if last_pts is not None else 0.0:.1f} ms")
    print(f"  PTS Out-of-Order Events:   {pts_jumps}")
    print(f"  Transport Confirmed:       TCP (Forced)")
    print("=" * 70 + "\n")

    if frame_count > 0:
        logger.info("[SUCCESS] Feed verification completed successfully.")
        return True
    else:
        logger.error("[FAIL] No frames were read during verification.")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Phase 1 — Feed Verification & RTSP Ingestion Test"
    )
    parser.add_argument(
        "--host",
        default=None,
        help="CCTV gateway host or IP (e.g. 192.168.1.50 or localhost)"
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Direct RTSP stream URL (e.g. rtsp://<host>:8554/stream/1)"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=15.0,
        help="Duration in seconds to test the stream (default: 15.0)"
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="Camera index from catalogue to stream (default: 0)"
    )
    args = parser.parse_args()

    rtsp_target = args.url

    # If host is provided, first query GET /api/ingest
    if args.host:
        cameras = fetch_catalogue(args.host)
        if cameras and not rtsp_target:
            idx = min(args.camera_index, len(cameras) - 1)
            selected_cam = cameras[idx]
            cid = selected_cam.get("camera_id") or selected_cam.get("id", f"CAM-{idx+1}")
            cname = selected_cam.get("name", "Unknown")
            rtsp_target = selected_cam.get("rtsp_url")
            if not rtsp_target:
                stream_id = selected_cam.get("stream_id", idx + 1)
                rtsp_target = f"rtsp://{args.host}:8554/stream/{stream_id}"
            logger.info(f"Selected Camera #{idx+1} ({cid} - {cname}) -> {rtsp_target}")

    # Fallback if neither host nor url is passed
    if not rtsp_target:
        env_host = os.getenv("GOVT_GATEWAY_HOST", "localhost")
        logger.warning(
            f"No --url or accessible --host provided. Using default fallback: rtsp://{env_host}:8554/stream/1"
        )
        rtsp_target = f"rtsp://{env_host}:8554/stream/1"

    success = verify_stream(rtsp_target, test_duration_sec=args.duration)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
