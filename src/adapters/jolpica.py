"""Jolpica F1 API (Ergast successor): schedule, session times, results.

Endpoints verified live on 2026-09-26:
  /ergast/f1/{season}/races/                 calendar with FirstPractice/SecondPractice/ThirdPractice/
                                             SprintQualifying/Sprint/Qualifying and race date+time
  /ergast/f1/{season}/{round}/results/       race classification
  /ergast/f1/{season}/{round}/qualifying/    qualifying classification
  /ergast/f1/{season}/{round}/sprint/        sprint classification
Sprint qualifying results are not available (400); they come from ESPN instead.
"""

from __future__ import annotations

from datetime import datetime

from ..fetch import FetchError, get_json
from ..model import SCHEDULED, Event

BASE = "https://api.jolpi.ca/ergast/f1"

SESSION_FIELDS = {
    "FirstPractice": "fp1",
    "SecondPractice": "fp2",
    "ThirdPractice": "fp3",
    "SprintQualifying": "sprint_qualifying",
    "Sprint": "sprint",
    "Qualifying": "qualifying",
}
SESSION_LABELS = {
    "fp1": "FP1", "fp2": "FP2", "fp3": "FP3",
    "sprint_qualifying": "Sprint Qualifying", "sprint": "Sprint",
    "qualifying": "Qualifying", "race": "Race",
}
RESULT_PATHS = {"race": "results", "qualifying": "qualifying", "sprint": "sprint"}
RESULT_KEYS = {"race": "Results", "qualifying": "QualifyingResults", "sprint": "SprintResults"}


def _dt(date: str, time: str | None) -> datetime:
    return datetime.fromisoformat(f"{date}T{(time or '00:00:00Z').replace('Z', '+00:00')}")


def schedule(season: int) -> list[Event]:
    """One Event per session of every Grand Prix in the season."""
    data = get_json(f"{BASE}/{season}/races/", {"limit": "100"})
    events = []
    for race in data["MRData"]["RaceTable"]["Races"]:
        rnd = int(race["round"])
        loc = race["Circuit"].get("Location") or {}
        sessions = {key: race[f] for f, key in SESSION_FIELDS.items() if race.get(f)}
        sessions["race"] = {"date": race["date"], "time": race.get("time")}
        for key, when in sessions.items():
            events.append(Event(
                uid=f"f1-{season}-{rnd}-{key}",
                source="jolpica",
                sport="f1",
                competition="f1",
                competition_name="Formula 1",
                start=_dt(when["date"], when.get("time")),
                time_tbd=not when.get("time"),
                title=SESSION_LABELS[key],
                stage=key,
                stage_name=f"Round {rnd}",
                status=SCHEDULED,
                venue=race["Circuit"].get("circuitName"),
                city=", ".join(x for x in (loc.get("locality"), loc.get("country")) if x) or None,
                link=race.get("url"),
                info=race["raceName"],
            ))
    return events


def round_results(season: int, rnd: int) -> dict[str, list[str]]:
    """Top-3 family names per finished session: {"race": [...], "qualifying": [...], "sprint": [...]}."""
    out: dict[str, list[str]] = {}
    for key, path in RESULT_PATHS.items():
        try:
            data = get_json(f"{BASE}/{season}/{rnd}/{path}/")
        except FetchError:
            if key == "sprint":      # no sprint that weekend
                continue
            raise
        races = data["MRData"]["RaceTable"]["Races"]
        if not races:
            continue
        rows = sorted(races[0].get(RESULT_KEYS[key]) or [], key=lambda r: int(r["position"]))
        if rows:
            out[key] = [r["Driver"]["familyName"] for r in rows[:3]]
    return out
