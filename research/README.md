# Research scripts

How the numbers in `pipeline/static/` were produced (2017–2025 nflverse data). Run from a folder that has the
nflverse files in `raw/` and an empty `work/` folder.

1. `01_team_games.py` – play-by-play to one row per team per game (offense and defense allowed).
2. `02_team_analysis.py` – which team stats predict results, plus the first model and its backtests.
3. `02b_trends_research.py` – how often 2+ week trends carried into the next game.
4. `03_player_analysis.py` – which player stats predict props; projection formulas.
5. `06_extra_aggregates.py` – garbage-time-filtered efficiency and quarterback games.
6. `07_spread_experiments.py` – walk-forward spread tests (opponent adjustment, garbage time, recency, QB ratings,
   rest and travel, pressure), key numbers, teasers, and the current model's weights (`model_v2.json`).
7. `08_high_chance.py` – outcome distributions for player milestones (2018–2025) and the 2024–25 check that picks rated
   80%+ hit about as often as promised (`prop_dist.json`, `high_chance_research.json`).
8. `09_long_shots.py` – touchdown model (anytime, 2+, first scorer) and 100/300-yard chances, each tested season by
   season on 2021–2025 with only earlier data, plus a replay of the weekly long-shot picks (`longshot_model.json`,
   `longshot_research.json`).
9. `10_units_backtest.py` – units won or lost following the model's picks from 2020–2025, graded at real prices:
   spread picks at −110, moneylines at the closing price (`units_research.json`). Run after 07, which saves the
   walk-forward predictions to `work/`.
10. `inj_parity.py` – not research: checks that the page's live injury merge (`site/index.html`) and the build's
    (`pipeline/injuries.py`) give identical statuses, on saved copies of ESPN's injury feed and an NFL.com report, across
    made-up timings that exercise every rule. Needs Node.js.

## NBA and NHL (`nba_nhl/`)

How `pipeline/static/nba_model.json` and `pipeline/static/nhl_model.json` were produced. Run from a folder with the
inputs in `raw/` and an empty `work/` folder:

- `raw/nba/` and `raw/nhl/`: the sportsdataverse release files (hoopR: `schedule_`, `team_box_`, `player_box_<year>.csv`
  for 2012–2027; fastRhockey: `schedule_`, `team_box_`, `skater_box_`, `goalie_box_<year>.csv` for 2011–2027). A season
  is labeled by the year it ends.
- `raw/sbr/`: closing lines from the sportsbookreviewsonline archives (NBA 2007-08 to 2022-23; NHL most seasons from
  2007-08 to 2022-23).
- `raw/odds/`: closing game lines from ESPN's odds records for later seasons (`*_events.csv`, `*_odds.csv`).
- `raw/props/`: real player-prop lines from ESPN's odds records, 2023-24 on (`nba_props.csv.gz`, `nhl_props.csv.gz`,
  `nhl_athletes.csv`).

1. `nba_01_data.py`, `nhl_01_data.py` – one row per game with scores, rest, travel and closing lines.
2. `nba_02_model.py`, `nhl_02_model.py` (`nhl_02b_check.py`) – the game models, tested walk-forward against the closing
   line: NBA efficiency ratings plus availability; NHL goal and shot ratings scaled by the starting goalies.
3. `nba_03_players.py`, `nba_04_avail.py`, `nhl_03_players.py` – player projections (minutes or ice time times rates)
   and the value of missing rotation players.
4. `nba_05_propdata.py`, `nhl_05_propdata.py` – match the prop lines to players and outcomes.
5. `nba_06_props.py`, `nba_07_proptest.py`, `nhl_04_proptest.py`, `nhl_06_proptest.py` – outcome distributions, the
   calibration of high and low chances, and model-versus-book tests that set how much the model is blended with the
   book's price.
6. `nba_08_hcls.py` – how often high-chance and long-shot legs hit, by the chance the model gave them;
   `nba_08b_calibrate.py` – the tail maps for long shots and double- and triple-doubles (fit on 2015-16 to 2022-23,
   checked on 2023-24 to 2025-26), and a replay of the site's high-chance and long-shot lists on 2023-24 to 2025-26.
7. `situational.py`, `trend_carry.py` – rest and schedule spots, and whether streaks carried into the next game.
   Rest is counted in calendar days (Eastern): a back-to-back means the team also played the day before.
8. `nba_09_export.py`, `nhl_07_export.py` – write the two model files the builds read.

## Injured teammates

- `13a_with_without.py`, `13_injury_bump.py` (NFL): with/without splits show a missing regular's targets and carries go
  mostly to teammates at his position. The bump (fit 2018-2022, checked 2023-2025) moved backs' rushing projections from
  8 yards too low to about 1 when the starter sat, and improved target and carry shares, receptions and touchdowns.
- `nba_nhl/nba_10_injury_bump.py` (NBA): minutes go mostly to bench players at the same position; the old rule (everyone
  up to 15%) overshot by about 2 minutes. Per-minute rates did not reliably rise, so stats scale with the minutes only.
- `nba_nhl/nhl_08_injury_bump.py` (NHL): ice time shifts to skaters at the same position; shots, points and blocks did not
  move measurably, so only the ice time changes.
