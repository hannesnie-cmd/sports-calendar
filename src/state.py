"""Persistent build state: last good data per source unit, source health, sticky big games.

Lives in a directory that the workflow keeps on the gh-pages branch, so it
survives between runs. If a source fails, its last good data is used instead.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .model import Event

log = logging.getLogger("state")

SCHEMA = 1                     # bump when the cached event format changes
PRUNE_AFTER = timedelta(days=45)


def _safe(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key)


class State:
    def __init__(self, directory: Path, now: datetime):
        self.dir = Path(directory)
        self.now = now
        (self.dir / "units").mkdir(parents=True, exist_ok=True)
        self.health: dict[str, dict] = self._read("health.json", {})
        self.sticky: dict[str, dict] = self._read("sticky.json", {})
        self.last_build: dict = self._read("last_build.json", {})
        self.used: set[str] = set()
        self.failures: list[str] = []

    def _read(self, name: str, default):
        p = self.dir / name
        try:
            return json.loads(p.read_text()) if p.exists() else default
        except (OSError, ValueError):
            log.warning("could not read %s, starting fresh", p)
            return default

    def _write(self, name: str, data) -> None:
        (self.dir / name).write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True))

    # --- source units ------------------------------------------------------

    def _unit_path(self, key: str) -> Path:
        return self.dir / "units" / f"{_safe(key)}.json"

    def load(self, key: str) -> Any | None:
        p = self._unit_path(key)
        try:
            blob = json.loads(p.read_text())
        except (OSError, ValueError):
            return None
        if blob.get("schema") != SCHEMA:
            return None
        return blob["data"]

    def save(self, key: str, data: Any) -> None:
        blob = {"schema": SCHEMA, "key": key, "fetched_at": self.now.isoformat(), "data": data}
        self._unit_path(key).write_text(json.dumps(blob, ensure_ascii=False))

    def run(self, key: str, fetch: Callable[[], Any], events: bool = True) -> Any | None:
        """Fetch a unit; on failure (or a suspicious empty result) fall back to the last good data.

        For event units the return value is a list[Event]; otherwise raw JSON-able data.
        """
        self.used.add(key)
        cached = self.load(key)
        try:
            fresh = fetch()
            if events:
                fresh_json = [e.to_json() for e in fresh]
                if not fresh_json and cached and self._has_upcoming(cached):
                    raise RuntimeError("empty response, but last good data had upcoming events")
                self.save(key, fresh_json)
            else:
                self.save(key, fresh)
            self._ok(key)
            return fresh
        except Exception as e:  # noqa: BLE001 - any failure falls back to cached data
            self._fail(key, e)
            if cached is None:
                log.error("SOURCE FAILED %s: %s (no cached data)", key, e)
                return None
            log.error("SOURCE FAILED %s: %s (using data from last good fetch)", key, e)
            return [Event.from_json(d) for d in cached] if events else cached

    def _has_upcoming(self, cached: list[dict]) -> bool:
        return any(datetime.fromisoformat(d["start"]) > self.now for d in cached)

    def _ok(self, key: str) -> None:
        self.health[key] = {"last_success": self.now.isoformat(), "failing_since": None, "last_error": None}

    def _fail(self, key: str, err: Exception) -> None:
        h = self.health.setdefault(key, {"last_success": None, "failing_since": None, "last_error": None})
        h["failing_since"] = h.get("failing_since") or self.now.isoformat()
        h["last_error"] = str(err)[:300]
        self.failures.append(key)

    def stale_sources(self, max_age: timedelta) -> list[str]:
        """Units (used in this build) that have been failing for longer than max_age."""
        out = []
        for key in sorted(self.used):
            since = (self.health.get(key) or {}).get("failing_since")
            if since and self.now - datetime.fromisoformat(since) > max_age:
                out.append(key)
        return out

    # --- sticky big games --------------------------------------------------

    def sticky_reason(self, uid: str) -> str | None:
        return (self.sticky.get(uid) or {}).get("reason")

    def remember(self, uid: str, reason: str, start: datetime) -> None:
        self.sticky[uid] = {"reason": reason, "start": start.isoformat()}

    # --- persistence -------------------------------------------------------

    def finish(self, build_info: dict) -> None:
        cutoff = self.now - PRUNE_AFTER
        self.sticky = {u: v for u, v in self.sticky.items() if datetime.fromisoformat(v["start"]) > cutoff}
        for p in (self.dir / "units").glob("*.json"):
            if p.stat().st_mtime < cutoff.timestamp():
                p.unlink()
        self.health = {k: v for k, v in self.health.items() if k in self.used}
        self._write("health.json", self.health)
        self._write("sticky.json", self.sticky)
        self._write("last_build.json", build_info)
