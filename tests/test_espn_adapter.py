"""Parsing real ESPN responses (both the team-schedule and the scoreboard format)."""

from src.model import FINAL, SCHEDULED

from .conftest import load_fixture, parse


def test_team_schedule_final_with_dict_scores(raw):
    ev = parse(raw["bayern_union_final"])
    assert ev.uid == "espn-401884790"
    assert ev.competition == "ger.1"
    assert ev.status == FINAL
    assert (ev.home.name, ev.home_score, ev.away_score, ev.away.name) == ("Bayern", "7", "0", "Union Berlin")
    assert ev.link.startswith("https://www.espn.com/soccer/match/")


def test_fixture_stage_and_us_broadcast(raw):
    ev = parse(raw["bayern_viking_ucl"])
    assert ev.competition == "uefa.champions"
    assert ev.stage == "league-phase"
    assert ev.status == SCHEDULED
    assert ev.home_score is None
    assert ev.us_broadcasts == ["Paramount+"]
    assert ev.start.isoformat() == "2026-10-13T19:00:00+00:00"


def test_time_not_confirmed_is_flagged(raw):
    assert parse(raw["bayern_tbd_fixture"]).time_tbd is True
    assert parse(raw["bayern_viking_ucl"]).time_tbd is False


def test_penalty_shootout(raw):
    ev = parse(raw["germany_paraguay_pens"])
    assert ev.status == FINAL
    assert ev.status_detail == "STATUS_FINAL_PEN"
    assert ev.home_shootout and ev.away_shootout


def test_scoreboard_string_scores_use_home_away_not_order():
    data = load_fixture("espn_scoreboard_ger1_202609.json")
    ev = next(parse(e, league="ger.1") for e in data["events"] if e["id"] == "401884790")
    assert ev.home.name == "Bayern" and ev.home_score == "7" and ev.away_score == "0"
    assert ev.stage == "2026-27-german-bundesliga"


def test_mlb_placeholders_have_tbd_teams_and_postseason_type(raw):
    evs = [parse(e, "mlb") for e in raw["mlb_postseason_placeholders"]]
    assert all(e.season_type == 3 for e in evs)
    tbd = [e for e in evs if e.home.name == "TBD" and e.away.name == "TBD"]
    assert tbd and all(e.home.id is None for e in tbd)
    yankees = next(e for e in evs if "10" in e.team_ids())
    assert yankees.time_tbd and yankees.notes[0].startswith("ALWC")


def test_cfb_rank_prefix(raw):
    evs = [parse(e, "cfb") for e in raw["cfb_week"]]
    names = [t.name for e in evs for t in (e.home, e.away)]
    assert any(n.startswith("#") for n in names)
    assert all(not n.startswith("#99") for n in names)
