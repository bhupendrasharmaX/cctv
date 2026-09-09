"""
Snapshot retention.

Every detection writes a JPEG crop into data/snapshots/ and nothing ever removed
them. On a live feed that is unbounded growth on the same disk the database
sits on, so the platform eventually fails by filling the volume.

Snapshots are evidence, so pruning is deliberate and configurable rather than
aggressive: an age limit, plus a file-count ceiling as a backstop against a
burst. Both are disabled by setting the corresponding value to 0.
"""

import logging
import time
from pathlib import Path
from typing import Dict

from backend.app.config import (
    SNAPSHOT_DIR,
    SNAPSHOT_MAX_FILES,
    SNAPSHOT_RETENTION_DAYS,
)

logger = logging.getLogger("cctv.retention")


def prune_snapshots(
    directory: Path = SNAPSHOT_DIR,
    retention_days: int = SNAPSHOT_RETENTION_DAYS,
    max_files: int = SNAPSHOT_MAX_FILES,
) -> Dict[str, int]:
    """
    Remove snapshots older than the retention window, then enforce the file
    ceiling by dropping the oldest first. Returns what it deleted.
    """
    if not directory.exists():
        return {"deleted_by_age": 0, "deleted_by_count": 0, "remaining": 0}

    files = []
    for path in directory.glob("*.jpg"):
        try:
            files.append((path, path.stat().st_mtime))
        except OSError:
            continue

    deleted_by_age = 0
    if retention_days > 0:
        cutoff = time.time() - retention_days * 86400
        survivors = []
        for path, mtime in files:
            if mtime < cutoff:
                try:
                    path.unlink()
                    deleted_by_age += 1
                except OSError as e:
                    logger.warning(f"Could not delete expired snapshot {path.name}: {e}")
                    survivors.append((path, mtime))
            else:
                survivors.append((path, mtime))
        files = survivors

    deleted_by_count = 0
    if max_files > 0 and len(files) > max_files:
        files.sort(key=lambda item: item[1])  # oldest first
        for path, _mtime in files[: len(files) - max_files]:
            try:
                path.unlink()
                deleted_by_count += 1
            except OSError as e:
                logger.warning(f"Could not delete surplus snapshot {path.name}: {e}")
        files = files[len(files) - max_files:]

    if deleted_by_age or deleted_by_count:
        logger.info(
            f"Snapshot retention: removed {deleted_by_age} expired and "
            f"{deleted_by_count} surplus files; {len(files)} remain."
        )

    return {
        "deleted_by_age": deleted_by_age,
        "deleted_by_count": deleted_by_count,
        "remaining": len(files),
    }
