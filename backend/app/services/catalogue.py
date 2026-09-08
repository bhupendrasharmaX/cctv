import logging
import requests
import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from backend.app.config import GOVT_INGEST_URL, GOVT_GATEWAY_HOST
from backend.app.models import Camera, utcnow

logger = logging.getLogger("cctv.catalogue")

def generate_default_gujarat_cameras(host: str) -> List[Dict[str, Any]]:
    """
    Realistic Gujarat CCTV registry seed for ~20 geographically distributed cameras
    across Ahmedabad, Gandhinagar, Surat, Vadodara, and Rajkot.
    Used when government evaluation gateway is offline or for local verification.
    """
    mock_cameras = [
        {
            "camera_id": "CAM-01-SG-HIGHWAY",
            "name": "Pakwan Crossroad Junction North",
            "department": "Gujarat Police Traffic Branch",
            "district": "Ahmedabad",
            "latitude": 23.0489,
            "longitude": 72.5054,
            "location_description": "SG Highway intersection opposite ISKCON temple corridor",
            "camera_type": "ANPR",
            "codec": "H264",
            "stream_id": "1"
        },
        {
            "camera_id": "CAM-02-VASTRAPUR",
            "name": "Vastrapur Lake Circle East",
            "department": "Ahmedabad Municipal Corporation (AMC)",
            "district": "Ahmedabad",
            "latitude": 23.0375,
            "longitude": 72.5298,
            "location_description": "Near Alpha One Mall arterial lane",
            "camera_type": "Fixed Bullet",
            "codec": "H264",
            "stream_id": "2"
        },
        {
            "camera_id": "CAM-03-ISCON-CROSS",
            "name": "ISKCON Flyover Landing South",
            "department": "Gujarat Police Highway Patrol",
            "district": "Ahmedabad",
            "latitude": 23.0286,
            "longitude": 72.5068,
            "location_description": "Bopal-Sanand approach ramp",
            "camera_type": "ANPR",
            "codec": "H264",
            "stream_id": "3"
        },
        {
            "camera_id": "CAM-04-SHIVRANJANI",
            "name": "Shivranjani Crossroad BRTS Corridor",
            "department": "Ahmedabad Janmarg (BRTS)",
            "district": "Ahmedabad",
            "latitude": 23.0242,
            "longitude": 72.5360,
            "location_description": "Dedicated BRTS lane monitoring lane 1",
            "camera_type": "PTZ",
            "codec": "H264",
            "stream_id": "4"
        },
        {
            "camera_id": "CAM-05-NEHRUNAGAR",
            "name": "Nehrunagar Circle Outbound",
            "department": "Gujarat Police Traffic Branch",
            "district": "Ahmedabad",
            "latitude": 23.0187,
            "longitude": 72.5443,
            "location_description": "Towards Manekbaug / Anjali crossroad",
            "camera_type": "ANPR",
            "codec": "H264",
            "stream_id": "5"
        },
        {
            "camera_id": "CAM-06-INFOCITY-GN",
            "name": "Infocity Circle Entry 1",
            "department": "Gandhinagar Municipal Corporation (GMC)",
            "district": "Gandhinagar",
            "latitude": 23.1925,
            "longitude": 72.6288,
            "location_description": "Main gate connecting TCS / NIFT campuses",
            "camera_type": "ANPR",
            "codec": "H264",
            "stream_id": "6"
        },
        {
            "camera_id": "CAM-07-CH0-GANDHINAGAR",
            "name": "CH-0 Roundabout Mahatma Mandir",
            "department": "State Intelligence & VIP Security",
            "district": "Gandhinagar",
            "latitude": 23.2156,
            "longitude": 72.6369,
            "location_description": "VIP corridor approaching Swarnim Sankul",
            "camera_type": "PTZ",
            "codec": "H265",
            "stream_id": "7"
        },
        {
            "camera_id": "CAM-08-SECTOR21-GN",
            "name": "Sector 21 Market Point",
            "department": "Gujarat Police Civil Branch",
            "district": "Gandhinagar",
            "latitude": 23.2285,
            "longitude": 72.6512,
            "location_description": "Major commercial hub arterial",
            "camera_type": "Fixed Bullet",
            "codec": "H264",
            "stream_id": "8"
        },
        {
            "camera_id": "CAM-09-AIRPORT-ROAD",
            "name": "Sardar Patel International Airport T2 Approach",
            "department": "Gujarat State Transport & RTO",
            "district": "Ahmedabad",
            "latitude": 23.0734,
            "longitude": 72.6266,
            "location_description": "Arrival concourse toll plaza lane 3",
            "camera_type": "ANPR",
            "codec": "H264",
            "stream_id": "9"
        },
        {
            "camera_id": "CAM-10-RINGROAD-SURAT",
            "name": "Majura Gate Flyover South",
            "department": "Surat City Police Control Room",
            "district": "Surat",
            "latitude": 21.1764,
            "longitude": 72.8223,
            "location_description": "Ring road textile market entry",
            "camera_type": "ANPR",
            "codec": "H264",
            "stream_id": "10"
        },
        {
            "camera_id": "CAM-11-ATHWAGATE-SURAT",
            "name": "Athwagate Chowk T-Junction",
            "department": "Surat Municipal Corporation (SMC)",
            "district": "Surat",
            "latitude": 21.1852,
            "longitude": 72.8091,
            "location_description": "Tapi riverfront boulevard connection",
            "camera_type": "PTZ",
            "codec": "H264",
            "stream_id": "11"
        },
        {
            "camera_id": "CAM-12-SAYAJIGUNJ-BRD",
            "name": "Vadodara Central Railway Station West",
            "department": "Vadodara City Police",
            "district": "Vadodara",
            "latitude": 22.3106,
            "longitude": 73.1812,
            "location_description": "Sayajigunj bus terminal outbound lane",
            "camera_type": "ANPR",
            "codec": "H264",
            "stream_id": "12"
        },
        {
            "camera_id": "CAM-13-KALAGHODA-BRD",
            "name": "Kala Ghoda Circle North",
            "department": "Vadodara Municipal Corporation (VMC)",
            "district": "Vadodara",
            "latitude": 22.3168,
            "longitude": 73.1908,
            "location_description": "Vishwamitri bridge crossing",
            "camera_type": "Fixed Bullet",
            "codec": "H264",
            "stream_id": "13"
        },
        {
            "camera_id": "CAM-14-MADHAPAR-RJK",
            "name": "Madhapar Chowkdi Highway Ring",
            "department": "Rajkot Rural Police Highway Cell",
            "district": "Rajkot",
            "latitude": 22.3189,
            "longitude": 70.7712,
            "location_description": "Jamnagar-Rajkot highway divergence point",
            "camera_type": "ANPR",
            "codec": "H264",
            "stream_id": "14"
        },
        {
            "camera_id": "CAM-15-GIDC-VATVA",
            "name": "GIDC Vatva Phase 4 Main Checkpost",
            "department": "Gujarat Pollution & Industrial Security",
            "district": "Ahmedabad",
            "latitude": 22.9644,
            "longitude": 72.6321,
            "location_description": "Industrial freight exit checkpoint",
            "camera_type": "ANPR",
            "codec": "H264",
            "stream_id": "15"
        }
    ]

    camera_records = []
    for m in mock_cameras:
        stream_id = m["stream_id"]
        camera_records.append({
            "camera_id": m["camera_id"],
            "name": m["name"],
            "department": m["department"],
            "district": m["district"],
            "latitude": m["latitude"],
            "longitude": m["longitude"],
            "location_description": m["location_description"],
            "camera_type": m["camera_type"],
            "codec": m["codec"],
            "rtsp_url": f"rtsp://{host}:8554/stream/{stream_id}",
            "whep_url": f"http://{host}:8889/stream/{stream_id}/whep",
            "hls_url": f"http://{host}/live/stream/{stream_id}/index.m3u8",
            "connectivity_status": "ONLINE"
        })
    return camera_records


