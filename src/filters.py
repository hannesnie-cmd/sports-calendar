"""Which events go into the calendar, and why.

Pure functions over normalized events plus a Context of tables/rankings,
driven by config/teams.yaml and config/rules.yaml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from .model import CANCELLED, FINAL, POSTPONED, Event

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class Context:
    """Data the rules need besides the events themselves."""
    my_team_ids: dict[str, str] = field(default_factory=dict)       # "sport:espn id" -> my display name
    standings: dict[str, list[dict]] = field(default_factory=dict)   # league slug -> table rows
    ap_top: list[str] | None = None                                  # AP poll team ids, best first
    matchdays: dict[str, int] = field(default_factory=dict)          # event uid -> matchday

    def league_team_ids(self, league: str) -> set[str]:
        return {r["team_id"] for r in self.standings.get(league, [])}


@dataclass
class Inclusion:
    reason: str
    my_team: bool = False


def soccer_rules(rules: dict) -> dict[str, dict]:
    return {c["slug"]: c for c in rules.get("soccer", [])}


def base_competition(slug: str) -> str:
    """ESPN lists qualifying rounds as '<slug>_qual' (e.g. uefa.europa.conf_qual)."""
    return slug.removesuffix("_qual")


# --- tags --------------------------------------------------------------------

def tags_for(ev: Event, rules: dict) -> set[str]:
    """Tags used by the rights map (and NFL rules)."""
    tags: set[str] = set()
    if ev.sport in ("nfl", "cfb", "mlb") and ev.season_type == 3:
        tags.add("postseason")
    if ev.sport == "nfl" and not ev.time_tbd:
        pt = rules["nfl"]["primetime"]
        local = ev.start.astimezone(ZoneInfo(pt["timezone"]))
        if WEEKDAYS[local.weekday()] in pt["weekdays"] and local.hour >= pt["min_hour"]:
            tags.add("primetime")
    return tags


# --- matchdays ---------------------------------------------------------------

def compute_matchdays(events: list[Event], standings: dict[str, list[dict]],
                      leagues: set[str]) -> dict[str, int]:
    """Matchday numbers for league games, from the table's games played.

    matchday = games played by the home team now
             - its completed games on/after this game
             + its not-yet-completed games before this game + 1
    Needs every game of the home team between this game and now, which the
    month scoreboards covering the window provide.
    """
    out: dict[str, int] = {}
    for league in leagues:
        table = {r["team_id"]: r["games_played"] for r in standings.get(league, [])}
        if not table:
            continue
        games = [e for e in events if e.competition == league and e.status not in (POSTPONED, CANCELLED)]
        for ev in games:
            team = ev.home.id if ev.home else None
            if team not in table:
                continue
            played = table[team]
            mine = [g for g in games if team in g.team_ids()]
            done_after = sum(1 for g in mine if g.status == FINAL and g.start >= ev.start)
            open_before = sum(1 for g in mine if g.status != FINAL and g.start < ev.start)
            out[ev.uid] = played - done_after + open_before + 1
    return out


# --- rules -------------------------------------------------------------------

def _stage_label(ev: Event) -> str:
    return ev.stage_name or (ev.stage or "").replace("-", " ").title()


def _soccer_big_game(ev: Event, comp: dict, rules: dict, ctx: Context) -> str | None:
    rule = comp.get("rule", "none")
    label = comp.get("label", ev.competition_name)
    ids = ev.team_ids()
    if len(ids) < 2:
        return None
    lists = rules.get("lists", {})

    if rule == "table_clash":
        md = ctx.matchdays.get(ev.uid)
        table = ctx.standings.get(ev.competition, [])
        if md is None and table:
            md = max(r["games_played"] for r in table) + 1
        early = md is not None and md < comp.get("table_from_matchday", 6)
        if early or not table:
            if ids <= set(comp.get("big_clubs", [])):
                return f"{label}: big clubs (before matchday {comp.get('table_from_matchday', 6)})"
            return None
        top = {r["team_id"]: r["rank"] for r in table if r["rank"] <= comp.get("top_n", 6)}
        if ids <= set(top):
            ranks = sorted(top[i] for i in ids)
            return f"{label}: top-{comp.get('top_n', 6)} clash (#{ranks[0]} vs #{ranks[1]})"
        return None

    knockout = ev.stage in comp.get("knockout_stages", [])
    if rule == "elite_or_knockout":
        if knockout:
            return f"{label}: knockout ({_stage_label(ev)})"
        if ids <= set(lists.get("elite_clubs", [])):
            return f"{label}: elite clubs"
    elif rule == "knockout":
        if knockout:
            return f"{label}: knockout ({_stage_label(ev)})"
    elif rule == "nations_clash":
        if ids <= set(lists.get("top_nations", [])):
            return f"{label}: top nations"
    elif rule == "tournament":
        if knockout:
            return f"{label}: knockout ({_stage_label(ev)})"
        if ids <= set(lists.get("top_nations", [])):
            return f"{label}: top nations"
    return None


def _any_match(patterns: list[str], notes: list[str]) -> str | None:
    for note in notes:
        for p in patterns:
            if re.search(p, note):
                return note
    return None


def big_game_reason(ev: Event, rules: dict, ctx: Context, tags: set[str]) -> str | None:
    if ev.sport == "soccer":
        comp = soccer_rules(rules).get(ev.competition)
        return _soccer_big_game(ev, comp, rules, ctx) if comp else None
    if ev.sport == "nfl":
        cfg = rules["nfl"]
        if _any_match(cfg.get("exclude_notes", []), ev.notes):
            return None
        if cfg.get("postseason") and "postseason" in tags:
            return "NFL postseason"
        if "primetime" in tags:
            day = ev.start.astimezone(ZoneInfo(cfg["primetime"]["timezone"])).strftime("%A")
            return f"NFL primetime ({day} night)"
        return None
    if ev.sport == "cfb":
        cfg = rules["cfb"]
        note = _any_match(cfg.get("include_notes", []), ev.notes)
        if note:
            return f"College football: {note}"
        if ctx.ap_top is not None:
            top = ctx.ap_top[: cfg.get("ap_top_n", 15)]
            ids = ev.team_ids()
            if len(ids) == 2 and ids <= set(top):
                ranks = sorted(top.index(i) + 1 for i in ids)
                return f"College football: AP top {cfg.get('ap_top_n', 15)} (#{ranks[0]} vs #{ranks[1]})"
        return None
    if ev.sport == "mlb":
        if "postseason" in tags:
            note = _any_match(rules["mlb"].get("include_postseason_notes", []), ev.notes)
            if note:
                return f"MLB postseason: {note}"
        return None
    return None


def classify(ev: Event, rules: dict, teams_cfg: dict, ctx: Context) -> Inclusion | None:
    """Why an event belongs in the calendar, or None if it doesn't."""
    if ev.source == "extras":
        return Inclusion("extra")
    if ev.sport == "f1":
        return Inclusion("Formula 1") if f1_session_enabled(ev, teams_cfg) else None
    if ev.competition in set(teams_cfg.get("exclude_competitions") or []):
        return None
    mine = [ctx.my_team_ids[k] for k in (f"{ev.sport}:{i}" for i in ev.team_ids()) if k in ctx.my_team_ids]
    if mine:
        return Inclusion(f"my team: {', '.join(sorted(mine))}", my_team=True)
    reason = big_game_reason(ev, rules, ctx, tags_for(ev, rules))
    return Inclusion(reason) if reason else None


def f1_session_enabled(ev: Event, teams_cfg: dict) -> bool:
    f1 = teams_cfg.get("f1") or {}
    if not f1.get("enabled", True):
        return False
    sessions = f1.get("sessions") or {}
    key = "practice" if ev.stage in ("fp1", "fp2", "fp3") else ev.stage
    return bool(sessions.get(key, False))


# --- volume guardrail ----------------------------------------------------------

def weekly_volume(included: list[tuple[Event, Inclusion]], tz: str = "Europe/Berlin") -> dict[str, int]:
    """Neutral (non-team, non-F1, non-extra) events per ISO week."""
    counts: dict[str, int] = {}
    for ev, inc in included:
        if inc.my_team or ev.sport == "f1" or ev.source == "extras":
            continue
        y, w, _ = ev.start.astimezone(ZoneInfo(tz)).isocalendar()
        key = f"{y}-W{w:02d}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def in_window(ev: Event, start: datetime, end: datetime) -> bool:
    ev_end = ev.end or ev.start
    return ev_end >= start and ev.start <= end
