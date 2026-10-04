"""Abuse limits that run before any paid Places call.

Per-visitor limit is in memory (the lookup form). The daily cap is a sqlite
counter so a process restart cannot reset the spend guard.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

DAILY_CAP_MESSAGE = "We've hit today's check limit. Please try again tomorrow."
IP_LIMIT_MESSAGE = "Too many checks from this connection. Please wait and try again."

_lock = threading.Lock()
_ip_hits: dict[str, list[float]] = {}


class DailyCapReached(Exception):
    def __init__(self, message: str | None = None):
        super().__init__(message or DAILY_CAP_MESSAGE)


class IpRateLimited(Exception):
    def __init__(self, message: str | None = None):
        super().__init__(message or IP_LIMIT_MESSAGE)


def places_daily_cap() -> int:
    raw = (os.environ.get("PLACES_DAILY_CAP") or "").strip()
    if not raw:
        return 150
    try:
        n = int(raw)
    except ValueError:
        return 150
    if n < 0:
        return 150
    return n


def _positive_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        n = int(raw)
    except ValueError:
        return default
    return n if n > 0 else default


def ip_limit() -> int:
    return _positive_int("PLACES_IP_LIMIT", 5)


def ip_window_seconds() -> int:
    return _positive_int("PLACES_IP_WINDOW_SECONDS", 3600)


def usage_db_path() -> Path:
    override = (os.environ.get("PLACES_USAGE_DB") or "").strip()
    path = Path(override) if override else Path(__file__).resolve().parent / "data" / "places_calls.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def visitor_ip(remote_addr: str, forwarded_for: str) -> str:
    for part in (forwarded_for or "").split(","):
        part = part.strip()
        if part:
            return part
    return (remote_addr or "").strip() or "unknown"


def reset_ip_limits() -> None:
    with _lock:
        _ip_hits.clear()


def enforce_lookup_ip(ip: str, *, now: float | None = None) -> None:
    """Count one lookup-form submission. Raise IpRateLimited when the window is full."""
    visitor = (ip or "").strip() or "unknown"
    limit = ip_limit()
    window = ip_window_seconds()
    moment = time.monotonic() if now is None else now
    with _lock:
        hits = [t for t in _ip_hits.get(visitor, []) if moment - t < window]
        if len(hits) >= limit:
            _ip_hits[visitor] = hits
            raise IpRateLimited()
        hits.append(moment)
        _ip_hits[visitor] = hits


def reserve_places_call(*, today: str | None = None) -> int:
    """Count one Places HTTP call. Raise DailyCapReached before the call when the cap is full."""
    cap = places_daily_cap()
    day = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = usage_db_path()
    with _lock:
        conn = sqlite3.connect(path, isolation_level=None)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS places_calls (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)"
            )
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT calls FROM places_calls WHERE day = ?", (day,)).fetchone()
            current = int(row[0]) if row else 0
            if current >= cap:
                conn.execute("ROLLBACK")
                raise DailyCapReached()
            updated = current + 1
            if row:
                conn.execute("UPDATE places_calls SET calls = ? WHERE day = ?", (updated, day))
            else:
                conn.execute("INSERT INTO places_calls (day, calls) VALUES (?, ?)", (day, updated))
            conn.execute("COMMIT")
            return updated
        except DailyCapReached:
            raise
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()


def calls_on(day: str | None = None) -> int:
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = usage_db_path()
    if not path.exists():
        return 0
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT calls FROM places_calls WHERE day = ?",
            (day,),
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()
    return int(row[0]) if row else 0
