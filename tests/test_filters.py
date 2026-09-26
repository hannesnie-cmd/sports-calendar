"""Rule filters: my teams, big-game rules per competition, volume guardrail."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from src.filters import Context, classify, compute_matchdays, tags_for, weekly_volume
from src.model import FINAL, Event, Team

from .conftest import load_fixture, parse

BAYERN, DORTMUND, LEVERKUSEN, MAINZ, ELVERSBERG = "132", "124", "131", "2950", "10388"


def soccer(comp, home, away, stage=None, start=datetime(2026, 10, 17, 16, 30, tzinfo=UTC), uid="espn-1"):
    return Event(uid=uid, source="espn", sport="soccer", competition=comp, competition_name=comp,
                 start=start, home=Team(home, f"T{home}"), away=Team(away, f"T{away}"), stage=stage)


def us(sport, home, away, start, season_type=2, notes=None, uid="espn-9"):
    return Event(uid=uid, source="espn", sport=sport, competition=sport, competition_name=sport, start=start,
                 home=Team(home, f"T{home}"), away=Team(away, f"T{away}"), season_type=season_type,
                 notes=notes or [])


# --- my teams ------------------------------------------------------------------

def test_my_team_in_any_competition(cfg, ctx):
    inc = classify(soccer("club.friendly", "999", BAYERN), cfg["rules"], cfg["teams"], ctx)
    assert inc.my_team and "Bayern" in inc.reason


def test_team_ids_are_scoped_by_sport(cfg, ctx):
    # The Patriots are ESPN NFL team 17; a college team with id 17 is not "my team".
    cfb = us("cfb", "17", "333", datetime(2026, 10, 3, 18, tzinfo=UTC))
    assert classify(cfb, cfg["rules"], cfg["teams"], ctx) is None
    nfl = us("nfl", "17", "2", datetime(2026, 10, 4, 17, tzinfo=UTC))
    assert classify(nfl, cfg["rules"], cfg["teams"], ctx).my_team


def test_excluded_competition_drops_my_team_games(cfg, ctx):
    teams = {**cfg["teams"], "exclude_competitions": ["club.friendly"]}
    assert classify(soccer("club.friendly", "999", BAYERN), cfg["rules"], teams, ctx) is None


# --- Bundesliga / Premier League / Eredivisie table rule -------------------------

def test_before_matchday_6_uses_big_clubs(cfg, ger1_standings):
    ctx = Context(standings={"ger.1": ger1_standings}, matchdays={"espn-1": 5})
    big = soccer("ger.1", DORTMUND, LEVERKUSEN)             # both on big_clubs
    assert "big clubs" in classify(big, cfg["rules"], cfg["teams"], ctx).reason
    table_only = soccer("ger.1", DORTMUND, MAINZ)           # both top 6, Mainz not a big club
    assert classify(table_only, cfg["rules"], cfg["teams"], ctx) is None


def test_from_matchday_6_uses_table(cfg, ger1_standings):
    ctx = Context(standings={"ger.1": ger1_standings}, matchdays={"espn-1": 6})
    inc = classify(soccer("ger.1", DORTMUND, MAINZ), cfg["rules"], cfg["teams"], ctx)
    assert inc and "top-6 clash (#1 vs #6)" in inc.reason
    assert classify(soccer("ger.1", DORTMUND, ELVERSBERG), cfg["rules"], cfg["teams"], ctx) is None


def test_matchday_from_standings_and_scoreboard(ger1_standings):
    events = [parse(e, league="ger.1") for e in load_fixture("espn_scoreboard_ger1_202609.json")["events"]]
    md = compute_matchdays(events, {"ger.1": ger1_standings}, {"ger.1"})
    assert md["espn-401884790"] == 4       # Bayern v Union on 18 Sep: Bayern's 4th league game
    assert md["espn-401884791"] == 3       # Elversberg v Bayern on 13 Sep


# --- Europe, cups, national teams --------------------------------------------------

@pytest.mark.parametrize("comp,home,away,stage,included", [
    ("uefa.champions", "86", "132", "league-phase", True),        # both elite
    ("uefa.champions", "510", "132", "league-phase", False),      # Viking not elite (Bayern is mine, tested elsewhere)
    ("uefa.champions", "510", "2980", "round-of-16", True),       # any knockout game
    ("uefa.europa", "1", "2", "league-phase", False),
    ("uefa.europa", "1", "2", "round-of-16", True),
    ("ger.dfb_pokal", "1", "2", "second-round", False),
    ("ger.dfb_pokal", "1", "2", "quarterfinals", True),
    ("eng.fa", "1", "2", "semifinals", False),
    ("eng.fa", "1", "2", "final", True),
    ("uefa.nations", "164", "478", "league-phase", True),         # Spain v France
    ("uefa.nations", "164", "6757", "league-phase", False),       # Spain v Serbia
    ("fifa.world", "1", "2", "group-stage", False),
    ("fifa.world", "1", "2", "round-of-32", True),
    ("uefa.europa.conf", "1", "2", "league-phase", False),        # rule: none
])
def test_competition_rules(cfg, comp, home, away, stage, included):
    ctx = Context()                                               # nobody is "my team" here
    inc = classify(soccer(comp, home, away, stage), cfg["rules"], cfg["teams"], ctx)
    assert (inc is not None) == included


# --- NFL -------------------------------------------------------------------------------

def test_nfl_primetime_from_real_schedule(cfg):
    evs = {e["id"]: parse(e, "nfl") for e in load_fixture("espn_events.json")["nfl_month"]}
    ctx = Context()
    included = {uid for uid, ev in evs.items() if classify(ev, cfg["rules"], cfg["teams"], ctx)}
    for uid, ev in evs.items():
        local = ev.start.astimezone(ZoneInfo("America/New_York"))
        primetime = local.strftime("%a") in ("Thu", "Sun", "Mon") and local.hour >= 19
        assert (uid in included) == primetime, (ev.home.name, ev.away.name, local)
    assert included, "fixture should contain at least one primetime game"


def test_nfl_postseason_included(cfg):
    ev = us("nfl", "1", "2", datetime(2027, 1, 10, 18, tzinfo=UTC), season_type=3, notes=["AFC Wild Card Playoffs"])
    assert "postseason" in tags_for(ev, cfg["rules"])
    assert classify(ev, cfg["rules"], cfg["teams"], Context()).reason == "NFL postseason"


def test_nfl_pro_bowl_excluded(cfg):
    ev = us("nfl", "1", "2", datetime(2027, 2, 1, 1, tzinfo=UTC), season_type=3, notes=["Pro Bowl"])
    assert classify(ev, cfg["rules"], cfg["teams"], Context()) is None


# --- College football -------------------------------------------------------------------

def test_cfb_ap_top15_both_ranked(cfg):
    ctx = Context(ap_top=[str(i) for i in range(100, 125)])
    both = us("cfb", "101", "112", datetime(2026, 10, 3, 19, tzinfo=UTC))
    assert "(#2 vs #13)" in classify(both, cfg["rules"], cfg["teams"], ctx).reason
    one = us("cfb", "101", "118", datetime(2026, 10, 3, 19, tzinfo=UTC))    # #19 is outside top 15
    assert classify(one, cfg["rules"], cfg["teams"], ctx) is None


def test_cfb_title_games_and_playoff_from_real_notes(cfg):
    evs = [parse(e, "cfb") for e in load_fixture("espn_events.json")["cfb_2025_title_games"]]
    ctx = Context(ap_top=[])
    for ev in evs:
        assert classify(ev, cfg["rules"], cfg["teams"], ctx), ev.notes


# --- MLB ---------------------------------------------------------------------------------

def test_mlb_only_lcs_and_world_series_plus_yankees(cfg, ctx):
    evs = [parse(e, "mlb") for e in load_fixture("espn_events.json")["mlb_postseason_placeholders"]]
    for ev in evs:
        inc = classify(ev, cfg["rules"], cfg["teams"], ctx)
        note = ev.notes[0]
        if "10" in ev.team_ids():
            assert inc.my_team
        elif note.startswith(("ALCS", "NLCS", "World Series")):
            assert inc and "MLB postseason" in inc.reason
        else:
            assert inc is None, note


# --- F1 ------------------------------------------------------------------------------------

def test_f1_practice_switch(cfg, ctx):
    fp1 = Event(uid="f1-2026-17-fp1", source="jolpica", sport="f1", competition="f1",
                competition_name="Formula 1", start=datetime(2026, 10, 9, 8, 30, tzinfo=UTC), stage="fp1")
    on = {**cfg["teams"], "f1": {"enabled": True, "sessions": {"practice": True}}}
    off = {**cfg["teams"], "f1": {"enabled": True, "sessions": {"practice": False}}}
    assert classify(fp1, cfg["rules"], on, ctx)
    assert classify(fp1, cfg["rules"], off, ctx) is None


# --- volume guardrail ---------------------------------------------------------------------

def test_weekly_volume_counts_only_neutral_games(cfg, ctx):
    mine = soccer("ger.1", BAYERN, DORTMUND, uid="espn-a")
    neutral = soccer("ger.1", DORTMUND, LEVERKUSEN, uid="espn-b")
    rows = [(mine, classify(mine, cfg["rules"], cfg["teams"], ctx)),
            (neutral, classify(neutral, cfg["rules"], cfg["teams"], Context(matchdays={"espn-b": 1})))]
    assert weekly_volume(rows) == {"2026-W42": 1}


def test_status_final_does_not_change_inclusion(cfg, ctx):
    ev = soccer("ger.1", BAYERN, DORTMUND)
    ev.status = FINAL
    assert classify(ev, cfg["rules"], cfg["teams"], ctx).my_team
