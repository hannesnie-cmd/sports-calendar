"""Render included events to an iCalendar feed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from icalendar import Calendar
from icalendar import Event as VEvent

from .model import CANCELLED, Event

UID_DOMAIN = "hannes-sports-calendar"
BERLIN = ZoneInfo("Europe/Berlin")


def ascii_url(url: str) -> str:
    """Percent-encode non-ASCII characters (calendar apps reject raw umlauts in URLs)."""
    return quote(url, safe=":/?&=#%+~@!$'()*,;[]")


@dataclass
class Rendered:
    event: Event
    title: str
    description: str
    duration: timedelta


def calendar(items: list[Rendered], name: str, now: datetime, refresh_minutes: int = 30) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Hannes Sports Calendar//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", "Europe/Berlin")
    cal.add("refresh-interval", timedelta(minutes=refresh_minutes), parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", f"PT{refresh_minutes}M")

    for it in sorted(items, key=lambda i: (i.event.start, i.event.uid)):
        ev = it.event
        v = VEvent()
        v.add("uid", f"{ev.uid}@{UID_DOMAIN}")
        v.add("dtstamp", now)
        if ev.time_tbd:
            day = ev.start.astimezone(BERLIN).date()
            v.add("dtstart", day)
            v.add("dtend", day + timedelta(days=1))
        else:
            v.add("dtstart", ev.start)
            v.add("dtend", ev.start + it.duration)
        v.add("summary", it.title)
        v.add("description", it.description)
        location = ", ".join(x for x in (ev.venue, ev.city) if x)
        if location:
            v.add("location", location)
        if ev.link:
            v.add("url", ascii_url(ev.link))
        v.add("status", "CANCELLED" if ev.status == CANCELLED else "CONFIRMED")
        v.add("transp", "TRANSPARENT")       # sports never block your free/busy time
        v.add("categories", [ev.sport])
        cal.add_component(v)
    return cal.to_ical()
