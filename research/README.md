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