def sync_catalogue_with_db(db: Session, host: Optional[str] = None, ingest_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Onboard cameras from the government gateway endpoint:
    `curl -s http://<host>/api/ingest`
    If reachable: parses JSON catalogue.
    If unreachable: falls back to high-fidelity Gujarat CCTV network seed.
    Upserts into the `cameras` database table.

    Passing `host` alone now also retargets the ingest URL. Previously the host
    only affected the generated stream URLs while the fetch still went to the
    default gateway, so `?host=` appeared to work but silently queried the wrong
    machine.
    """
    host = host or GOVT_GATEWAY_HOST
    if ingest_url is None:
        ingest_url = f"http://{host}/api/ingest" if host != GOVT_GATEWAY_HOST else GOVT_INGEST_URL

    raw_data = None
    source = "live_gateway"

    try:
        logger.info(f"Attempting connection to government ingest API: {ingest_url}")
        resp = requests.get(ingest_url, timeout=3.0)
        if resp.status_code == 200:
            raw_data = resp.json()
            logger.info(f"Successfully received catalogue payload from {ingest_url}")
        else:
            logger.warning(f"Ingest endpoint returned HTTP {resp.status_code}. Using fallback seed.")
    except Exception as e:
        logger.warning(f"Unable to reach live gateway {ingest_url} ({e}). Initializing offline Gujarat CCTV seed.")

    if not raw_data:
        raw_data = generate_default_gujarat_cameras(host)
        source = "seed_fallback"

    # Normalize incoming catalogue data to database schema
    synced_count = 0
    now = utcnow()

    # Ingest endpoint might return {"cameras": [...]} or directly [...]
    camera_list = raw_data if isinstance(raw_data, list) else raw_data.get("cameras", raw_data.get("data", []))

    for item in camera_list:
        cam_id = str(item.get("camera_id") or item.get("id") or f"CAM-{item.get('stream_id', synced_count+1)}")
        name = item.get("name", f"Gujarat CCTV Node {cam_id}")
        department = item.get("department", "Gujarat Police Department")
        district = item.get("district", "Ahmedabad")
        latitude = float(item.get("latitude") or item.get("lat") or 23.0225)
        longitude = float(item.get("longitude") or item.get("lng") or item.get("lon") or 72.5714)
        loc_desc = item.get("location_description") or item.get("location", "")
        cam_type = item.get("camera_type", "ANPR")
        codec = item.get("codec", "H264")

        # Stream URLs following challenge specifications
        stream_id = item.get("stream_id", str(synced_count + 1))
        rtsp_url = item.get("rtsp_url") or f"rtsp://{host}:8554/stream/{stream_id}"
        whep_url = item.get("whep_url") or f"http://{host}:8889/stream/{stream_id}/whep"
        hls_url = item.get("hls_url") or f"http://{host}/live/stream/{stream_id}/index.m3u8"
        status = item.get("connectivity_status") or item.get("status", "ONLINE")

        existing = db.query(Camera).filter(Camera.camera_id == cam_id).first()
        if existing:
            existing.name = name
            existing.department = department
            existing.district = district
            existing.latitude = latitude
            existing.longitude = longitude
            existing.location_description = loc_desc
            existing.camera_type = cam_type
            existing.codec = codec
            existing.rtsp_url = rtsp_url
            existing.whep_url = whep_url
            existing.hls_url = hls_url
            existing.connectivity_status = status
            existing.last_ping = now
        else:
            new_cam = Camera(
                camera_id=cam_id,
                name=name,
                department=department,
                district=district,
                latitude=latitude,
                longitude=longitude,
                location_description=loc_desc,
                camera_type=cam_type,
                codec=codec,
                rtsp_url=rtsp_url,
                whep_url=whep_url,
                hls_url=hls_url,
                connectivity_status=status,
                last_ping=now,
                created_at=now
            )
            db.add(new_cam)
        synced_count += 1

    db.commit()
    return {
        "status": "success",
        "source": source,
        "synced_cameras": synced_count,
        "timestamp": now.isoformat()
    }
