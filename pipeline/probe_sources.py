"""Research probe (GitHub Actions only; the dev sandbox can't reach these hosts): raw ESPN and NHL feeds saved as test
fixtures for the quarter, half and period markets. For each sport: scoreboards from two days back to three ahead, every
page of prop bets for two upcoming games, and the summary (play-by-play) of a finished game; for the NHL also the NHL's
landing page for that game. Writes probe_out/raw/."""
import json, os, time, urllib.request, urllib.error, datetime as dt
UA = {'User-Agent': 'Mozilla/5.0 (sports-edge research)'}
OUT = 'probe_out/raw'; os.makedirs(OUT, exist_ok=True)
LG = {'nfl': ('football', 'nfl'), 'nba': ('basketball', 'nba'), 'nhl': ('hockey', 'nhl')}


def get(url, timeout=40, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(2 * (i + 1))
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in ('links', 'headshot', 'logos', 'logo', 'videos', 'news', 'article')}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


def save(name, obj):
    json.dump(strip(obj), open(f'{OUT}/{name}', 'w'), separators=(',', ':'))


today = dt.datetime.utcnow().date()
for lg, (sp, l) in LG.items():
    core = f'https://sports.core.api.espn.com/v2/sports/{sp}/leagues/{l}'
    site = f'https://site.api.espn.com/apis/site/v2/sports/{sp}/{l}'
    pre, post = [], []
    for d in range(-3, 4):
        day = (today + dt.timedelta(days=d)).strftime('%Y%m%d')
        j = get(f'{site}/scoreboard?dates={day}&limit=100')
        if j:
            save(f'{lg}_sb_{day}.json', j)
        for e in (j or {}).get('events', []):
            st = ((e.get('status') or {}).get('type') or {}).get('state')
            if st == 'pre': pre.append(e['id'])
            if st == 'post': post.append(e['id'])
    for ev in pre[:3]:
        for pid in ('100',):
            items, page, pc = [], 1, 1
            while page <= 8:
                j = get(f'{core}/events/{ev}/competitions/{ev}/odds/{pid}/propBets?limit=1000&page={page}')
                if not j:
                    break
                save(f'{lg}_props_{ev}_{pid}_p{page}.json', j)
                pc = j.get('pageCount') or 1
                if page >= pc:
                    break
                page += 1
            print(f'::notice title={lg} props::{ev} pages {pc}')
        o = get(f'{core}/events/{ev}/competitions/{ev}/odds')
        if o:
            save(f'{lg}_odds_{ev}.json', o)
    for ev in post[-2:]:
        s = get(f'{site}/summary?event={ev}')
        if s:
            save(f'{lg}_summary_{ev}.json', s)
            print(f'::notice title={lg} summary::{ev} plays {len(s.get("plays") or [])}')
sc = get(f'https://api-web.nhle.com/v1/score/{(today - dt.timedelta(days=1)).isoformat()}')
for g in (sc or {}).get('games', [])[:3]:
    land = get(f'https://api-web.nhle.com/v1/gamecenter/{g["id"]}/landing')
    if land:
        save(f'nhl_landing_{g["id"]}.json', land)
open('probe_out/when.txt', 'w').write(dt.datetime.utcnow().isoformat())
