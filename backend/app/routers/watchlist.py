import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from backend.app.database import get_db
from backend.app.models import Watchlist, WatchlistSchema
from pydantic import BaseModel

router = APIRouter(prefix="/api/watchlist", tags=["Police Watchlist Database"])

class WatchlistCreate(BaseModel):
    plate_number: str
    vehicle_owner: Optional[str] = None
    vehicle_make_model: Optional[str] = None
    crime_category: str
    fir_number: Optional[str] = None
    police_station: Optional[str] = None
    severity: str = "CRITICAL"
    notes: Optional[str] = None

@router.get("", response_model=List[WatchlistSchema])
def list_watchlist(active_only: bool = True, db: Session = Depends(get_db)):
    """Retrieve all vehicles currently under surveillance in the police watchlist."""
    query = db.query(Watchlist)
    if active_only:
        query = query.filter(Watchlist.active == True)
    return query.order_by(Watchlist.added_at.desc()).all()


@router.post("", response_model=WatchlistSchema)
def add_to_watchlist(item: WatchlistCreate, db: Session = Depends(get_db)):
    """Add a new suspect or stolen vehicle to the active surveillance watchlist."""
    normalized_plate = "".join(c for c in item.plate_number.upper() if c.isalnum())
    existing = db.query(Watchlist).filter(Watchlist.plate_number == normalized_plate).first()
    if existing:
        existing.active = True
        existing.crime_category = item.crime_category
        existing.severity = item.severity
        existing.notes = item.notes
        db.commit()
        db.refresh(existing)
        return existing

    new_entry = Watchlist(
        plate_number=normalized_plate,
        vehicle_owner=item.vehicle_owner,
        vehicle_make_model=item.vehicle_make_model,
        crime_category=item.crime_category,
        fir_number=item.fir_number,
        police_station=item.police_station,
        severity=item.severity,
        notes=item.notes,
        active=True
    )
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    return new_entry


@router.delete("/{watchlist_id}")
def remove_from_watchlist(watchlist_id: int, db: Session = Depends(get_db)):
    """
    Deactivate a vehicle so it stops raising alerts.

    Deliberately a soft deactivate, not a delete: this row is what ties existing
    Alert records to their FIR and crime category, and an alert that has already
    been acted on has to remain explicable afterwards.
    """
    entry = db.query(Watchlist).filter(Watchlist.watchlist_id == watchlist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    entry.active = False
    db.commit()
    return {
        "status": "success",
        "watchlist_id": entry.watchlist_id,
        "plate_number": entry.plate_number,
        "active": False,
        "message": f"Plate {entry.plate_number} deactivated - it will no longer raise alerts",
    }


@router.post("/{watchlist_id}/reactivate", response_model=WatchlistSchema)
def reactivate_watchlist_entry(watchlist_id: int, db: Session = Depends(get_db)):
    """
    Put a deactivated vehicle back under surveillance.

    Re-POSTing the plate also reactivates it, but that requires resending every
    field and silently overwrites the crime category and severity already on
    record. This restores the entry as it stands.
    """
    entry = db.query(Watchlist).filter(Watchlist.watchlist_id == watchlist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    entry.active = True
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/seed")
def seed_watchlist(db: Session = Depends(get_db)):
    """Populate initial realistic police watchlist records from seed_watchlist.json."""
    from backend.app.config import DATA_DIR
    seed_file = DATA_DIR / "seed_watchlist.json"
    if not seed_file.exists():
        raise HTTPException(status_code=404, detail=f"Seed file not found at {seed_file}")

    with open(seed_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    inserted = 0
    for item in data:
        plate = "".join(c for c in item["plate_number"].upper() if c.isalnum())
        existing = db.query(Watchlist).filter(Watchlist.plate_number == plate).first()
        if not existing:
            new_item = Watchlist(
                plate_number=plate,
                vehicle_owner=item.get("vehicle_owner"),
                vehicle_make_model=item.get("vehicle_make_model"),
                crime_category=item.get("crime_category", "Suspicious"),
                fir_number=item.get("fir_number"),
                police_station=item.get("police_station"),
                severity=item.get("severity", "CRITICAL"),
                notes=item.get("notes"),
                active=True
            )
            db.add(new_item)
            inserted += 1

    db.commit()
    return {"status": "success", "inserted_count": inserted}
