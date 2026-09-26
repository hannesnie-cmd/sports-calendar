"""Rights map: slot rules, confidence markers, labels, and that every entry is sourced."""

from datetime import UTC, date, datetime

import pytest

from src.filters import Context
from src.model import Event, Team
from src.tv import resolve, tv_lines

BERLIN_SUMMER = 2   # CEST offset in October before the clock change


def match(comp, y, mo, d, h, mi, home="1", away="2", stage=None, sport="soccer", tbd=False):
    start = datetime(y, mo, d, h - BERLIN_SUMMER, mi, tzinfo=UTC)
    return Event(uid="espn-1", source="espn", sport=sport, competition=comp, competition_name=comp,
                 start=start, home=Team(home, "H"), away=Team(away, "A"), stage=stage, time_tbd=tbd)


def channels(ev, cfg, country, ctx=None, tags=frozenset()):
    rule = resolve(ev, cfg["rights"], country, ctx or Context(), set(tags))
    return rule["channels"] if rule else None


@pytest.mark.parametrize("day,hh,mm,expected", [
    (16, 20, 30, ["Sky"]),                          # Friday
    (17, 15, 30, ["Sky", "DAZN (Konferenz)"]),      # Saturday afternoon
    (17, 18, 30, ["Sky"]),                          # Saturday top game
    (18, 17, 30, ["DAZN"]),                         # Sunday
    (21, 20, 30, ["Sky", "DAZN (Konferenz)"]),      # Wednesday (englische Woche)
])
def test_bundesliga_germany_slots(cfg, day, hh, mm, expected):
    assert channels(match("ger.1", 2026, 10, day, hh, mm), cfg, "DE") == expected


def test_tbd_kickoff_skips_slot_rules(cfg):
    rule = resolve(match("ger.1", 2026, 12, 5, 21, 0, tbd=True), cfg["rights"], "DE", Context(), set())
    assert rule["channels"] == ["Sky"] and rule["confidence"] == "low"


def test_premier_league_uk_3pm_blackout_and_early_kickoff(cfg):
    # UK is one hour behind Berlin
    assert channels(match("eng.1", 2026, 10, 17, 16, 0), cfg, "UK") == ["not on UK TV (3pm blackout)"]
    assert channels(match("eng.1", 2026, 10, 17, 13, 30), cfg, "UK") == ["TNT Sports"]
    assert channels(match("eng.1", 2026, 10, 18, 17, 30), cfg, "UK") == ["Sky Sports"]


def test_champions_league_germany_tuesday_top_game(cfg):
    ctx = Context(standings={"ger.1": [{"team_id": "132", "rank": 2, "games_played": 4}]})
    tue_bayern = match("uefa.champions", 2026, 10, 13, 21, 0, home="510", away="132", stage="league-phase")
    rule = resolve(tue_bayern, cfg["rights"], "DE", ctx, set())
    assert rule["channels"] == ["Prime Video"] and rule["confidence"] == "low"
    wed = match("uefa.champions", 2026, 10, 21, 21, 0, home="132", away="359", stage="league-phase")
    assert channels(wed, cfg, "DE", ctx) == ["DAZN"]


def test_nations_league_germany_home_and_away(cfg):
    assert channels(match("uefa.nations", 2026, 10, 4, 20, 45, home="455", away="481"), cfg, "DE") == ["RTL"]
    assert channels(match("uefa.nations", 2026, 10, 1, 20, 45, home="481", away="6757"), cfg, "DE") == ["ZDF"]
    assert channels(match("uefa.nations", 2026, 11, 16, 20, 45, home="481", away="449"), cfg, "DE") == ["ARD"]
    assert channels(match("uefa.nations", 2026, 10, 4, 20, 45, home="449", away="6757"), cfg, "NL") == ["NOS"]


def test_qualifying_rounds_use_parent_competition(cfg):
    ev = match("uefa.europa.conf_qual", 2026, 8, 27, 20, 0, home="139", away="1")
    assert channels(ev, cfg, "NL") == ["Ziggo Sport"]


def test_nfl_primetime_tag_in_germany(cfg):
    ev = match("nfl", 2026, 10, 5, 2, 20, sport="nfl")
    assert channels(ev, cfg, "DE", tags={"primetime"})[0] == "RTL/NITRO"
    assert channels(ev, cfg, "DE")[0] == "Sky"


def test_lines_are_labelled_and_low_confidence_marked(cfg):
    ev = match("ned.1", 2026, 10, 10, 21, 0, home="139", away="147")
    ev.us_broadcasts = ["ESPN+"]
    lines = tv_lines(ev, cfg["rights"], Context(), set())
    assert lines == [
        "📺 EN: ESPN+ (live data) | no UK broadcaster? (rights map)",
        "📺 DE: Sportdigital (rights map)",
        "📺 NL: ESPN (rights map)",
    ]


def test_unknown_competition_shows_dash(cfg):
    lines = tv_lines(match("club.friendly", 2026, 10, 2, 18, 0), cfg["rights"], Context(), set())
    assert lines == ["📺 EN: –", "📺 DE: –", "📺 NL: –"]


def test_extras_use_manual_tv(cfg):
    ev = Event(uid="extra-x", source="extras", sport="running", competition="extra", competition_name="",
               start=datetime(2026, 9, 27, 6, tzinfo=UTC), tv={"DE": "RTL"})
    assert tv_lines(ev, cfg["rights"], Context(), set()) == ["📺 DE: RTL (manual)"]


def test_every_rights_entry_has_source_and_checked_date(cfg):
    comps = cfg["rights"]["competitions"]
    wanted = {"ger.1", "ger.2", "ger.dfb_pokal", "ned.1", "ned.cup", "eng.1", "uefa.champions",
              "uefa.nations", "fifa.worldq.uefa", "nfl", "cfb", "mlb", "f1"}
    assert wanted <= set(comps)
    for comp, countries in comps.items():
        for country, block in countries.items():
            assert country in cfg["rights"]["countries"], (comp, country)
            for rule in block["rules"]:
                src = rule.get("source", block.get("source"))
                checked = rule.get("checked", block.get("checked"))
                assert src and all(s.startswith("https://") for s in src), (comp, country)
                assert isinstance(checked, date), (comp, country)
                assert rule.get("confidence", block.get("confidence")) in ("high", "medium", "low")
                assert rule.get("channels"), (comp, country)
