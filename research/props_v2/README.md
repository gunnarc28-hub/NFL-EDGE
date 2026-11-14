# Prop fair prices, v2 (November 2026)

Run in order with box scores from sportsdataverse (NBA, NHL), nflverse weekly stats (NFL) and ESPN's prop-line records
(collected through GitHub Actions; the scripts expect them in `research_work/props/`).

- `nba_base.py`: player form rebuilt game by game, 2022-23 to now.
- `nba_proj_test.py`: projection error vs results; faster form (half-life 10 games), a lighter prior and a refit minutes
  model (last game, season start) cut the error by 1-3%.
- `nba_lines.py`, `nba_eval.py`: main lines (2023-24 to now) against the result. The book beat the projection in every
  market; overs hit 1-3 points less often than the book's no-vig price.
- `nba_rule.py`: betting where the fair chance beat the price. No market held up in every test season.
- `nba_ms_eval.py`: ESPN's milestone prices. Rungs below the main line were often listed near even money and hit 94-98%:
  bad records, not value.
- `nba_anchor_test.py`: projection mixed with the line's implied mean; high-chance and long-shot calibration.
- `nba_fit_export.py`: the shipped parameters (`pipeline/static/nba_props_v2.json`).
- `nhl_eval.py`: NHL main lines and anytime-goal prices (`pipeline/static/nhl_props_v2.json`).
- `nfl_eval.py`: NFL lines (no prices in ESPN's records): how often overs cleared DraftKings' lines.
