"""Titles, descriptions, ICS output, stable UIDs, no-spoiler feed, and source-failure fallback."""

import json
from datetime import UTC, datetime

import pytest
from icalendar import Calendar

from src import build_ics
from src.adapters import espn, jolpica
from src.fetch import FetchError
from src.filters import Inclusion
from src.formatting import description, duration, title
from src.model import FINAL, POSTPONED, Event, Team

from .conftest import FIX, ROOT, load_fixture

MINE = Inclusion("my team: Bayern", my_team=True)
BIG = Inclusion("Bundesliga: top-6 clash (#1 vs #2)")


def game(**kw):
    base = dict(uid="espn-1", source="espn", sport="soccer", competition="ger.1", competition_name="German Bundesliga",
                start=datetime(2026, 10, 31, 17, 30, tzinfo=UTC), home=Team("132", "Bayern"),
                away=Team("124", "Dortmund"), venue="Allianz Arena", city="Munich")
    base.update(kw)
    return Event(**base)


# --- titles -------------------------------------------------------------------------

def test_title_before_and_after(cfg):
    ev = game()
    assert title(ev, MINE, cfg["rules"]) == "⭐ ⚽ Bayern vs Dortmund · Bundesliga"
    assert title(ev, BIG, cfg["rules"]) == "⚽ Bayern vs Dortmund · Bundesliga"
    ev.status, ev.home_score, ev.away_score = FINAL, "3", "1"
    assert title(ev, BIG, cfg["rules"]) == "✅ Bayern 3–1 Dortmund · Bundesliga"
    assert title(ev, MINE, cfg["rules"]) == "✅ ⭐ Bayern 3–1 Dortmund · Bundesliga"
    assert title(ev, MINE, cfg["rules"], spoilers=False) == "⭐ ⚽ Bayern vs Dortmund · Bundesliga"


def test_title_extra_time_and_penalties(cfg):
    aet = game(competition="ger.dfb_pokal", status=FINAL, status_detail="STATUS_FINAL_AET",
               home_score="2", away_score="1")
    assert title(aet, MINE, cfg["rules"]) == "✅ ⭐ Bayern 2–1 Dortmund (a.e.t.) · DFB-Pokal"
    pens = game(competition="ger.dfb_pokal", status=FINAL, status_detail="STATUS_FINAL_PEN",
                home_score="1", away_score="1", home_shootout="4", away_shootout="3")
    assert title(pens, MINE, cfg["rules"]) == "✅ ⭐ Bayern 1–1 Dortmund (4–3 pens) · DFB-Pokal"


def test_title_postponed_and_tbd(cfg):
    assert title(game(status=POSTPONED), MINE, cfg["rules"]).startswith("⏸️ Postponed: ⭐ ⚽ Bayern vs Dortmund")
    assert title(game(time_tbd=True), MINE, cfg["rules"]).endswith("(time TBC)")


def test_f1_titles(cfg):
    race = Event(uid="f1-2026-15-race", source="jolpica", sport="f1", competition="f1",
                 competition_name="Formula 1", start=datetime(2026, 9, 26, 11, tzinfo=UTC), title="Race",
                 stage="race", stage_name="Round 15", info="Azerbaijan Grand Prix")
    f1 = Inclusion("Formula 1")
    assert title(race, f1, cfg["rules"]) == "🏎️ Race · Azerbaijan Grand Prix"
    race.results, race.status = ["Russell", "Verstappen", "Hadjar"], FINAL
    assert title(race, f1, cfg["rules"]) == "✅ 🏎️ Race: 1. Russell · 2. Verstappen · 3. Hadjar"
    assert title(race, f1, cfg["rules"], spoilers=False) == "🏎️ Race · Azerbaijan Grand Prix"
    assert duration(race, cfg["rules"]).total_seconds() == 2 * 3600
    race.stage = "qualifying"
    assert duration(race, cfg["rules"]).total_seconds() == 3600


def test_description_layout(cfg):
    ev = game(link="https://www.espn.com/soccer/match/_/gameId/1")
    tv = ["📺 EN: ESPN+ (live data) | Sky Sports (rights map)", "📺 DE: Sky (rights map)", "📺 NL: Viaplay (rights map)"]
    assert description(ev, BIG, cfg["rules"], tv, matchday=9) == "\n".join([
        "Bundesliga, Matchday 9, Allianz Arena, Munich",
        *tv,
        "Why: Bundesliga: top-6 clash (#1 vs #2)",
        "Link: https://www.espn.com/soccer/match/_/gameId/1",
    ])


@pytest.mark.parametrize("sport,hours", [("soccer", 2), ("nfl", 3.5), ("cfb", 3.5), ("mlb", 3.5)])
def test_durations(cfg, sport, hours):
    assert duration(game(sport=sport), cfg["rules"]).total_seconds() == hours * 3600


# --- end-to-end build with fixture-backed adapters -----------------------------------------

NOW = "2026-09-26T21:00:00+00:00"


