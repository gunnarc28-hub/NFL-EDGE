"""One-off research collection (GitHub Actions only; the dev sandbox can't reach these hosts):
  - closing odds for every NBA and NHL game since 2022-23 from ESPN's odds records (open and close, several books)
  - Sportsbook Review season archives (via the Internet Archive) that failed on the first try
  - a look at ESPN player-prop odds records
Writes probe_out/ for the research scripts."""
import json, os, time, urllib.request, urllib.parse, concurrent.futures as cf, csv, datetime as dt
import pandas as pd
UA = {'User-Agent': 'Mozilla/5.0 (sports-edge research)'}
os.makedirs('probe_out/odds', exist_ok=True); os.makedirs('probe_out/sbr', exist_ok=True)


def get(url, timeout=40, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
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


def amer(x):
    try:
        s = str(x).replace('+', '')
        if s in ('', 'EVEN', 'even'): return 100.0 if s else None
        return float(s)
    except Exception:
        return None


def parse_odds(league, ev, j):
    rows = []
    for it in (j or {}).get('items', []):
        p = it.get('provider') or {}
        h, a = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
        def g(side, when, k1, k2='american'):
            return ((side.get(when) or {}).get(k1) or {}).get(k2)
        tot = lambda when, k: ((it.get(when) or {}).get(k) or {}).get('american')
        rows.append({'league': league, 'event': ev, 'provider_id': p.get('id'), 'provider': p.get('name'), 'details': it.get('details'),
                     'spread': it.get('spread'), 'over_under': it.get('overUnder'),
                     'h_ml': h.get('moneyLine'), 'a_ml': a.get('moneyLine'), 'h_sp_odds': h.get('spreadOdds'), 'a_sp_odds': a.get('spreadOdds'),
                     'over_odds': it.get('overOdds'), 'under_odds': it.get('underOdds'),
                     'h_line_open': amer(g(h, 'open', 'pointSpread')), 'h_line_close': amer(g(h, 'close', 'pointSpread')),
                     'a_line_open': amer(g(a, 'open', 'pointSpread')), 'a_line_close': amer(g(a, 'close', 'pointSpread')),
                     'h_sp_open_odds': amer(g(h, 'open', 'spread')), 'h_sp_close_odds': amer(g(h, 'close', 'spread')),
                     'a_sp_open_odds': amer(g(a, 'open', 'spread')), 'a_sp_close_odds': amer(g(a, 'close', 'spread')),
                     'h_ml_open': amer(g(h, 'open', 'moneyLine')), 'h_ml_close': amer(g(h, 'close', 'moneyLine')),
                     'a_ml_open': amer(g(a, 'open', 'moneyLine')), 'a_ml_close': amer(g(a, 'close', 'moneyLine')),
                     'total_open': amer(tot('open', 'total')), 'total_close': amer(tot('close', 'total')),
                     'over_open_odds': amer(tot('open', 'over')), 'over_close_odds': amer(tot('close', 'over')),
                     'under_open_odds': amer(tot('open', 'under')), 'under_close_odds': amer(tot('close', 'under'))})
    return rows


SPORT = {'nba': 'basketball/leagues/nba', 'nhl': 'hockey/leagues/nhl'}
SITE = {'nba': 'basketball/nba', 'nhl': 'hockey/nhl'}
# ---------------------------------------------------------------- event lists from ESPN scoreboards, one request per day
events = {'nba': [], 'nhl': []}
for lg in ('nba', 'nhl'):
    d0, d1 = dt.date(2022, 10, 1), dt.date.today()
    days = [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]
    days = [d for d in days if d.month not in (7, 8, 9) or (lg == 'nhl' and d.month == 9 and d.day >= 25)]
    def sb(d):
        b = get(f'https://site.api.espn.com/apis/site/v2/sports/{SITE[lg]}/scoreboard?dates={d:%Y%m%d}&limit=100')
        out = []
        if b:
            for ev in json.loads(b).get('events', []):
                c = (ev.get('competitions') or [{}])[0]; t = {x.get('homeAway'): x for x in c.get('competitors', [])}
                h, a = t.get('home') or {}, t.get('away') or {}
                out.append({'league': lg, 'event': ev['id'], 'date': ev.get('date'), 'season': (ev.get('season') or {}).get('year'),
                            'season_type': (ev.get('season') or {}).get('type'), 'completed': c.get('status', {}).get('type', {}).get('completed'),
                            'home': (h.get('team') or {}).get('abbreviation'), 'away': (a.get('team') or {}).get('abbreviation'),
                            'home_score': h.get('score'), 'away_score': a.get('score')})
        return out
    with cf.ThreadPoolExecutor(12) as ex:
        for out in ex.map(sb, days):
            events[lg] += out
    pd.DataFrame(events[lg]).drop_duplicates('event').to_csv(f'probe_out/odds/{lg}_events.csv', index=False)
    note(f'{lg} events', f'{len(events[lg])} events over {len(days)} days')
# ---------------------------------------------------------------- odds per event
for lg in ('nba', 'nhl'):
    evs = pd.read_csv(f'probe_out/odds/{lg}_events.csv')
    evs = evs[evs.season_type.isin([2, 3])]
    def one(ev):
        b = get(f'https://sports.core.api.espn.com/v2/sports/{SPORT[lg]}/events/{ev}/competitions/{ev}/odds?limit=50')
        return parse_odds(lg, ev, json.loads(b)) if b else []
    rows = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(16) as ex:
        for r in ex.map(one, evs.event.astype(str).tolist()):
            rows += r
    df = pd.DataFrame(rows)
    df.to_csv(f'probe_out/odds/{lg}_odds.csv', index=False)
    note(f'{lg} odds', f'{len(df)} rows for {df.event.nunique() if len(df) else 0} of {len(evs)} games in {time.time() - t0:.0f}s; providers {df.provider.value_counts().head(8).to_dict() if len(df) else {}}')
# ---------------------------------------------------------------- player-prop odds records (a look)
for lg in ('nba', 'nhl'):
    evs = pd.read_csv(f'probe_out/odds/{lg}_events.csv')
    for ev in evs[evs.completed == True].event.astype(str).tail(2).tolist() + evs[evs.completed != True].event.astype(str).head(1).tolist():
        for pid in ('58', '100'):
            b = get(f'https://sports.core.api.espn.com/v2/sports/{SPORT[lg]}/events/{ev}/competitions/{ev}/odds/{pid}/propBets?limit=1000')
            if b:
                open(f'probe_out/odds/{lg}_props_{ev}_{pid}.json', 'wb').write(b)
                j = json.loads(b); note(f'{lg} props {ev} {pid}', f'count {j.get("count")} sample {json.dumps((j.get("items") or [None])[0])[:900]}')
# ---------------------------------------------------------------- Sportsbook Review archives that failed before
got = []
for lg, seasons in (('nhl', ['2012-13', '2014-15', '2015-16', '2017-18', '2019-20', '2020-21', '2022-23']), ('nba', ['2022-23'])):
    for season in seasons:
        orig = f'sportsbookreviewsonline.com/scoresoddsarchives/{lg}/{lg}%20odds%20{season}.xlsx'
        try:
            av = get('https://archive.org/wayback/available?url=' + urllib.parse.quote(orig, safe='/%'))
            snap = (json.loads(av).get('archived_snapshots') or {}).get('closest') or {} if av else {}
            if not snap.get('available'):
                got.append(f'{lg} {season}: no snapshot'); continue
            raw = get(f'https://web.archive.org/web/{snap["timestamp"]}id_/https://{orig}', timeout=120, tries=6)
            if not raw:
                got.append(f'{lg} {season}: download failed'); continue
            fn = f'probe_out/sbr/{lg}_{season}.xlsx'; open(fn, 'wb').write(raw)
            pd.read_excel(fn).to_csv(f'probe_out/sbr/{lg}_{season}.csv', index=False); os.remove(fn)
            got.append(f'{lg} {season}: ok')
        except Exception as e:
            got.append(f'{lg} {season}: {e!r}'[:120])
        time.sleep(3)
note('SBR retry', ' | '.join(got))
