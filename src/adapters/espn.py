"""ESPN public site API (unofficial): schedules, scores, status, tables, rankings, US TV.

Endpoints verified live on 2026-09-26:
  site/v2/sports/soccer/all/teams/{id}/schedule[?fixture=true]   every competition of a club/nation
  site/v2/sports/{path}/teams/{id}/schedule[?seasontype=3]       NFL/MLB team schedule (+ postseason)
  site/v2/sports/{path}/{league}/scoreboard?dates=YYYYMM         whole month (date *ranges* return 400)
  site/v2/sports/football/college-football/scoreboard?seasontype=S&week=W&groups=80
  apis/v2/sports/soccer/{league}/standings                       league table
  site/v2/sports/football/college-football/rankings              AP poll
  site/v2/sports/racing/f1/scoreboard?dates=YYYYMMDD             F1 weekend: sessions, US TV, results
"""

from __future__ import annotations

import re
from datetime import datetime

from ..fetch import get_json
from ..model import CANCELLED, FINAL, IN_PROGRESS, POSTPONED, SCHEDULED, Event, Team

SITE = "https://site.api.espn.com/apis/site/v2/sports"
V2 = "https://site.api.espn.com/apis/v2/sports"

SPORT_PATHS = {
    "soccer": "soccer",
    "nfl": "football/nfl",
    "cfb": "football/college-football",
    "mlb": "baseball/mlb",
}
US_COMPETITION = {"nfl": "nfl", "cfb": "cfb", "mlb": "mlb"}


# --- parsing -----------------------------------------------------------------

