"""Research probe (GitHub Actions only): shared DraftKings bets and what's needed to enter them in Sports Edge.
For each post key in probe_posts.txt: the bet DraftKings attached to it (the comments service answers when asked the
way its own social pages ask). Plus the live site's grade files and ESPN's NBA scoreboards for the last four days and
the next two, to match games and players. Writes probe_out/raw/."""
import os, re, json, base64, time, datetime as dt, urllib.request, urllib.error
OUT = 'probe_out/raw'; os.makedirs(OUT, exist_ok=True)
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'
LIVE = 'https://gunnarc28-hub.github.io/NFL-EDGE/'
log = []


def req(url, body=None, dk=False):
    h = {'User-Agent': UA, 'Accept': 'application/json, text/plain, */*', 'Accept-Language': 'en-US,en;q=0.9'}
    if dk:
        h.update({'Origin': 'https://sportsbook.draftkings.com', 'Referer': 'https://sportsbook.draftkings.com/social'})
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h['Content-Type'] = 'application/json'
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=40) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404, 422):
                return e.code, b''
        except Exception:
            pass
        time.sleep(2 * (i + 1))
    return 0, b''


keys = [k.strip() for k in open('probe_posts.txt').read().split() if k.strip()] if os.path.exists('probe_posts.txt') else []
for k in keys:
    m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', k)
    if not m:
        continue
    pk = m.group(1)
    st, b = req('https://api.draftkings.com/comments/feed/post/details.json', {'postKey': pk}, dk=True)
    log.append(f'post {pk} {st} {len(b)}')
    if st != 200:
        continue
    d = json.loads(b)
    for i, pe in enumerate((d.get('post') or {}).get('postEntries') or []):
        props = (pe.get('metadataProperties') or {}).get('properties') or {}
        if props.get('name') == 'betJSON':
            v = props['value']; bet = json.loads(base64.b64decode(v + '=' * (-len(v) % 4)))
            json.dump(bet, open(f'{OUT}/dk_{pk[:8]}_{i}.json', 'w'), indent=1)
            log.append(f'  bet {bet.get("betId")} {bet.get("type")} {bet.get("status")} stake {bet.get("stake")} odds {bet.get("originalDisplayOdds")}')
stamp = int(time.time())
for sp in ('nba', 'nhl', 'nfl'):
    st, b = req(f'{LIVE}{sp}/data/grade.json?t={stamp}')
    if st == 200:
        open(f'{OUT}/live_{sp}_grade.json', 'wb').write(b)
    log.append(f'live {sp} grade {st} {len(b)}')
today = dt.datetime.utcnow().date()
for d in range(-4, 3):
    day = today + dt.timedelta(days=d)
    st, b = req(f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={day:%Y%m%d}')
    if st == 200:
        j = json.loads(b)
        keep = {'events': [{'id': e['id'], 'date': e['date'], 'competitions': [{'competitors': [{'homeAway': c['homeAway'], 'team': {'abbreviation': c['team']['abbreviation']}} for c in e['competitions'][0]['competitors']]}]} for e in j.get('events') or []]}
        json.dump(keep, open(f'{OUT}/nba_sb_{day:%Y%m%d}.json', 'w'))
open(f'{OUT}/log.txt', 'w').write('\n'.join(log))
print('\n'.join(log))
