"""One-off research collection (GitHub Actions only; the dev sandbox can't reach these hosts):
historical player-prop lines from ESPN's odds records for every completed NBA and NHL game since 2022-23,
plus names for the NHL athletes in them. Writes probe_out/ for the research scripts."""
import json, os, time, gzip, csv, io, urllib.request, concurrent.futures as cf
import pandas as pd
UA = {'User-Agent': 'Mozilla/5.0 (sports-edge research)'}
os.makedirs('probe_out/props', exist_ok=True)
SPORT = {'nba': 'basketball/leagues/nba', 'nhl': 'hockey/leagues/nhl'}
KEEP = {
    'nba': ['Total Points', 'Total Rebounds', 'Total Assists', 'Total 3-Point Field Goals', 'Total Points, Rebounds, and Assists', 'Total Points and Rebounds',
            'Total Points and Assists', 'Total Assists and Rebounds', 'Total Steals', 'Total Blocks', 'Total Turnovers', 'To Record a Double Double',
            'To Record a Triple Double', 'Points Milestones', 'Rebounds Milestones', 'Assists Milestones', '3-Point Field Goals Milestones',
            'Points + Assists + Rebounds Milestones', 'Points + Rebounds Milestones', 'Points + Assists Milestones', 'Rebounds + Assists Milestones',
            'Steals Milestones', 'Blocks Milestones', 'First Basket'],
    'nhl': ['Anytime Goalscorer', 'First Goalscorer', 'To Score 2+ Goals', 'To Score 3+ Goals', 'Total Points', 'Total Assists', 'Total Shots on Goal',
            'Shots on Goal Milestones', 'Points Milestones', 'Assists Milestones', 'Goals Milestones', 'Total Saves', 'Goalkeeper Saves Milestones',
            'Total Blocked Shots', 'Blocked Shots Milestones', 'Powerplay Points Milestones']}


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


ath = {}
for lg in ('nba', 'nhl'):
    evs = pd.read_csv(f'research/data/{lg}_events.csv')
    evs = evs[evs.season_type.isin([2, 3]) & (evs.completed == True)]
    keep = set(KEEP[lg])

    def one(ev):
        out = []
        for pid in ('100', '58'):
            b = get(f'https://sports.core.api.espn.com/v2/sports/{SPORT[lg]}/events/{ev}/competitions/{ev}/odds/{pid}/propBets?limit=1000')
            if not b:
                continue
            items = json.loads(b).get('items') or []
            for i, it in enumerate(items):
                typ = (it.get('type') or {}).get('name')
                if typ not in keep:
                    continue
                a = ((it.get('athlete') or {}).get('$ref') or '').split('/athletes/')
                aid = a[1].split('?')[0] if len(a) > 1 else ''
                o = (it.get('odds') or {}).get('american') or {}
                tgt = ((it.get('current') or {}).get('target') or {}).get('value')
                tgo = ((it.get('open') or {}).get('target') or {}).get('value')
                out.append([ev, pid, i, typ, aid, tgt, tgo, o.get('value'), o.get('open')])
            if out:
                break                      # one book per game is plenty
        return out
    rows, t0, n_ev = [], time.time(), 0
    with cf.ThreadPoolExecutor(20) as ex:
        for r in ex.map(one, evs.event.astype(str).tolist()):
            rows += r; n_ev += bool(r)
    df = pd.DataFrame(rows, columns=['event', 'book', 'i', 'type', 'athlete', 'line', 'line_open', 'odds', 'odds_open'])
    df.to_csv(f'probe_out/props/{lg}_props.csv.gz', index=False, compression='gzip')
    ev_season = evs.set_index(evs.event.astype(str)).season.to_dict()
    df['season'] = df.event.astype(str).map(ev_season)
    note(f'{lg} props', f'{len(df)} rows for {n_ev} of {len(evs)} games in {time.time() - t0:.0f}s; by season {df.groupby("season").event.nunique().to_dict()}; '
                        f'books {df.book.value_counts().to_dict()}; types {df.type.value_counts().head(30).to_dict()}')
    if lg == 'nhl':
        ids = sorted(set(df.athlete) - {''})

        def nm(aid):
            b = get(f'https://sports.core.api.espn.com/v2/sports/{SPORT[lg]}/athletes/{aid}')
            if not b:
                return [aid, '', '', '']
            j = json.loads(b)
            return [aid, j.get('fullName') or j.get('displayName') or '', (j.get('position') or {}).get('abbreviation') or '', j.get('dateOfBirth') or '']
        with cf.ThreadPoolExecutor(20) as ex:
            names = list(ex.map(nm, ids))
        pd.DataFrame(names, columns=['athlete', 'name', 'pos', 'dob']).to_csv('probe_out/props/nhl_athletes.csv', index=False)
        note('nhl athletes', f'{len(names)} ids, {sum(1 for n in names if n[1])} named')
