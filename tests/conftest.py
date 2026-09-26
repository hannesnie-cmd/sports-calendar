import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from src.adapters import espn
from src.filters import Context

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIX / name).read_text())


@pytest.fixture(scope="session")
def cfg():
    out = {}
    for name in ("teams", "rules", "rights", "extras"):
        out[name] = yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text())
    return out


@pytest.fixture(scope="session")
def raw():
    return load_fixture("espn_events.json")


@pytest.fixture
def ctx(cfg):
    return Context(my_team_ids={f"{t['sport']}:{t['espn_id']}": t["name"] for t in cfg["teams"]["teams"]})


@pytest.fixture
def ger1_standings():
    data = load_fixture("espn_standings_ger1.json")
    rows = []
    for entry in data["children"][0]["standings"]["entries"]:
        stats = {s["name"]: s.get("value") for s in entry["stats"]}
        rows.append({"team_id": entry["team"]["id"], "name": entry["team"]["shortDisplayName"],
                     "rank": int(stats["rank"]), "games_played": int(stats["gamesPlayed"])})
    return sorted(rows, key=lambda r: r["rank"])


def parse(raw_event, sport="soccer", league=None):
    return espn.parse_event(raw_event, sport, league)


NOW = datetime(2026, 9, 26, 21, 0, tzinfo=UTC)
