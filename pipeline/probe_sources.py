"""One-off check of NBA and NHL sources from GitHub Actions (the dev sandbox can't reach them). Saves raw copies to probe_out/."""
import json, os, re, urllib.request, collections
UA = {'User-Agent': 'Mozilla/5.0 (sports-edge data refresh)', 'Accept': '*/*'}
os.makedirs('probe_out', exist_ok=True)


def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read()


def note(title, msg):
    print(f'::notice title={title}::{str(msg).replace(chr(10), " ")[:3000]}')


def save(name, url):
    try:
        st, hd, body = get(url)
        open(f'probe_out/{name}', 'wb').write(body)
        note(name, f'HTTP {st} {len(body)} bytes cors={hd.get("Access-Control-Allow-Origin")}')
        return body
    except Exception as e:
        print(f'::warning title={name}::{e!r}')
        return None


E = 'https://site.api.espn.com/apis/site/v2/sports'
for lg, path in (('nba', 'basketball/nba'), ('nhl', 'hockey/nhl')):
    for d in ('20200115', '20220115', '20250115', '20260115', ''):
        b = save(f'{lg}_sb_{d or "today"}.json', f'{E}/{path}/scoreboard' + (f'?dates={d}' if d else ''))
        if b and d == '20250115':
            j = json.loads(b); ev = (j.get('events') or [{}])[0]
            save(f'{lg}_summary_{ev.get("id")}.json', f'{E}/{path}/summary?event={ev.get("id")}')
    save(f'{lg}_sb_range_202501.json', f'{E}/{path}/scoreboard?dates=20250101-20250131&limit=1000')
    save(f'{lg}_injuries.json', f'{E}/{path}/injuries')
save('nhl_api_schedule_now.json', 'https://api-web.nhle.com/v1/schedule/now')
b = save('nhl_api_partner_odds_us.json', 'https://api-web.nhle.com/v1/partner-game/US/now')
try:
    j = json.load(open('probe_out/nhl_api_schedule_now.json'))
    gid = j['gameWeek'][0]['games'][0]['id']
    save(f'nhl_api_landing_{gid}.json', f'https://api-web.nhle.com/v1/gamecenter/{gid}/landing')
except Exception as e:
    print(f'::warning title=nhl landing::{e!r}')
save('dailyfaceoff_goalies.html', 'https://www.dailyfaceoff.com/starting-goalies/')
