"""One-off: fetch historical NBA/NHL closing odds (Sportsbook Review archives via the Internet Archive) and test ESPN's
core odds endpoint for past games. Saves to probe_out/ (CSV conversions of the spreadsheets)."""
import json, os, urllib.request, urllib.parse, time
import pandas as pd
UA = {'User-Agent': 'Mozilla/5.0 (sports-edge research)'}
os.makedirs('probe_out/sbr', exist_ok=True)


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def note(t, m):
    print(f'::notice title={t}::{str(m)[:3000]}')


got = []
for lg in ('nba', 'nhl'):
    for y in range(2007, 2024):
        season = f'{y}-{str(y + 1)[2:]}'
        done = False
        for ext in ('xlsx', 'xls'):
            orig = f'sportsbookreviewsonline.com/scoresoddsarchives/{lg}/{lg}%20odds%20{season}.{ext}'
            try:
                av = json.loads(get('https://archive.org/wayback/available?url=' + urllib.parse.quote(orig, safe='/%')))
                snap = (av.get('archived_snapshots') or {}).get('closest') or {}
                if not snap.get('available'):
                    continue
                ts = snap['timestamp']
                raw = get(f'https://web.archive.org/web/{ts}id_/https://{orig}', timeout=120)
                fn = f'probe_out/sbr/{lg}_{season}.{ext}'
                open(fn, 'wb').write(raw)
                df = pd.read_excel(fn)
                df.to_csv(f'probe_out/sbr/{lg}_{season}.csv', index=False)
                os.remove(fn)
                got.append(f'{lg} {season} {ext} snap {ts} rows {len(df)}')
                done = True
                break
            except Exception as e:
                got.append(f'{lg} {season} {ext} failed {e!r}'[:160])
            time.sleep(1)
note('SBR archives', ' | '.join(got))
# ESPN core odds for past games
for lg, path, ev in (('nba', 'basketball/leagues/nba', '401705127'), ('nhl', 'hockey/leagues/nhl', '401688304'), ('nba', 'basketball/leagues/nba', '401585000')):
    try:
        u = f'https://sports.core.api.espn.com/v2/sports/{path}/events/{ev}/competitions/{ev}/odds'
        b = get(u); open(f'probe_out/core_odds_{lg}_{ev}.json', 'wb').write(b)
        j = json.loads(b); note(f'core odds {lg} {ev}', f'count {j.get("count")} items {len(j.get("items", []))} {b[:600]}')
    except Exception as e:
        print(f'::warning title=core odds {lg} {ev}::{e!r}')
