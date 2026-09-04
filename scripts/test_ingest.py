import sys
import argparse
import requests
import json

def test_ingest_endpoint(url: str):
    print(f"[TEST] Querying Government CCTV Ingestion Catalogue: {url}")
    try:
        resp = requests.get(url, timeout=5.0)
        print(f"[STATUS] HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            cameras = data if isinstance(data, list) else data.get("cameras", data.get("data", []))
            print(f"[SUCCESS] Discovered {len(cameras)} cameras from gateway.")
            for i, c in enumerate(cameras[:5]):
                cid = c.get("camera_id") or c.get("id")
                name = c.get("name", "Unknown")
                rtsp = c.get("rtsp_url", f"rtsp://.../stream/{c.get('stream_id', i+1)}")
                print(f"  #{i+1}: ID={cid} | {name} | RTSP={rtsp}")
            if len(cameras) > 5:
                print(f"  ... and {len(cameras) - 5} more cameras.")
        else:
            print(f"[ERROR] Endpoint returned non-200 code: {resp.text}")
    except Exception as e:
        print(f"[FAIL] Unable to reach {url}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Gujarat CCTV Ingest API")
    parser.add_argument("--url", default="http://localhost/api/ingest", help="Catalogue ingest URL")
    args = parser.parse_args()
    test_ingest_endpoint(args.url)
