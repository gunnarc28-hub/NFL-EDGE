# NFL Edge

NFL matchups with season and last-4 records, injury outlooks, trends that have lasted 2+ weeks, player prop
projections, high-chance picks, plus-money long shots (anytime and first touchdown scorers, 2+ TDs, 100- and 300-yard
games) with a check of your sportsbook's price, and a pick tracker that grades itself.

**How it stays current:** a GitHub Action (`.github/workflows/update.yml`) runs every 30 minutes from August
through February. It downloads the latest public data, rebuilds `site/data/data.json`, and redeploys the site.
Every visit loads the newest build, and live scores come straight from ESPN while games are on.

## What's inside

- `site/index.html`: the website. It reads `data/data.json` on every visit. Picks are saved in each visitor's browser,
  with Download backup / Restore backup to move them between devices.
- `pipeline/build.py`: rebuilds the data. Sources: nflverse (play-by-play, player stats, schedules and lines, official
  injury reports, snap counts, Next Gen Stats) and ESPN (injury status, expected return dates, live scores).
- `pipeline/static/`: the research the model is built on (2017–2025): which team and player stats predict results,
  model weights, spread backtests, teaser and key-number history, and how often 2+ week trends carried into the next game.
- `research/`: the scripts that produced those files.

## Run the build yourself

```
pip install -r pipeline/requirements.txt
python pipeline/build.py
```

Then open the site with any local web server, for example `python -m http.server -d site`.

## Turning the site on (one time)

Repository **Settings → Pages → Build and deployment → Source: GitHub Actions**. Then open the **Actions** tab,
choose **Update NFL Edge**, and click **Run workflow**. The site appears at `https://<your-username>.github.io/nfl-edge/`.

For entertainment and research. The model picks winners about as often as the betting favorite and has not
beaten the spread over time; nothing here is betting advice.
