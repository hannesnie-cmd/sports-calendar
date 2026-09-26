"""Hand-written one-off events from config/extras.yaml."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..model import Event

BERLIN = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")


def _when(value) -> tuple[datetime, bool]:
    """(UTC datetime, all_day) from a YAML value; naive times are Berlin local time."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return datetime.combine(value, time(12), BERLIN).astimezone(UTC), True
    else:
        text = str(value).strip()
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), time(12), BERLIN).astimezone(UTC), True
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BERLIN)
    return dt.astimezone(UTC), False


def load(cfg: dict) -> list[Event]:
    events = []
    for item in cfg.get("extras") or []:
        start, all_day = _when(item["start"])
        end = _when(item["end"])[0] if item.get("end") else start + timedelta(hours=2)
        events.append(Event(
            uid=f"extra-{item['id']}",
            source="extras",
            sport=str(item.get("sport") or "other"),
            competition="extra",
            competition_name=str(item.get("competition") or ""),
            start=start,
            end=None if all_day else end,
            time_tbd=all_day,
            title=str(item["title"]),
            link=item.get("link"),
            tv={str(k).upper(): str(v) for k, v in (item.get("tv") or {}).items()},
            info=item.get("notes"),
            venue=item.get("venue"),
        ))
    return events
