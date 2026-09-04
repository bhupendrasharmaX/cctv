import os
import sys
import time
import argparse
import cv2

# Force RTSP over TCP as required by challenge guidelines
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

def test_rtsp_stream(url: str, max_frames: int = 50):
    print(f"[TEST] Opening RTSP stream over TCP: {url}")
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

    if not cap.isOpened():
        print(f"[FAIL] Could not open video capture for: {url}")
        return False

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    print(f"[CONNECTED] Stream properties: {width}x{height} | Reported FPS: {fps}")
    print("[INFO] Note: As per challenge rules, we do not rely on CAP_PROP_FPS for timing.")

    frame_count = 0
    start_time = time.time()

    while frame_count < max_frames:
        ret, frame = cap.read()
        if not ret:
            print("[WARN] Frame read returned empty or stream finished.")
            break

        frame_count += 1
        pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

        if frame_count % 10 == 0 or frame_count == 1:
            print(f"  Frame #{frame_count:03d}: PTS={pts_ms:.1f}ms | Resolution={frame.shape[1]}x{frame.shape[0]}")

    elapsed = time.time() - start_time
    cap.release()
    print(f"[SUMMARY] Read {frame_count} frames in {elapsed:.2f}s (Actual throughput: {frame_count/elapsed:.1f} FPS)")
    return frame_count > 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test RTSP stream over TCP with PTS capture")
    parser.add_argument("--url", default="rtsp://localhost:8554/stream/1", help="RTSP stream URL")
    parser.add_argument("--frames", type=int, default=50, help="Number of frames to test")
    args = parser.parse_args()
    test_rtsp_stream(args.url, args.frames)
