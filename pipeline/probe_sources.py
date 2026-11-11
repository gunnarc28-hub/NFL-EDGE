"""Research probe (GitHub Actions only): the live site's NBA data, plus ESPN game logs for one player. Writes probe_out/raw/."""
import os, json, time, urllib.request
OUT = 'probe_out/raw'; os.makedirs(OUT, exist_ok=True)
LIVE = 'https://gunnarc28-hub.github.io/NFL-EDGE/'
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'
log = []; t = int(time.time())
def get(u, name):
    try:
        b = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=60).read()
        open(f'{OUT}/{name}', 'wb').write(b); log.append(f'{name} {len(b)}'); return b
    except Exception as e:
        log.append(f'{name} {e}')
for sp in ('nba', 'nhl'):
    get(f'{LIVE}{sp}/data/data.json?t={t}', f'{sp}_data.json')
try:
    d = json.load(open(f'{OUT}/nba_data.json'))
    for p in d['props']:
        if 'Spencer' in p['name']:
            get(f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{p['id']}/gamelog", f"gl_{p['id']}.json")
            get(f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{p['id']}/gamelog?season=2026", f"gl_{p['id']}_2026.json")
except Exception as e:
    log.append(f'spencer {e}')
open(f'{OUT}/log.txt', 'w').write('\n'.join(log)); print('\n'.join(log))
