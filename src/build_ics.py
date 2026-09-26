"""Build calendar.ics and calendar-nospoilers.ics.

    python -m src.build_ics --out site --state site/state

Each source call is a "unit" with its own last-good cache (see state.py), so one
failing API never removes that sport's events from the feeds.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from .adapters import espn, extras, jolpica
from .filters import (Context, Inclusion, classify, compute_matchdays, in_window,
                      tags_for, weekly_volume)
from .formatting import description, duration, title
from .ics import Rendered, calendar
from .model import CANCELLED, FINAL, IN_PROGRESS, POSTPONED, SCHEDULED, Event
from .state import State
from .tv import tv_lines

log = logging.getLogger("build")

STATUS_RANK = {SCHEDULED: 0, POSTPONED: 1, CANCELLED: 1, IN_PROGRESS: 2, FINAL: 3}
EMPTY = (None, "", [], {})
STALE_AFTER = timedelta(hours=24)
MIN_KEEP_RATIO = 0.5    # refuse to publish if the feed shrinks below this while a source failed


def load_config(config_dir: Path) -> dict:
    cfg = {}
    for name in ("teams", "rules", "rights", "extras"):
        with open(config_dir / f"{name}.yaml", encoding="utf-8") as f:
            cfg[name] = yaml.safe_load(f) or {}
    return cfg


def merge(old: Event | None, new: Event) -> Event:
    """Combine two views of the same match (team schedule + scoreboard)."""
    if old is None:
        return new
    base, other = (new, old) if STATUS_RANK[new.status] >= STATUS_RANK[old.status] else (old, new)
    for f in fields(Event):
        if getattr(base, f.name) in EMPTY and getattr(other, f.name) not in EMPTY:
            setattr(base, f.name, getattr(other, f.name))
    return base


def months(start: datetime, end: datetime) -> list[str]:
    out, cur = [], start.replace(day=1)
    while cur <= end:
        out.append(cur.strftime("%Y%m"))
        cur = (cur + timedelta(days=32)).replace(day=1)
    return out


class Collector:
    def __init__(self):
        self.events: dict[str, Event] = {}

    def add(self, evs: list[Event] | None) -> None:
        for e in evs or []:
            self.events[e.uid] = merge(self.events.get(e.uid), e)


def collect(cfg: dict, state: State, now: datetime, w_start: datetime, w_end: datetime):
    teams_cfg, rules = cfg["teams"], cfg["rules"]
    names = {str(k): v for k, v in (teams_cfg.get("name_overrides") or {}).items()}
    col = Collector()
    standings: dict[str, list[dict]] = {}
    ap_top = None
    month_keys = months(w_start, w_end)

    # A) my teams: full team schedules cover every competition
    for t in teams_cfg.get("teams", []):
        sport, tid = t["sport"], str(t["espn_id"])
        col.add(state.run(f"espn/team/{sport}/{tid}",
                          lambda s=sport, i=tid: espn.team_schedule(s, i, names)))

    # B) soccer competitions with big-game rules or matchday numbers
    for comp in rules.get("soccer", []):
        slug, rule = comp["slug"], comp.get("rule", "none")
        if rule == "none" and not comp.get("matchday"):
            continue
        for m in month_keys:
            col.add(state.run(f"espn/sb/{slug}/{m}",
                              lambda s=slug, m=m: espn.scoreboard_month("soccer", s, m, names)))
        if rule == "table_clash" or comp.get("matchday"):
            standings[slug] = state.run(f"espn/standings/{slug}",
                                        lambda s=slug: espn.standings(s), events=False) or []

    # NFL and MLB (postseason) by month
    for m in month_keys:
        col.add(state.run(f"espn/sb/nfl/{m}", lambda m=m: espn.scoreboard_month("nfl", None, m, names)))
        col.add(state.run(f"espn/sb/mlb/{m}",
                          lambda m=m: espn.scoreboard_month("mlb", None, m, names, postseason_only=True)))

    # College football by week, plus the AP poll
    weeks = state.run("espn/cfb/calendar", lambda: [
        {**w, "start": w["start"].isoformat(), "end": w["end"].isoformat()} for w in espn.cfb_calendar()
    ], events=False) or []
    for w in weeks:
        if datetime.fromisoformat(w["end"]) >= w_start and datetime.fromisoformat(w["start"]) <= w_end:
            st, wk = w["season_type"], w["week"]
            col.add(state.run(f"espn/cfb/{st}/{wk}", lambda st=st, wk=wk: espn.cfb_week(st, wk, names)))
    ap_top = state.run("espn/cfb/ap", lambda: espn.ap_top(25), events=False)

    # F1: Jolpica schedule + results, ESPN for US TV and sprint-qualifying results
    if (teams_cfg.get("f1") or {}).get("enabled", True):
        for season in sorted({w_start.year, w_end.year}):
            sessions = state.run(f"jolpica/schedule/{season}", lambda y=season: jolpica.schedule(y)) or []
            by_round: dict[int, list[Event]] = {}
            for s in sessions:
                if in_window(s, w_start, w_end):
                    by_round.setdefault(int(s.uid.split("-")[2]), []).append(s)
            for rnd, evs in sorted(by_round.items()):
                results = {}
                if any(e.start <= now for e in evs):
                    results = state.run(f"jolpica/results/{season}/{rnd}",
                                        lambda y=season, r=rnd: jolpica.round_results(y, r), events=False) or {}
                race_day = max(e.start for e in evs).strftime("%Y%m%d")
                weekend = state.run(f"espn/f1/{race_day}",
                                    lambda d=race_day: espn.f1_weekend(d), events=False) or {}
                for e in evs:
                    info = (weekend.get("sessions") or {}).get(e.stage) or {}
                    e.results = results.get(e.stage) or info.get("top3") or []
                    e.us_broadcasts = info.get("us_broadcasts") or []
                    if weekend.get("link"):
                        e.link = weekend["link"]
                    if e.results:
                        e.status = FINAL
                col.add(evs)

    # C) extras
    col.add(extras.load(cfg["extras"]))
    return col.events, standings, ap_top


def build(cfg: dict, state: State, now: datetime) -> dict:
    rules, teams_cfg, rights = cfg["rules"], cfg["teams"], cfg["rights"]
    win = rules.get("window", {})
    w_start = now - timedelta(days=win.get("days_back", 7))
    w_end = now + timedelta(days=win.get("days_ahead", 21))

    all_events, standings, ap_top = collect(cfg, state, now, w_start, w_end)
    matchday_leagues = {c["slug"] for c in rules.get("soccer", []) if c.get("matchday")}
    ctx = Context(
        my_team_ids={f"{t['sport']}:{t['espn_id']}": t["name"] for t in teams_cfg.get("teams", [])},
        standings=standings,
        ap_top=ap_top,
        matchdays=compute_matchdays(list(all_events.values()), standings, matchday_leagues),
    )

    included: list[tuple[Event, Inclusion]] = []
    for ev in all_events.values():
        if not in_window(ev, w_start, w_end):
            continue
        inc = classify(ev, rules, teams_cfg, ctx)
        if inc is None and rules.get("sticky_big_games", True) and ev.source == "espn":
            reason = state.sticky_reason(ev.uid)
            if reason:
                inc = Inclusion(reason)
        if inc is None:
            continue
        if not inc.my_team and ev.source == "espn":
            state.remember(ev.uid, inc.reason, ev.start)
        included.append((ev, inc))

    full, clean = [], []
    for ev, inc in included:
        tags = tags_for(ev, rules)
        desc = description(ev, inc, rules, tv_lines(ev, rights, ctx, tags), ctx.matchdays.get(ev.uid))
        dur = duration(ev, rules)
        full.append(Rendered(ev, title(ev, inc, rules, spoilers=True), desc, dur))
        clean.append(Rendered(ev, title(ev, inc, rules, spoilers=False), desc, dur))

    return {"included": included, "full": full, "clean": clean,
            "window": (w_start, w_end), "volume": weekly_volume(included)}


def report(result: dict, state: State, rules: dict) -> None:
    by_sport: dict[str, int] = {}
    for ev, inc in result["included"]:
        key = f"{ev.sport}{' (my teams)' if inc.my_team else ''}"
        by_sport[key] = by_sport.get(key, 0) + 1
    log.info("events in feed: %d  %s", len(result["included"]),
             ", ".join(f"{k}={v}" for k, v in sorted(by_sport.items())))
    limit = rules.get("volume_guardrail", {}).get("max_non_team_events_per_week", 20)
    for week, n in result["volume"].items():
        if n > limit:
            log.warning("VOLUME: %s has %d neutral events (limit %d) - consider tightening config/rules.yaml",
                        week, n, limit)
        else:
            log.info("volume %s: %d neutral events", week, n)
    if state.failures:
        log.warning("sources that failed this run (cached data used): %s", ", ".join(state.failures))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=Path("config"))
    ap.add_argument("--out", type=Path, default=Path("site"))
    ap.add_argument("--state", type=Path, default=None, help="state directory (default: <out>/state)")
    ap.add_argument("--now", help="pretend it is this UTC time (ISO), for testing")
    ap.add_argument("--check-health", action="store_true",
                    help="exit 1 if any source has been failing for more than 24h")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    state = State(args.state or args.out / "state", now)

    if args.check_health:
        stale = [k for k, v in state.health.items()
                 if v.get("failing_since") and now - datetime.fromisoformat(v["failing_since"]) > STALE_AFTER]
        for k in stale:
            log.error("source failing for more than 24h: %s (%s)", k, state.health[k].get("last_error"))
        return 1 if stale else 0

    cfg = load_config(args.config)
    result = build(cfg, state, now)
    report(result, state, cfg["rules"])

    count = len(result["included"])
    previous = state.last_build.get("event_count")
    if state.failures and previous and count < MIN_KEEP_RATIO * previous:
        log.error("feed shrank from %d to %d events while sources failed - NOT publishing", previous, count)
        return 2
    if count == 0:
        log.error("no events at all - NOT publishing")
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "calendar.ics").write_bytes(calendar(result["full"], "Hannes Sports", now))
    (args.out / "calendar-nospoilers.ics").write_bytes(
        calendar(result["clean"], "Hannes Sports (no spoilers)", now))
    state.finish({"built_at": now.isoformat(), "event_count": count, "failed_sources": state.failures})
    log.info("wrote %s", ", ".join(str(args.out / n) for n in ("calendar.ics", "calendar-nospoilers.ics")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
