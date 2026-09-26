"""Event titles and descriptions (with and without spoilers)."""

from __future__ import annotations

import re
from datetime import timedelta

from .filters import Inclusion, base_competition, soccer_rules
from .ics import ascii_url
from .model import CANCELLED, FINAL, POSTPONED, Event

SPORT_EMOJI = {"soccer": "⚽", "nfl": "🏈", "cfb": "🏈", "mlb": "⚾", "f1": "🏎️"}
EXTRA_EMOJI = {"running": "🏃", "marathon": "🏃", "boxing": "🥊", "tennis": "🎾",
               "cycling": "🚴", "golf": "⛳", "darts": "🎯"}
F1_PRACTICE = {"fp1", "fp2", "fp3"}
SMALL_WORDS = {"of", "the", "and"}


def _stage_text(slug: str | None) -> str | None:
    if not slug:
        return None
    return " ".join(w if w in SMALL_WORDS else w.capitalize() for w in slug.split("-"))


def label(ev: Event, rules: dict) -> str:
    """Short competition label for titles."""
    if ev.sport == "soccer":
        comps = soccer_rules(rules)
        if ev.competition in comps:
            return comps[ev.competition]["label"]
        base = base_competition(ev.competition)
        if base in comps:
            return f"{comps[base]['label']} Qualifying"
        return ev.competition_name
    if ev.sport in ("nfl", "cfb", "mlb"):
        default = rules.get(ev.sport, {}).get("label", ev.sport.upper())
        if ev.sport == "cfb":
            # CFB notes are mostly TV kickoff windows; only title games and the playoff name the round
            patterns = rules.get("cfb", {}).get("include_notes", [])
            return next((n for n in ev.notes if any(re.search(p, n) for p in patterns)), default)
        if ev.notes and ev.season_type == 3:
            return ev.notes[0]
        return default
    return ev.competition_name


def _emoji(ev: Event) -> str:
    return SPORT_EMOJI.get(ev.sport) or EXTRA_EMOJI.get(ev.sport.lower(), "🏆")


def _score_text(ev: Event) -> str | None:
    if ev.home_score is None or ev.away_score is None:
        return None
    text = f"{ev.home.name} {ev.home_score}–{ev.away_score} {ev.away.name}"
    detail = ev.status_detail or ""
    if ev.home_shootout and ev.away_shootout:
        text += f" ({ev.home_shootout}–{ev.away_shootout} pens)"
    elif "AET" in detail:
        text += " (a.e.t.)"
    return text


def title(ev: Event, inc: Inclusion, rules: dict, spoilers: bool = True) -> str:
    star = "⭐ " if inc.my_team else ""
    emoji = _emoji(ev)

    if ev.source == "extras":
        t = ev.title or "Event"
        known = [*SPORT_EMOJI.values(), *EXTRA_EMOJI.values(), "🏆"]
        return t if any(t.startswith(e) for e in known) else f"{emoji} {t}"

    if ev.sport == "f1":
        if spoilers and ev.results and ev.stage not in F1_PRACTICE:
            podium = " · ".join(f"{i}. {name}" for i, name in enumerate(ev.results, 1))
            return f"✅ {emoji} {ev.title}: {podium}"
        return f"{emoji} {ev.title} · {ev.info}"

    home = ev.home.name if ev.home else "TBD"
    away = ev.away.name if ev.away else "TBD"
    lab = label(ev, rules)
    if spoilers and ev.status == FINAL:
        score = _score_text(ev)
        if score:
            return f"✅ {star}{score} · {lab}"
    base = f"{star}{emoji} {home} vs {away} · {lab}"
    if ev.status == POSTPONED:
        return f"⏸️ Postponed: {base}"
    if ev.status == CANCELLED:
        return f"❌ Cancelled: {base}"
    if ev.time_tbd:
        return f"{base} (time TBC)"
    return base


def _round_text(ev: Event, rules: dict, matchday: int | None) -> str | None:
    if ev.sport == "soccer":
        comp = soccer_rules(rules).get(ev.competition) or {}
        if comp.get("matchday"):
            return f"Matchday {matchday}" if matchday else None
        text = ev.stage_name or _stage_text(ev.stage)
        # season names ("2026 Club Friendly", "2026-27 German Bundesliga") say nothing useful
        if not text or re.match(r"^\d{4}\b", text) or text == "Regular Season":
            return None
        return text
    if ev.sport in ("nfl", "cfb", "mlb"):
        if ev.season_type == 3 and ev.notes:
            return ev.notes[0]
        if ev.week and ev.sport != "mlb":
            return f"Week {ev.week}"
        return None
    if ev.sport == "f1":
        return f"{ev.stage_name}, {ev.info}"
    return None


def description(ev: Event, inc: Inclusion, rules: dict, tv: list[str],
                matchday: int | None = None) -> str:
    first = [label(ev, rules) if ev.sport != "f1" else "Formula 1"]
    if ev.source == "extras":
        first = [ev.competition_name] if ev.competition_name and ev.competition_name != "extra" else []
    rnd = _round_text(ev, rules, matchday)
    if rnd and rnd not in first:
        first.append(rnd)
    place = ", ".join(x for x in (ev.venue, ev.city) if x)
    if place:
        first.append(place)
    lines = [", ".join(first)] if first else []
    if ev.time_tbd:
        window = next((n for n in ev.notes if n not in first), None) if ev.sport == "cfb" else None
        lines.append(f"Kickoff time not confirmed yet ({window})." if window else "Kickoff time not confirmed yet.")
    lines += tv
    if ev.source == "extras" and ev.info:
        lines.append(ev.info)
    if not inc.my_team and ev.source != "extras" and ev.sport != "f1":
        lines.append(f"Why: {inc.reason}")
    if ev.link:
        lines.append(f"Link: {ascii_url(ev.link)}")
    return "\n".join(lines)


def duration(ev: Event, rules: dict) -> timedelta:
    d = rules.get("durations_minutes", {})
    if ev.end:
        return ev.end - ev.start
    if ev.sport == "f1":
        return timedelta(minutes=d.get("f1_race", 120) if ev.stage == "race" else d.get("f1_session", 60))
    return timedelta(minutes=d.get(ev.sport, 120))
