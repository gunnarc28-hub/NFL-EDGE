"""Research probe (GitHub Actions only; the dev sandbox can't reach these hosts).

Which sportsbook markets ESPN carries for upcoming NFL, NBA and NHL games (quarter, half and period lines,
first-quarter and first-half player props, first basket, early-goal props), plus one finished game's
play-by-play shape from ESPN's summary feed and the NHL's own feed, for grading. Writes probe_out/."""
import json, os, time, urllib.request, urllib.error, datetime as dt
from collections import Counter

UA = {'User-Agent': 'Mozilla/5.0 (sports-edge research)'}
os.makedirs('probe_out', exist_ok=True)
LG = {'nfl': ('football', 'nfl'), 'nba': ('basketball', 'nba'), 'nhl': ('hockey', 'nhl')}
KEYWORDS = ('quarter', 'half', 'period', '1st', '2nd', '3rd', '4th', 'first', 'minute', 'basket', 'tip', 'q1', '1h', 'team', 'race', 'score first')


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


def note(t, m):
    print(f'::notice title={t}::{str(m)[:3500]}', flush=True)


def trim(o, depth=0, max_list=6):
    """Keep a JSON sample small enough to read: short lists, no deep nesting."""
    if depth > 7:
        return '…'
    if isinstance(o, dict):
        return {k: trim(v, depth + 1, max_list) for k, v in o.items()}
    if isinstance(o, list):
        return [trim(v, depth + 1, max_list) for v in o[:max_list]] + ([f'… {len(o) - max_list} more'] if len(o) > max_list else [])
    return o


today = dt.datetime.utcnow().date()
for lg, (sp, l) in LG.items():
    core = f'https://sports.core.api.espn.com/v2/sports/{sp}/leagues/{l}'
    site = f'https://site.api.espn.com/apis/site/v2/sports/{sp}/{l}'
    pre, post = [], []
    for d in range(-2, 5):
        day = (today + dt.timedelta(days=d)).strftime('%Y%m%d')
        j = get(f'{site}/scoreboard?dates={day}&limit=100')
        for e in (j or {}).get('events', []):
            st = ((e.get('status') or {}).get('type') or {}).get('state')
            (pre if st == 'pre' else post if st == 'post' else []).append(e)
    out = {'pre': [e['id'] for e in pre][:40], 'post': [e['id'] for e in post][:40], 'odds': {}, 'props': {}, 'linescores': None, 'summary': None}
    # ---- sportsbook markets for a few upcoming games
    all_types = Counter()
    for e in pre[:4]:
        ev = e['id']
        o = get(f'{core}/events/{ev}/competitions/{ev}/odds?limit=100')
        out['odds'][ev] = trim(o, max_list=12)
        for it in (o or {}).get('items') or []:
            pv = (it.get('provider') or {})
            note(f'{lg} odds provider', f"{ev} {pv.get('id')} {pv.get('name')} keys {sorted(it.keys())}")
        for pid in ('100', '58', '40', '1002', '200', '1004'):
            pj = get(f'{core}/events/{ev}/competitions/{ev}/odds/{pid}/propBets?limit=2000')
            items = (pj or {}).get('items') or []
            if not items:
                continue
            types = Counter(((it.get('type') or {}).get('name')) for it in items)
            all_types.update({f'{pid}:{k}': v for k, v in types.items()})
            samples = {}
            for it in items:
                nm = (it.get('type') or {}).get('name') or ''
                if nm not in samples or len(samples[nm]) < 3:
                    samples.setdefault(nm, []).append(trim(it, max_list=4))
            out['props'][f'{ev}:{pid}'] = {'n': len(items), 'types': types.most_common(), 'samples': samples}
    note(f'{lg} prop types', ' | '.join(f'{k} ({v})' for k, v in all_types.most_common(200)))
    hits = [k for k in all_types if any(w in k.lower() for w in KEYWORDS)]
    note(f'{lg} quarter/half/period/first types', ' | '.join(hits) or 'none')
    # ---- a finished game: scoreboard line scores and the summary feed's play-by-play shape
    if post:
        e = post[-1]
        out['linescores'] = [{'team': (c.get('team') or {}).get('abbreviation'), 'linescores': c.get('linescores')} for c in e['competitions'][0]['competitors']]
        s = get(f'{site}/summary?event={e["id"]}')
        if s:
            keep = {k: s.get(k) for k in ('plays', 'scoringPlays', 'drives', 'boxscore', 'header')}
            out['summary'] = {'event': e['id'], 'keys': sorted(s.keys()), 'n_plays': len(s.get('plays') or []),
                              'plays_head': (s.get('plays') or [])[:12], 'scoringPlays_head': (s.get('scoringPlays') or [])[:6],
                              'drives': trim(keep.get('drives'), max_list=3), 'header': trim(keep.get('header'), max_list=3)}
            note(f'{lg} summary', f"event {e['id']} keys {sorted(s.keys())} plays {len(s.get('plays') or [])} scoringPlays {len(s.get('scoringPlays') or [])}")
    json.dump(out, open(f'probe_out/{lg}_markets.json', 'w'), indent=1, default=str)

# ---- the NHL's own feed: goal times for one finished game
sc = get('https://api-web.nhle.com/v1/score/now')
fin = [g for g in (sc or {}).get('games', []) if str(g.get('gameState')) in ('OFF', 'FINAL')]
if not fin:
    d = (today - dt.timedelta(days=1)).isoformat()
    sc = get(f'https://api-web.nhle.com/v1/score/{d}')
    fin = [g for g in (sc or {}).get('games', []) if str(g.get('gameState')) in ('OFF', 'FINAL')]
if fin:
    gid = fin[0]['id']
    land = get(f'https://api-web.nhle.com/v1/gamecenter/{gid}/landing')
    pbp = get(f'https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play')
    json.dump({'game': gid, 'landing_summary': trim((land or {}).get('summary'), max_list=8),
               'pbp_keys': sorted((pbp or {}).keys()), 'pbp_goals': [p for p in (pbp or {}).get('plays', []) if p.get('typeDescKey') == 'goal'][:6]},
              open('probe_out/nhl_feed.json', 'w'), indent=1, default=str)
    note('nhl feed', f'game {gid} landing keys {sorted((land or {}).keys())}')
