# Hannes Sports Calendar

One subscribable calendar with every game of my teams, a curated set of big neutral games,
TV channels in English, German and Dutch, and results in the title after each game.
GitHub Actions rebuilds it every 30 minutes and publishes it to GitHub Pages.

| Feed | URL |
|---|---|
| With results | `https://hannesnie-cmd.github.io/sports-calendar/calendar.ics` |
| No spoilers  | `https://hannesnie-cmd.github.io/sports-calendar/calendar-nospoilers.ics` |

The no-spoiler feed has the same events and descriptions but never shows scores or F1 results.

## Subscribe

**Apple Calendar (Mac)**
1. Calendar → File → New Calendar Subscription…
2. Paste the feed URL (use `webcal://` instead of `https://` if it asks), click Subscribe.
3. Location: **iCloud** (so it syncs to your iPhone). Auto-refresh: **Every 15 minutes**.
4. Leave "Remove Alerts" ticked unless you want alarms. Click OK.

**Apple Calendar (iPhone, if you don't use the Mac)**
Settings → Apps → Calendar → Calendar Accounts → Add Account → Other → Add Subscribed Calendar → paste the URL → Next → Save.

**Google Calendar**
1. Open calendar.google.com on a computer.
2. Left sidebar: Other calendars → **+** → From URL.
3. Paste the `https://` feed URL → Add calendar.

Google refreshes subscribed calendars only every 8–24 hours and can't be forced, so results show up
much later there than in Apple Calendar.

## What's in it

**My teams, every competition** (`config/teams.yaml`): 1. FC Kaiserslautern, FC Bayern, Ajax,
Germany, Netherlands, New England Patriots, New York Yankees (regular season and postseason).
ESPN's team schedule covers league, cups, European games, supercups and friendlies.

**Formula 1:** practice, sprint qualifying, sprint, qualifying and race (each switchable).

**Big neutral games** (`config/rules.yaml`):
- Bundesliga and Premier League: both teams in the top 6 (before matchday 6: both on the big-clubs list)
- Eredivisie: both teams in the top 3
- Champions League: both teams elite clubs, plus every knockout game
- Europa League from the round of 16, DFB-Pokal from the quarterfinals, FA Cup final
- Nations League / qualifiers: both teams on the top-nations list; World Cup/EURO: plus every knockout game
- NFL: Thursday, Sunday and Monday night games and the whole postseason
- College football: both teams in the AP top 15, conference title games, the playoff and the title game
- MLB: ALCS, NLCS and World Series (plus every Yankees game)

A big game stays in the calendar once it qualifies, even if the table changes before kickoff
(`sticky_big_games`). Each neutral event says why it's there ("Why: …") so you can tune the rules.
The build log warns when a week has more than 20 neutral events.

**Event format**
```
⭐ ⚽ Bayern vs Dortmund · Bundesliga          before (⭐ = one of my teams, home team first)
✅ ⭐ Bayern 3–1 Dortmund · Bundesliga         after
✅ 🏎️ Race: 1. Russell · 2. Verstappen · 3. Hadjar
```
Times are stored in UTC and shown in your local time. Games without a confirmed kickoff time are
all-day events marked "(time TBC)" until ESPN has the time. Events don't block your free/busy time.

## Changing things

All settings are YAML; you never need to touch the code. Push the change to `main` and the
workflow rebuilds right away.

**Add or remove a team** — `config/teams.yaml`. You need the team's ESPN id:
```sh
curl -s https://site.api.espn.com/apis/site/v2/sports/soccer/ger.1/teams | jq '.sports[0].leagues[0].teams[].team | {id, displayName}'
```
Replace `soccer/ger.1` with `football/nfl`, `baseball/mlb` or another league slug. Use `sport: soccer | nfl | mlb`.
To skip a competition for your teams (e.g. friendlies), add its slug to `exclude_competitions`.
F1 sessions are switched under `f1.sessions`.

**Change the big-game rules** — `config/rules.yaml`. Each soccer competition has a `rule`
(`table_clash`, `elite_or_knockout`, `knockout`, `nations_clash`, `tournament` or `none`) and its
parameters (`top_n`, `big_clubs`, `knockout_stages`). The `elite_clubs` and `top_nations` lists are at
the top. NFL, college football and MLB have their own sections. The window (7 days back, 21 ahead)
and event durations are there too.

**Add a one-off event** — `config/extras.yaml`:
```yaml
extras:
  - id: wimbledon-final-2027        # unique, keeps the event stable when you edit it
    title: Wimbledon men's final
    start: 2027-07-11T15:00         # Berlin time, or add an offset like +01:00
    end: 2027-07-11T19:00
    sport: tennis                   # adds 🎾
    tv: {EN: BBC One, DE: Prime Video, NL: Ziggo Sport}
    notes: Centre Court
```

**Update TV rights** — `config/rights.yaml`. Rights are per competition and country (UK, DE, NL).
Each block has `source` URLs, a `checked` date, a `confidence`, and `rules` that are tried top to
bottom; the first match wins:
```yaml
ger.1:
  DE:
    source: [https://…]
    checked: 2026-09-26
    confidence: high
    rules:
      - when: {weekdays: [sat], times: ["15:30"]}
        channels: [Sky, DAZN (Konferenz)]
      - channels: [Sky]           # default
```
Conditions: `weekdays`, `times`, `after`, `stages`, `teams`, `home_team`, `away_team`,
`league_teams` (a club from that league plays), `tags` (`primetime`, `postseason`) and `event_ids`
(pin one match, e.g. when the Tuesday Prime Video game is announced). `confidence: low` shows the
channel as `DAZN?`. US channels come from ESPN's live data and are labelled "(live data)".

Things to re-check: UEFA's 2027–2030 club competition rights (the Paramount deal in Germany starts in 2027),
EURO 2028 qualifiers (from March 2027), Viaplay NL moving to Videoland, and MLB in Germany after 2026.

## How it works

```
config/*.yaml → src/adapters (espn.py, jolpica.py, extras.py) → src/filters.py → src/tv.py
             → src/formatting.py → src/ics.py → site/calendar.ics + site/calendar-nospoilers.ics
```
- **ESPN** (unofficial public API): team schedules, league scoreboards by month, tables, AP poll,
  scores, status, US TV, F1 US TV and sprint-qualifying results.
- **Jolpica** (Ergast successor): F1 calendar, session times, race/qualifying/sprint results.
- Every API call is a "unit" with its own last-good copy in the `state` branch. If a call fails, or
  suddenly returns nothing while it used to have upcoming games, the last good data is used and the
  failure is logged. The build refuses to publish if the feed would shrink by half while a source is
  down, and the workflow run turns red (GitHub emails you) when a source has been failing for 24 hours.
- A keepalive step stops GitHub from disabling the schedule after 60 days without commits.

**Run locally**
```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m src.build_ics --out site     # writes site/calendar.ics
```