def fixture_router(url: str, params: dict | None = None):
    params = params or {}
    raw = load_fixture("espn_events.json")
    if "/soccer/all/teams/132/schedule" in url:
        return {"events": [raw["bayern_viking_ucl"], raw["bayern_tbd_fixture"]] if params.get("fixture")
                else [raw["bayern_union_final"]]}
    if "/teams/" in url and url.endswith("/schedule"):
        return {"events": []}
    if "/soccer/ger.1/scoreboard" in url and params.get("dates") == "202609":
        return load_fixture("espn_scoreboard_ger1_202609.json")
    if "/soccer/ger.1/standings" in url:
        return load_fixture("espn_standings_ger1.json")
    if url.endswith("/standings"):
        return {"children": []}
    if "college-football/rankings" in url:
        return load_fixture("espn_cfb_rankings.json")
    if "college-football/scoreboard" in url and "week" not in params:
        return {"leagues": [{"calendar": []}], "events": []}
    if "racing/f1/scoreboard" in url:
        return load_fixture("espn_f1_weekend.json")
    if url.endswith("/scoreboard"):
        return {"events": []}
    if url.endswith("/2026/races/"):
        return load_fixture("jolpica_2026_races.json")
    if url.endswith("/2026/15/results/"):
        return load_fixture("jolpica_2026_15_results.json")
    if url.endswith("/2026/15/qualifying/"):
        return load_fixture("jolpica_2026_15_qualifying.json")
    if "api.jolpi.ca" in url:
        raise FetchError(f"HTTP 400 for {url}")
    raise AssertionError(f"unexpected URL {url} {params}")


def down(url, params=None):
    raise FetchError("HTTP 503 (simulated outage)")


@pytest.fixture
def offline(monkeypatch):
    def use(router_espn, router_jolpica=None):
        monkeypatch.setattr(espn, "get_json", router_espn)
        monkeypatch.setattr(jolpica, "get_json", router_jolpica or router_espn)
    use(fixture_router)
    return use


def run(out):
    return build_ics.main(["--config", str(ROOT / "config"), "--out", str(out), "--now", NOW])


def feed(out, name="calendar.ics"):
    cal = Calendar.from_ical((out / name).read_bytes())
    return {str(c["UID"]): c for c in cal.walk("VEVENT")}


def test_build_is_stable_and_has_no_duplicates(tmp_path, offline):
    assert run(tmp_path) == 0
    first = (tmp_path / "calendar.ics").read_text()
    assert run(tmp_path) == 0
    second = (tmp_path / "calendar.ics").read_text()
    uids = [l for l in second.splitlines() if l.startswith("UID:")]
    assert len(uids) == len(set(uids))
    assert [l for l in first.splitlines() if l.startswith("UID:")] == uids

    events = feed(tmp_path)
    assert "espn-401915411@hannes-sports-calendar" in events            # Viking v Bayern (UCL)
    assert "espn-401884788@hannes-sports-calendar" in events            # Leverkusen v Leipzig (big clubs)
    assert "extra-berlin-marathon-2026@hannes-sports-calendar" in events
    race = events["f1-2026-15-race@hannes-sports-calendar"]
    assert str(race["SUMMARY"]) == "✅ 🏎️ Race: 1. Russell · 2. Verstappen · 3. Hadjar"
    viking = events["espn-401915411@hannes-sports-calendar"]
    assert viking["DTSTART"].to_ical() == b"20261013T190000Z"          # stored in UTC
    assert viking["DTEND"].to_ical() == b"20261013T210000Z"


def test_nospoiler_feed_matches_but_hides_results(tmp_path, offline):
    run(tmp_path)
    full, clean = feed(tmp_path), feed(tmp_path, "calendar-nospoilers.ics")
    assert set(full) == set(clean)
    for uid, ev in clean.items():
        assert not str(ev["SUMMARY"]).startswith("✅"), ev["SUMMARY"]
        assert str(ev["DESCRIPTION"]) == str(full[uid]["DESCRIPTION"])
    assert str(clean["espn-401884788@hannes-sports-calendar"]["SUMMARY"]) == "⚽ Leverkusen vs RB Leipzig · Bundesliga"
    assert str(full["espn-401884788@hannes-sports-calendar"]["SUMMARY"]) == "✅ Leverkusen 2–0 RB Leipzig · Bundesliga"


def test_failed_source_keeps_last_good_data(tmp_path, offline):
    run(tmp_path)
    before = set(feed(tmp_path))
    offline(down)                                   # every API is down now
    assert run(tmp_path) == 0
    assert set(feed(tmp_path)) == before
    health = json.loads((tmp_path / "state" / "health.json").read_text())
    assert health["espn/team/soccer/132"]["failing_since"] == NOW
    assert build_ics.main(["--out", str(tmp_path), "--now", "2026-09-28T00:00:00+00:00", "--check-health"]) == 1


def test_empty_response_is_treated_as_failure(tmp_path, offline):
    run(tmp_path)
    offline(lambda url, params=None: {"events": []} if "/teams/132/" in url else fixture_router(url, params))
    run(tmp_path)
    assert "espn-401915411@hannes-sports-calendar" in feed(tmp_path)


def test_refuses_to_publish_a_shrunken_feed(tmp_path, offline):
    offline(down, fixture_router)                   # ESPN down, only F1 + extras available
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "last_build.json").write_text(json.dumps({"event_count": 100}))
    assert run(tmp_path) == 2
    assert not (tmp_path / "calendar.ics").exists()


def test_fixtures_are_present():
    assert (FIX / "espn_events.json").exists()
