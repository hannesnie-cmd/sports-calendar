"""The normalized event format every adapter returns."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

# Event.status values
SCHEDULED = "scheduled"
IN_PROGRESS = "in_progress"
FINAL = "final"
POSTPONED = "postponed"
CANCELLED = "cancelled"


@dataclass
class Team:
    id: str | None
    name: str
    abbr: str | None = None


@dataclass
class Event:
    uid: str                      # stable id, e.g. "espn-401884790" or "f1-2026-17-qualifying"
    source: str                   # espn | jolpica | extras
    sport: str                    # soccer | nfl | cfb | mlb | f1 | other
    competition: str              # ESPN league slug, "nfl", "cfb", "mlb", "f1" or "extra"
    competition_name: str         # e.g. "German Bundesliga"
    start: datetime               # timezone-aware UTC
    time_tbd: bool = False        # kickoff time not fixed yet
    home: Team | None = None
    away: Team | None = None
    title: str | None = None      # for events without two teams (F1 sessions, extras)
    stage: str | None = None      # ESPN stage slug ("league-phase", "round-of-16") or F1 session key
    stage_name: str | None = None
    notes: list[str] = field(default_factory=list)   # ESPN notes (US sports: round names)
    week: int | None = None
    season_type: int | None = None  # ESPN: 2 regular season, 3 postseason
    status: str = SCHEDULED
    status_detail: str | None = None  # "FT", "AET", "FT-Pens"
    home_score: str | None = None
    away_score: str | None = None
    home_shootout: str | None = None
    away_shootout: str | None = None
    results: list[str] = field(default_factory=list)  # F1: ["Verstappen", "Norris", "Leclerc"]
    venue: str | None = None
    city: str | None = None
    link: str | None = None
    us_broadcasts: list[str] = field(default_factory=list)
    end: datetime | None = None   # only extras set this; others use the duration rules
    tv: dict[str, str] = field(default_factory=dict)  # extras: fixed TV text per language
    info: str | None = None       # extras: free-text notes; F1: Grand Prix name

    def team_ids(self) -> set[str]:
        return {t.id for t in (self.home, self.away) if t and t.id}

    def to_json(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat() if self.end else None
        return d

    @classmethod
    def from_json(cls, d: dict) -> Event:
        d = dict(d)
        d["start"] = datetime.fromisoformat(d["start"])
        d["end"] = datetime.fromisoformat(d["end"]) if d.get("end") else None
        for side in ("home", "away"):
            if d.get(side):
                d[side] = Team(**d[side])
        return cls(**d)
