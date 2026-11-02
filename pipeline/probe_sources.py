"""Research probe (GitHub Actions only): the live site's data for tonight's slate. Writes probe_out/raw/."""
import os, json, time, urllib.request
OUT = 'probe_out/raw'; os.makedirs(OUT, exist_ok=True)
LIVE = 'https://gunnarc28-hub.github.io/NFL-EDGE/'
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'
log = []; t = int(time.time())
for sp in ('nba', 'nhl', 'nfl'):
    for f in ('data.json', 'summary.json'):
        try:
            b = urllib.request.urlopen(urllib.request.Request(f'{LIVE}{sp}/data/{f}?t={t}', headers={'User-Agent': UA}), timeout=60).read()
            open(f'{OUT}/{sp}_{f}', 'wb').write(b); log.append(f'{sp} {f} {len(b)}')
        except Exception as e:
            log.append(f'{sp} {f} {e}')
open(f'{OUT}/log.txt', 'w').write('\n'.join(log)); print('\n'.join(log))
