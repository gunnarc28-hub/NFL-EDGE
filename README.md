# Sports Edge

Games, the model's picks and why, injuries, player props, high-chance picks, long shots, trends and research for the
NFL, NBA and NHL, with one bet slip and a bet tracker that grades itself. It lives at
https://gunnarc28-hub.github.io/NFL-EDGE/ (the address kept its old name).

**How it stays current:** a GitHub Action (`.github/workflows/update.yml`) runs every 30 minutes, all year. It
downloads the latest public data, rebuilds each sport's numbers and redeploys the site. Each sport builds on its own:
if one fails, the site keeps that sport's last good numbers and the others still update. Every visit loads the newest
build; live scores and injury statuses come straight from ESPN while the page is open.

## What's inside

- `site/index.html`: the home page, a card per sport plus your bets.
- `site/nfl/`, `site/nba/`, `site/nhl/`: one page per sport, each reading its own `data/` folder. The NBA and NHL pages
  share `site/assets/app.js`; every page shares `assets/app.css`, `assets/core.js` and the bet slip and tracker in
  `assets/bets.js`. Bets are saved in each visitor's browser, with Download backup / Restore backup to move them
  between devices, and grade themselves from each sport's `data/grade.json`.
- `pipeline/build.py`: the NFL build. Sources: nflverse (play-by-play, player stats, schedules and lines, snap counts,
  Next Gen Stats), the official NFL injury report from NFL.com (nflverse's copy as a backup) and ESPN (injury status,
  expected return dates, live scores).
- `pipeline/nba.py`, `pipeline/nhl.py`: the NBA and NHL builds. Sources: hoopR and fastRhockey box scores and schedules
  (sportsdataverse), the NHL's own schedule and box-score feed, and ESPN (scoreboard, injuries, rosters, game lines and
  player-prop lines). Shared helpers are in `pipeline/sportslib.py`.
- `pipeline/injuries.py`: each NFL player's status for his team's next game, merged from the official report and ESPN's
  feed. The page runs the same merge live; `research/inj_parity.py` checks the two give identical answers.
- `pipeline/static/`: the research each model is built on: which stats predict results, model weights, backtests
  against the closing line, prop calibration and how often trends carried into the next game.
- `research/`: the scripts that produced those files (`research/nba_nhl/` for basketball and hockey).

## Run the builds yourself

```
pip install -r pipeline/requirements.txt
python pipeline/build.py
python pipeline/nba.py
python pipeline/nhl.py
```

Then open the site with any local web server, for example `python -m http.server -d site`.

## Turning the site on (one time)

Repository **Settings → Pages → Build and deployment → Source: GitHub Actions**. Then open the **Actions** tab,
choose **Update Sports Edge**, and click **Run workflow**. The site appears at `https://<your-username>.github.io/<repo-name>/`.

For entertainment and research. The models pick winners about as often as the betting favorite and have not beaten
the closing line over time; nothing here is betting advice.
