"""Research probe (GitHub Actions only; the dev sandbox can't reach these hosts): the live site's NBA numbers as visitors
get them (grade, data, parts log, summary) plus ESPN's scoreboard and box scores for the last two nights, to check how
last night's bets grade. Writes probe_out/raw/."""
import json, os, time, urllib.request, urllib.error, datetime as dt
UA = {'User-Agent': 'Mozilla/5.0 (sports-edge research)'}
OUT = 'probe_out/raw'; os.makedirs(OUT, exist_ok=True)
LIVE = 'https://gunnarc28-hub.github.io/NFL-EDGE/'


def get(url, timeout=40, tries=3, raw=False):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                b = r.read()
                return b if raw else json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(2 * (i + 1))
        except Exception:
            time.sleep(2 * (i + 1))
    return None


stamp = int(time.time())
for sp in ('nba', 'nhl', 'nfl'):
    for f in ('grade.json', 'summary.json', 'parts_log.json'):
        b = get(f'{LIVE}{sp}/data/{f}?t={stamp}', raw=True)
        if b:
            open(f'{OUT}/live_{sp}_{f}', 'wb').write(b)
    for f in ('assets/bets.js',):
        b = get(f'{LIVE}{f}?t={stamp}', raw=True)
        if b:
            open(f'{OUT}/live_bets.js', 'wb').write(b)
b = get(f'{LIVE}nba/data/data.json?t={stamp}', raw=True)
if b:
    open(f'{OUT}/live_nba_data.json', 'wb').write(b)

# ESPN: last two nights of NBA games, with who played and who didn't
site = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
today = dt.datetime.utcnow().date()
for d in (today - dt.timedelta(days=2), today - dt.timedelta(days=1), today):
    sb = get(f'{site}/scoreboard?dates={d:%Y%m%d}')
    if not sb:
        continue
    json.dump(sb, open(f'{OUT}/nba_sb_{d:%Y%m%d}.json', 'w'), separators=(',', ':'))
    for ev in sb.get('events') or []:
        if ((ev.get('status') or {}).get('type') or {}).get('completed'):
            s = get(f'{site}/summary?event={ev["id"]}')
            if s:
                keep = {'header': s.get('header'), 'boxscore': s.get('boxscore')}
                json.dump(keep, open(f'{OUT}/nba_summary_{ev["id"]}.json', 'w'), separators=(',', ':'))
print('saved', sorted(os.listdir(OUT)))