def _parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _slug(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _score(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("displayValue", value.get("value"))
    if value is None or value == "":
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def _shootout(competitor: dict) -> str | None:
    """Scoreboards put shootoutScore on the competitor, team schedules inside `score`."""
    value = competitor.get("shootoutScore")
    if value is None and isinstance(competitor.get("score"), dict):
        value = competitor["score"].get("shootoutScore")
    return _score(value)


def _status(status: dict) -> tuple[str, str | None]:
    t = (status or {}).get("type", {})
    name = t.get("name", "")
    if "POSTPONED" in name or ("DELAYED" in name and t.get("state") == "pre"):
        return POSTPONED, name
    if "CANCELED" in name or "CANCELLED" in name or "ABANDONED" in name:
        return CANCELLED, name
    state = t.get("state")
    if state == "post" and t.get("completed"):
        return FINAL, name
    if state == "in" or (state == "post" and not t.get("completed")):
        return IN_PROGRESS, name
    return SCHEDULED, name


def _broadcasts(comp: dict) -> list[str]:
    names: list[str] = []
    for b in comp.get("broadcasts") or []:
        if b.get("region") not in (None, "us"):
            continue
        for n in b.get("names") or []:
            names.append(n)
        media = (b.get("media") or {}).get("shortName")
        if media:
            names.append(media)
    for b in comp.get("geoBroadcasts") or []:
        media = (b.get("media") or {}).get("shortName")
        if media and b.get("region", "us") == "us":
            names.append(media)
    seen: list[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def _team(c: dict, name_overrides: dict[str, str]) -> Team:
    t = c.get("team") or {}
    tid = str(t["id"]) if t.get("id") not in (None, "", "-1", "-2") else None
    name = name_overrides.get(tid or "", t.get("shortDisplayName") or t.get("displayName") or "TBD")
    if (t.get("abbreviation") or "").upper() == "TBD" or name.upper() == "TBD":
        tid, name = None, "TBD"
    rank = (c.get("curatedRank") or {}).get("current")
    team = Team(id=tid, name=name, abbr=t.get("abbreviation"))
    if isinstance(rank, int) and 0 < rank < 99:
        team.name = f"#{rank} {team.name}"
    return team


def parse_event(raw: dict, sport: str, league: str | None = None,
                name_overrides: dict[str, str] | None = None) -> Event:
    """Parse one ESPN event from either a scoreboard or a team-schedule response."""
    name_overrides = name_overrides or {}
    comp = (raw.get("competitions") or [{}])[0]
    league_info = raw.get("league") or {}
    slug = league_info.get("slug") or league or US_COMPETITION.get(sport)
    league_name = league_info.get("name") or (raw.get("season") or {}).get("displayName") or slug

    season = raw.get("season") or {}
    season_type_info = raw.get("seasonType") or {}
    stage = season.get("slug") if isinstance(season.get("slug"), str) else None
    stage_name = season_type_info.get("name")
    if not stage:
        stage = _slug(stage_name)
    season_type = None
    if sport in US_COMPETITION:
        st = season.get("type") if isinstance(season.get("type"), int) else season_type_info.get("type")
        season_type = int(st) if st is not None else None

    home = away = None
    home_c = away_c = {}
    for c in comp.get("competitors") or []:
        if c.get("homeAway") == "home":
            home, home_c = _team(c, name_overrides), c
        else:
            away, away_c = _team(c, name_overrides), c

    status_raw = comp.get("status") or raw.get("status") or {}
    status, detail = _status(status_raw)

    time_valid = comp.get("timeValid", raw.get("timeValid"))
    venue = comp.get("venue") or {}
    link = None
    for l in raw.get("links") or []:
        rel = l.get("rel") or []
        if "summary" in rel and "desktop" in rel:
            link = l.get("href")
            break

    ev = Event(
        uid=f"espn-{raw['id']}",
        source="espn",
        sport=sport,
        competition=slug,
        competition_name=league_name,
        start=_parse_time(raw["date"]),
        time_tbd=time_valid is False,
        home=home,
        away=away,
        stage=stage,
        stage_name=stage_name,
        notes=[n["headline"] for n in comp.get("notes") or [] if n.get("headline")],
        week=(raw.get("week") or {}).get("number"),
        season_type=season_type,
        status=status,
        status_detail=detail,
        venue=venue.get("fullName"),
        city=(venue.get("address") or {}).get("city"),
        link=link,
        us_broadcasts=_broadcasts(comp),
    )
    if status in (FINAL, IN_PROGRESS):
        ev.home_score = _score(home_c.get("score"))
        ev.away_score = _score(away_c.get("score"))
        ev.home_shootout = _shootout(home_c)
        ev.away_shootout = _shootout(away_c)
    return ev


# --- endpoints ---------------------------------------------------------------

def team_schedule(sport: str, team_id: str, name_overrides=None) -> list[Event]:
    """Every game ESPN lists for one team this season (past and upcoming)."""
    path = SPORT_PATHS[sport]
    events: dict[str, Event] = {}
    if sport == "soccer":
        urls = [(f"{SITE}/soccer/all/teams/{team_id}/schedule", {}),
                (f"{SITE}/soccer/all/teams/{team_id}/schedule", {"fixture": "true"})]
    else:
        urls = [(f"{SITE}/{path}/teams/{team_id}/schedule", {}),
                (f"{SITE}/{path}/teams/{team_id}/schedule", {"seasontype": "3"})]
    for url, params in urls:
        data = get_json(url, params)
        for raw in data.get("events") or []:
            ev = parse_event(raw, sport, name_overrides=name_overrides)
            events[ev.uid] = ev
    return list(events.values())


def scoreboard_month(sport: str, league: str | None, yyyymm: str, name_overrides=None,
                     postseason_only: bool = False) -> list[Event]:
    path = SPORT_PATHS[sport]
    url = f"{SITE}/{path}/{league}/scoreboard" if sport == "soccer" else f"{SITE}/{path}/scoreboard"
    data = get_json(url, {"dates": yyyymm, "limit": "1000"})
    events = [parse_event(raw, sport, league, name_overrides) for raw in data.get("events") or []]
    if postseason_only:
        events = [e for e in events if e.season_type == 3]
    return events


def cfb_calendar() -> list[dict]:
    """College football weeks: [{season_type, week, start, end}]."""
    data = get_json(f"{SITE}/football/college-football/scoreboard", {"groups": "80"})
    weeks = []
    for block in (data.get("leagues") or [{}])[0].get("calendar") or []:
        for entry in block.get("entries") or []:
            weeks.append({
                "season_type": int(block["value"]),
                "week": int(entry["value"]),
                "start": _parse_time(entry["startDate"]),
                "end": _parse_time(entry["endDate"]),
            })
    return weeks


def cfb_week(season_type: int, week: int, name_overrides=None) -> list[Event]:
    data = get_json(f"{SITE}/football/college-football/scoreboard",
                    {"seasontype": str(season_type), "week": str(week), "groups": "80", "limit": "400"})
    return [parse_event(raw, "cfb", None, name_overrides) for raw in data.get("events") or []]


def standings(league: str) -> list[dict]:
    """League table: [{team_id, name, rank, games_played}] sorted by rank."""
    data = get_json(f"{V2}/soccer/{league}/standings")
    rows = []
    for group in data.get("children") or []:
        for entry in (group.get("standings") or {}).get("entries") or []:
            stats = {s.get("name"): s.get("value") for s in entry.get("stats") or []}
            rows.append({
                "team_id": str(entry["team"]["id"]),
                "name": entry["team"].get("shortDisplayName"),
                "rank": int(stats.get("rank") or 0),
                "games_played": int(stats.get("gamesPlayed") or 0),
            })
    return sorted(rows, key=lambda r: r["rank"])


def ap_top(n: int) -> list[str]:
    """Team ids of the current AP poll, best first (top n)."""
    data = get_json(f"{SITE}/football/college-football/rankings")
    for poll in data.get("rankings") or []:
        if poll.get("type") == "ap":
            ranks = sorted(poll.get("ranks") or [], key=lambda r: r.get("current", 99))
            return [str(r["team"]["id"]) for r in ranks[:n]]
    raise ValueError("AP poll not found in rankings response")


F1_SESSIONS = {"FP1": "fp1", "FP2": "fp2", "FP3": "fp3", "SS": "sprint_qualifying",
               "SR": "sprint", "Qual": "qualifying", "Race": "race"}


def f1_weekend(yyyymmdd: str) -> dict:
    """ESPN's view of one F1 weekend: {link, sessions: {key: {start, us_broadcasts, top3, final}}}."""
    data = get_json(f"{SITE}/racing/f1/scoreboard", {"dates": yyyymmdd})
    events = data.get("events") or []
    if not events:
        return {"link": None, "sessions": {}}
    ev = events[0]
    sessions = {}
    for comp in ev.get("competitions") or []:
        key = F1_SESSIONS.get((comp.get("type") or {}).get("abbreviation"))
        if not key:
            continue
        status, _ = _status(comp.get("status") or {})
        order = sorted((c for c in comp.get("competitors") or [] if c.get("order")), key=lambda c: c["order"])
        top3 = []
        for c in order[:3]:
            short = (c.get("athlete") or {}).get("shortName") or ""
            top3.append(short.split(". ", 1)[-1])
        sessions[key] = {
            "start": comp.get("date"),
            "us_broadcasts": _broadcasts(comp),
            "top3": top3 if status == FINAL else [],
        }
    link = next((l.get("href") for l in ev.get("links") or [] if "/race/" in (l.get("href") or "")), None)
    return {"link": link, "sessions": sessions}
