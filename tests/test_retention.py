"""
Snapshot retention.

Every detection writes a JPEG crop and nothing removed them, so the platform
eventually fills the volume the database sits on.
"""

import os
import time

import pytest

from backend.app.services.retention import prune_snapshots


@pytest.fixture()
def snapshot_dir(tmp_path):
    return tmp_path / "snapshots"


def _write(directory, name, age_days=0):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"jpeg-bytes")
    if age_days:
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
    return path


def test_removes_snapshots_past_the_retention_window(snapshot_dir):
    fresh = _write(snapshot_dir, "fresh.jpg", age_days=1)
    stale = _write(snapshot_dir, "stale.jpg", age_days=45)

    result = prune_snapshots(snapshot_dir, retention_days=30, max_files=0)

    assert result["deleted_by_age"] == 1
    assert fresh.exists()
    assert not stale.exists()


def test_enforces_a_file_ceiling_oldest_first(snapshot_dir):
    for i in range(6):
        _write(snapshot_dir, f"snap-{i}.jpg", age_days=6 - i)

    result = prune_snapshots(snapshot_dir, retention_days=0, max_files=3)

    assert result["deleted_by_count"] == 3
    assert result["remaining"] == 3
    # The three newest are the ones kept.
    remaining = sorted(p.name for p in snapshot_dir.glob("*.jpg"))
    assert remaining == ["snap-3.jpg", "snap-4.jpg", "snap-5.jpg"]


def test_zero_disables_pruning(snapshot_dir):
    _write(snapshot_dir, "ancient.jpg", age_days=900)

    result = prune_snapshots(snapshot_dir, retention_days=0, max_files=0)

    assert result["deleted_by_age"] == 0
    assert result["deleted_by_count"] == 0
    assert (snapshot_dir / "ancient.jpg").exists()


def test_leaves_non_snapshot_files_alone(snapshot_dir):
    _write(snapshot_dir, "keepme.txt", age_days=900)
    _write(snapshot_dir, ".gitkeep", age_days=900)

    prune_snapshots(snapshot_dir, retention_days=1, max_files=1)

    assert (snapshot_dir / "keepme.txt").exists()
    assert (snapshot_dir / ".gitkeep").exists()


def test_missing_directory_is_not_an_error(tmp_path):
    result = prune_snapshots(tmp_path / "does-not-exist", retention_days=30, max_files=10)
    assert result == {"deleted_by_age": 0, "deleted_by_count": 0, "remaining": 0}
