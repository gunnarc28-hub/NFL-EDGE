"""Research collection (GitHub Actions only; the dev sandbox can't reach ESPN): historical player-prop lines from ESPN's odds
records (DraftKings first, ESPN BET otherwise) for every completed NBA and NHL game since 2022-23 and every NFL game since 2023,
through yesterday. Writes probe_out/props/ for the research scripts."""
import json, os, time, datetime as dt, urllib.request, urllib.error, concurrent.futures as cf
import pandas as pd
UA = {'User-Agent': 'Mozilla/5.0 (sports-edge research)'}
os.makedirs('probe_out/props', exist_ok=True)
SPORT = {'nba': 'basketball/leagues/nba', 'nhl': 'hockey/leagues/nhl', 'nfl': 'football/leagues/nfl'}
SB = {'nba': 'basketball/nba', 'nhl': 'hockey/nhl', 'nfl': 'football/nfl'}


def get(url, timeout=40, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (i + 1))
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def note(t, m):
    print(f'::notice title={t}::{str(m)[:3000]}')


def board(lg, day):
    b = get(f'https://site.api.espn.com/apis/site/v2/sports/{SB[lg]}/scoreboard?dates={day:%Y%m%d}&limit=200')
    out = []
    for e in (json.loads(b).get('events') or []) if b else []:
        c = e['competitions'][0]; st = e.get('season') or {}
        tm = {x['homeAway']: x for x in c['competitors']}
        out.append([lg, e['id'], e['date'], st.get('year'), st.get('type'), bool(e['status']['type'].get('completed')),
                    tm['home']['team']['abbreviation'], tm['away']['team']['abbreviation'], tm['home'].get('score'), tm['away'].get('score')])
    return out


yday = dt.date.today() - dt.timedelta(days=1)
cols = ['league', 'event', 'date', 'season', 'season_type', 'completed', 'home', 'away', 'home_score', 'away_score']
for lg in ('nba', 'nhl', 'nfl'):
    p = f'research/data/{lg}_events.csv'
    old = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame(columns=cols)
    start = (pd.to_datetime(old.date).max().date() + dt.timedelta(days=1)) if len(old) else dt.date(2023, 9, 1)
    days = [start + dt.timedelta(days=i) for i in range((yday - start).days + 1)]
    with cf.ThreadPoolExecutor(16) as ex:
        new = [r for rs in ex.map(lambda d: board(lg, d), days) for r in rs]
    ev = pd.concat([old, pd.DataFrame(new, columns=cols)]).drop_duplicates('event', keep='last')
    ev.to_csv(f'probe_out/props/{lg}_events.csv', index=False)
    evs = ev[ev.season_type.astype(str).isin(['2', '3', '2.0', '3.0']) & (ev.completed.astype(str) == 'True')]
    note(f'{lg} events', f'{len(evs)} completed games, {len(new)} new from {start} to {yday}')

    def one(e):
        out = []
        for pid in ('100', '58'):
            base = f'https://sports.core.api.espn.com/v2/sports/{SPORT[lg]}/events/{e}/competitions/{e}/odds/{pid}/propBets?limit=1000'
            b = get(base)
            if not b:
                continue
            j = json.loads(b); items = j.get('items') or []
            for pg in range(2, (j.get('pageCount') or 1) + 1):
                b2 = get(f'{base}&page={pg}')
                items += (json.loads(b2).get('items') or []) if b2 else []
            for i, it in enumerate(items):
                typ = (it.get('type') or {}).get('name')
                a = ((it.get('athlete') or {}).get('$ref') or '').split('/athletes/')
                aid = a[1].split('?')[0] if len(a) > 1 else ''
                o = (it.get('odds') or {}).get('american') or {}
                cur, opn = it.get('current') or {}, it.get('open') or {}
                side = 'over' if 'over' in cur else 'under' if 'under' in cur else ''
                tgt = (cur.get('target') or {}).get('value')
                tgo = (opn.get('target') or {}).get('value')
                out.append([e, pid, i, typ, aid, side, tgt, tgo, o.get('value'), o.get('open'), it.get('lastUpdated')])
            if out:
                break                      # one book per game is plenty
        return out
    rows, t0, n_ev = [], time.time(), 0
    with cf.ThreadPoolExecutor(24) as ex:
        for r in ex.map(one, evs.event.astype(str).tolist()):
            rows += r; n_ev += bool(r)
    df = pd.DataFrame(rows, columns=['event', 'book', 'i', 'type', 'athlete', 'side', 'line', 'line_open', 'odds', 'odds_open', 'updated'])
    df.to_csv(f'probe_out/props/{lg}_props.csv.gz', index=False, compression='gzip')
    note(f'{lg} props', f'{len(df)} rows for {n_ev} of {len(evs)} games in {time.time() - t0:.0f}s; books {df.book.value_counts().to_dict()}; '
                        f'types {df.type.value_counts().head(40).to_dict()}')
