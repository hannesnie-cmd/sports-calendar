"""TV channel lines: US from ESPN live data, UK/DE/NL from config/rights.yaml."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from .filters import WEEKDAYS, Context, base_competition
from .model import Event

LANG_ORDER = ["EN", "DE", "NL"]


def rights_key(ev: Event) -> str:
    return base_competition(ev.competition) if ev.sport == "soccer" else ev.sport


def _matches(when: dict | None, ev: Event, tz: ZoneInfo, ctx: Context, tags: set[str]) -> bool:
    if not when:
        return True
    local = ev.start.astimezone(tz)
    hhmm = local.strftime("%H:%M")
    ids = ev.team_ids()
    if ev.time_tbd and ({"weekdays", "times", "after"} & set(when)):
        return False     # placeholder date/time: slot rules can't be trusted
    if "weekdays" in when and WEEKDAYS[local.weekday()] not in when["weekdays"]:
        return False
    if "times" in when and hhmm not in [str(t) for t in when["times"]]:
        return False
    if "after" in when and hhmm < str(when["after"]):
        return False
    if "stages" in when and ev.stage not in when["stages"]:
        return False
    if "teams" in when and not ids & set(when["teams"]):
        return False
    if "home_team" in when and not (ev.home and ev.home.id in when["home_team"]):
        return False
    if "away_team" in when and not (ev.away and ev.away.id in when["away_team"]):
        return False
    if "league_teams" in when and not ids & ctx.league_team_ids(when["league_teams"]):
        return False
    if "tags" in when and not tags & set(when["tags"]):
        return False
    if "event_ids" in when and ev.uid.removeprefix("espn-") not in [str(i) for i in when["event_ids"]]:
        return False
    return True


def resolve(ev: Event, rights: dict, country: str, ctx: Context, tags: set[str]) -> dict | None:
    """The matching rights rule for one country, merged with its block's defaults."""
    block = (rights.get("competitions", {}).get(rights_key(ev)) or {}).get(country)
    if not block:
        return None
    tz = ZoneInfo(rights["countries"][country]["timezone"])
    for rule in block.get("rules", []):
        if _matches(rule.get("when"), ev, tz, ctx, tags):
            return {
                "channels": list(rule.get("channels") or []),
                "confidence": rule.get("confidence", block.get("confidence", "medium")),
                "source": rule.get("source", block.get("source")),
                "checked": rule.get("checked", block.get("checked")),
            }
    return None


def _fmt(rule: dict) -> str:
    q = "?" if rule["confidence"] == "low" else ""
    return ", ".join(f"{c}{q}" for c in rule["channels"])


def tv_lines(ev: Event, rights: dict, ctx: Context, tags: set[str]) -> list[str]:
    """Description lines like '📺 EN: ESPN+ (live data) | Sky Sports (rights map)'."""
    if ev.source == "extras":
        return [f"📺 {lang}: {ev.tv[lang]} (manual)" for lang in LANG_ORDER if ev.tv.get(lang)]

    parts: dict[str, list[str]] = {lang: [] for lang in LANG_ORDER}
    if ev.us_broadcasts:
        parts["EN"].append(f"{', '.join(ev.us_broadcasts)} (live data)")
    for country, info in rights.get("countries", {}).items():
        rule = resolve(ev, rights, country, ctx, tags)
        if rule and rule["channels"]:
            parts[info["label"]].append(f"{_fmt(rule)} (rights map)")
    return [f"📺 {lang}: {' | '.join(parts[lang]) if parts[lang] else '–'}" for lang in LANG_ORDER]
