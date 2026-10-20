"""One-off check of the live injury sources from GitHub Actions (the dev sandbox can't reach them).
Prints GitHub annotations so the results can be read back through the API."""
import collections, json, re, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (nfl-edge data refresh)', 'Accept': '*/*'}


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read().decode('utf-8', 'replace')


def note(title, msg):
    msg = str(msg).replace('\n', ' ').replace('\r', ' ')
    print(f'::notice title={title}::{msg[:3500]}')


def trim(o, n=90):
    if isinstance(o, dict):
        return {k: trim(v, n) for k, v in o.items() if k not in ('links', 'headshot', 'logos')}
    if isinstance(o, list):
        return [trim(v, n) for v in o[:3]]
    if isinstance(o, str) and len(o) > n:
        return o[:n] + '…'
    return o


try:
    st, hd, body = get('https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries')
    d = json.loads(body)
    teams = d.get('injuries', []) or []
    items = [it for t in teams for it in (t.get('injuries') or [])]
    stc = collections.Counter(str(it.get('status')) for it in items)
    tyc = collections.Counter(str((it.get('type') or {}).get('name')) for it in items)
    dates = sorted(str(it.get('date')) for it in items if it.get('date'))
    ret = sum(1 for it in items if (it.get('details') or {}).get('returnDate'))
    cors = {k: v for k, v in hd.items() if k.lower().startswith('access-control') or k.lower() in ('cache-control', 'age', 'last-modified')}
    note('ESPN injuries', f'HTTP {st}; top keys {list(d.keys())}; {len(teams)} teams; {len(items)} items; statuses {dict(stc)}; '
                          f'types {dict(tyc)}; newest {dates[-1] if dates else None}; oldest {dates[0] if dates else None}; with returnDate {ret}; headers {cors}')
    note('ESPN team keys', f'{list(teams[0].keys()) if teams else None}; first team {trim({k: v for k, v in teams[0].items() if k != "injuries"}) if teams else None}')
    recent = sorted(items, key=lambda it: str(it.get('date')), reverse=True)
    note('ESPN newest items', json.dumps([trim(x) for x in recent[:2]]))
    note('ESPN date spread', json.dumps(collections.Counter(str(it.get('date'))[:10] for it in items).most_common(12)))
except Exception as e:
    print(f'::warning title=ESPN injuries failed::{e!r}')

for url in ('https://www.nfl.com/injuries/league/2026/REG7', 'https://www.nfl.com/injuries/league/2026/REG6'):
    try:
        st, hd, body = get(url)
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.S)
        txt = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', r)).strip() for r in rows]
        note('NFL.com ' + url[-4:], f'HTTP {st}; {len(body)} bytes; {body.count("<table")} tables; {len(rows)} rows; first rows {txt[:6]}')
    except Exception as e:
        print(f'::warning title=NFL.com {url[-4:]} failed::{e!r}')
