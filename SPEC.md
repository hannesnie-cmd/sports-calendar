# SPEC: Hannes Sports Calendar

## Goal
One subscribable calendar feed (.ics) with every game for my teams, a curated set of big neutral games, TV channels in English, German and Dutch, and results added to the event title after each game. It runs automatically with zero maintenance.

## How to work on this (instructions for Claude Code)
- Start by reading this whole spec. Propose a plan and ask me the Open Questions at the bottom before writing code.
- Never assume an API slug, field name, or broadcaster. Hit the real endpoints, inspect the responses, and build from what you see.
- Show me sample events (5–10, across different sports) before setting up hosting.
- Keep everything configurable in YAML so I can change teams and rules without touching code.
- Python 3.12, minimal dependencies (`requests`, `icalendar`, `pyyaml`). Add tests for the rule filters and the ICS output.

## Hosting & automation
- GitHub repo `sports-calendar`. GitHub Actions runs the build every 2 hours and publishes `calendar.ics` (and `calendar-nospoilers.ics`) to GitHub Pages.
- Give me the final subscribe URLs and step-by-step instructions for adding them to Google Calendar ("From URL") and Apple Calendar.
- Window: 7 days back (so results stay visible) to 21 days ahead.
- Robustness: if a source fails, keep the last successful data for that source. Never publish an empty or partial calendar because one API was down. Log failures in the Actions run.

## Data sources (verify all of them live)
- **ESPN public site API** (unofficial, `site.api.espn.com/apis/site/v2/sports/...`): football/soccer, NFL, college football, MLB. Use it for schedules, scores, status, rankings, and US broadcasters.
  - Likely soccer slugs to verify: `ger.1`, `ger.2`, `ger.dfb_pokal`, `ned.1`, `eng.1`, `uefa.champions`, `uefa.europa`, `uefa.nations`, `fifa.friendly`, plus World Cup qualifying slugs.
  - For my teams, use team schedule endpoints so every competition is covered (cups, Europe).
- **Jolpica F1 API** (Ergast successor): F1 schedule, session times, and results.
- Wrap each source in its own adapter module so a broken source can be swapped out.

## What goes in the calendar

### A) My teams: every game, every competition
- Football clubs: 1. FC Kaiserslautern, FC Bayern München, AFC Ajax
- National teams (men): Germany, Netherlands, USA (see open questions)
- NFL: New England Patriots
- MLB: New York Yankees (regular season and postseason)
- F1: Qualifying, Sprint Qualifying, Sprint, and Race every weekend. Practice sessions off by default, switchable in config.

### B) Big games (rules, all in `config/rules.yaml`)
- **Bundesliga & Premier League:** both teams in the current top 6. Before matchday 6 of the season, use a configured "big clubs" list instead of the table.
- **Champions League:** both teams on a configured "elite clubs" list, plus every knockout-round game.
- **Nations League / World Cup qualifiers / major tournaments:** both teams on a configured "top nations" list, plus every knockout game at a major tournament.
- **NFL:** every primetime game (Thursday, Sunday, and Monday night), plus the whole postseason.
- **College football:** both teams ranked in the AP top 15, plus conference championships, the playoff, and the national title game.
- **MLB:** postseason only, plus all Yankees games.
- **Volume guardrail:** aim for no more than about 20 non-team events per week. If a week goes over, report it in the log so I can tighten the rules.

### C) Extras (`config/extras.yaml`)
Manually added one-off events: marathons, title fights, big tennis finals, and so on. Fields: title, start, end, sport, TV (per language), notes. They're included as-is.

## Event format
- Title before the game: `⚽ Bayern vs Dortmund · Bundesliga`. Use emoji per sport (⚽ 🏈 ⚾ 🏎️) and add ⭐ when one of my teams is involved.
- Title after the game: `✅ Bayern 3–1 Dortmund · Bundesliga`. For F1: `✅ 🏎️ Race: 1. Verstappen · 2. … · 3. …`
- Times: stored in UTC, displayed correctly in Europe/Berlin.
- Duration: football 2h, NFL and college 3.5h, MLB 3.5h, F1 race 2h, other F1 sessions 1h.
- Description:
  ```
  Competition, round/matchday, venue
  📺 EN: ESPN+ (live data) | Sky Sports (rights map)
  📺 DE: DAZN (rights map)
  📺 NL: ESPN NL (rights map)
  Link: ESPN match page
  ```
- Stable UIDs per match, so updates and results overwrite the existing event instead of creating duplicates.
- **No-spoiler feed:** `calendar-nospoilers.ics` is identical but never shows scores or F1 results.

## TV channels
- **EN (US):** from ESPN's live broadcast data, per match.
- **EN (UK), DE, NL:** from `config/rights.yaml`, a rights map per competition per country for the **2026/27 season**.
  - Research current rights holders on the web. Store each entry with its source URL and the date it was checked.
  - Support slot rules where rights are split (e.g. Bundesliga in Germany by kickoff day and time, Champions League in Germany by top game vs. the rest).
  - Mark any uncertain entry as `confidence: low`. Low-confidence channels show as "DAZN?" in the event.
  - Every channel line is labelled as live data or rights map.
- Competitions to cover in the rights map: Bundesliga, 2. Bundesliga, DFB-Pokal, Eredivisie, KNVB Beker, Premier League, Champions League, Nations League, World Cup qualifiers, NFL, college football, MLB, F1.

## Repo structure (suggested)
```
config/teams.yaml   config/rules.yaml   config/rights.yaml   config/extras.yaml
src/adapters/espn.py   src/adapters/jolpica.py
src/filters.py   src/tv.py   src/build_ics.py
tests/
.github/workflows/build.yml
```

## Acceptance criteria
- [ ] Both feeds subscribe cleanly in Google Calendar and Apple Calendar
- [ ] All six of my teams' upcoming games appear, including cups and European games
- [ ] F1 sessions appear with correct Berlin times
- [ ] Results show up in titles within one build cycle of full time (calendar app refresh lag aside)
- [ ] No duplicate events after repeated builds
- [ ] One API failing does not remove that sport's events
- [ ] The rights map has sources and dates for every entry
- [ ] README explains how to change teams, rules, extras, and rights

## Out of scope (for now)
Push notifications, a web UI, live in-game scores, other sports (NBA, NHL, tennis) except via extras.

## Open questions for Hannes (ask before building)
1. USA men's national team in or out?
2. F1 practice sessions: off (default) or on?
3. Is the build frequency (every 2h) fine, or should it be more frequent on matchdays?
4. Should UK English channels be in the rights map, or only US live data?
5. Any extra competitions to follow at league level (e.g. all Eredivisie top-3 clashes)?
