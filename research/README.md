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
9. `10_units_backtest.py` – units won or lost following each pick list, graded at real prices where they exist: model
   spread picks at −110 and moneylines at the closing price (2020–2025), high-chance favorites at the closing moneyline
   and teaser legs at the per-leg price of a 2-team teaser at −120 (2024–25), and player milestones and long shots at
   the card's fair price (no sportsbook prices exist for those in this data). Run after 07–09, which save their
   pick-by-pick replays to `work/` (`units_research.json`).
