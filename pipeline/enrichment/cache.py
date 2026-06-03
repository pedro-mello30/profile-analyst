"""Cache layer for the enrichment engine (spec 0014 §5.4)."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


def make_cache_key(adapter_id: str, entity_type: str, entity_value: str) -> str:
    """Return a deterministic sha256 hex digest for a (adapter, entity_type, entity_value) triple."""
    raw = f"{adapter_id}:{entity_type}:{entity_value}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_file(cache_dir: Path, adapter_id: str, entity_type: str, entity_value: str) -> Path:
    return cache_dir / f"{make_cache_key(adapter_id, entity_type, entity_value)}.json"


def write_cache(
    cache_dir: Path,
    adapter_id: str,
    entity_type: str,
    entity_value: str,
    payload: dict,
    ttl_hours: int,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_file(cache_dir, adapter_id, entity_type, entity_value)
    now = time.time()
    entry = {
        "adapter_id": adapter_id,
        "entity_type": entity_type,
        "entity_value": entity_value,
        "cached_at": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at_ts": now + ttl_hours * 3600,
        "payload": payload,
    }
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        json.dump(entry, fh)
    os.replace(tmp, path)


def read_cache(
    cache_dir: Path,
    adapter_id: str,
    entity_type: str,
    entity_value: str,
) -> dict | None:
    """Return cached payload or None if missing/expired."""
    path = _cache_file(cache_dir, adapter_id, entity_type, entity_value)
    if not path.exists():
        return None
    try:
        with open(path) as fh:
            entry = json.load(fh)
    except Exception:
        return None
    if time.time() > entry["expires_at_ts"]:
        return None
    return entry["payload"]


def is_expired(
    cache_dir: Path,
    adapter_id: str,
    entity_type: str,
    entity_value: str,
) -> bool:
    path = _cache_file(cache_dir, adapter_id, entity_type, entity_value)
    if not path.exists():
        return True
    try:
        with open(path) as fh:
            entry = json.load(fh)
        return time.time() > entry["expires_at_ts"]
    except Exception:
        return True


def secure_delete(path: Path, passes: int = 3) -> None:
    """Overwrite with random bytes N times then unlink (GDPR Art. 17 erasure)."""
    if not path.exists():
        return
    if path.is_dir():
        for child in list(path.iterdir()):
            secure_delete(child, passes=passes)
        path.rmdir()
        return
    size = path.stat().st_size
    if size > 0:
        with open(path, "r+b") as fh:
            for _ in range(passes):
                fh.seek(0)
                fh.write(os.urandom(size))
                fh.flush()
    path.unlink()
