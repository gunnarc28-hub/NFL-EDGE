"""Shared pieces of the NBA and NHL builds: downloads, ESPN feeds (scoreboard, odds, player-prop lines, injuries),
time helpers and JSON output. The NFL build (build.py) predates this and keeps its own copies."""
import os, re, json, math, time, gzip, datetime as dt, urllib.request, urllib.error, concurrent.futures as cf
import numpy as np, pandas as pd

UA = {'User-Agent': 'Mozilla/5.0 (sports-edge refresh; +https://github.com/gunnarc28-hub/NFL-EDGE)'}
ESPN_SITE = {'nba': 'basketball/nba', 'nhl': 'hockey/nhl', 'nfl': 'football/nfl'}
ESPN_CORE = {'nba': 'basketball/leagues/nba', 'nhl': 'hockey/leagues/nhl', 'nfl': 'football/leagues/nfl'}
SDV = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download'
ET = 'America/New_York'


def log(*a):
    print(*a, flush=True)


def notice(title, msg):
    print(f'::notice title={title}::{str(msg)[:3000]}', flush=True)


def day_lists(items, n, per_player, kinds=None):
    """High-chance and long-shot lists, best first: the regular list across every day (n long, at most per_player entries
    per player; those get top=1) plus the same cut made within each day, so a day picked on the page still has a full
    list. kinds limits the per-player cap to entries of those kinds (None: every entry, by its id)."""
    def cut(lst):
        seen, out = {}, []
        for x in sorted(lst, key=lambda x: -x['p']):
            pid = x.get('id') if kinds is None or x.get('kind') in kinds else None
            if pid is not None:
                if seen.get(pid, 0) >= per_player:
                    continue
                seen[pid] = seen.get(pid, 0) + 1
            out.append(x)
            if len(out) >= n:
                break
        return out
    keep = {}
    for x in cut(items):
        x['top'] = 1
        keep[id(x)] = x
    for d in sorted({x['day'] for x in items}):
        for x in cut([x for x in items if x['day'] == d]):
            keep.setdefault(id(x), x)
    return sorted(keep.values(), key=lambda x: -x['p'])


def league_ranks(stats, dirs, nd=4):
    """League ranks per stat, ties sharing a rank (1, 2, 2, 4). stats: {team: {stat: value}}; dirs[stat] False ranks
    the lowest value first, True or None (ranked by size) the highest. Values are compared at nd decimals."""
    ranks = {t: {} for t in stats}
    for k, hi in dirs.items():
        vals = []
        for t, v in stats.items():
            x = v.get(k)
            if x is not None and math.isfinite(float(x)):
                vals.append((round(float(x), nd), t))
        vals.sort(key=lambda a: -a[0] if hi in (True, None) else a[0])
        prev, r = None, 0
        for i, (x, t) in enumerate(vals):
            if x != prev:
                r, prev = i + 1, x
            ranks[t][k] = r
    return ranks


_FIX = None


def _fixture(url):
    """Tests: SE_FIXTURES names a JSON file of [url regex, local file] pairs that stand in for the network."""
    global _FIX
    if _FIX is None:
        p = os.environ.get('SE_FIXTURES')
        _FIX = json.load(open(p)) if p else []
    import re as _re
    for pat, path in _FIX:
        if _re.search(pat, url):
            return open(path, 'rb').read() if path else b''
    return None


def fetch(url, timeout=60, tries=3, quiet=False):
    """Bytes at url, or None. 404s don't retry."""
    if os.environ.get('SE_FIXTURES'):
        b = _fixture(url)
        if b is not None:
            return b or None
        if 'github.com' not in url:
            return None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            time.sleep(2 * (i + 1))
        except Exception as e:
            if i == tries - 1 and not quiet:
                log('unavailable:', url[:120], repr(e)[:120])
            time.sleep(2 * (i + 1))
    return None


def get_json(url, timeout=30, tries=3, quiet=False):
    b = fetch(url, timeout, tries, quiet)
    if not b:
        return None
    try:
        return json.loads(b)
    except Exception:
        return None


def sdv_csv(tag, fname, cache, max_age_min=20, required=True):
    """A sportsdataverse release file (refreshed daily upstream), cached for a few minutes between local runs."""
    os.makedirs(cache, exist_ok=True)
    dest = os.path.join(cache, f'{tag}_{fname}')
    if os.path.exists(dest) and time.time() - os.path.getmtime(dest) < max_age_min * 60:
        return dest
    b = fetch(f'{SDV}/{tag}/{fname}', timeout=180)
    if b:
        with open(dest + '.part', 'wb') as f:
            f.write(b)
        os.replace(dest + '.part', dest)
        return dest
    if os.path.exists(dest):
        log('using cached', dest)
        return dest
    if required:
        raise SystemExit(f'Could not download {tag}/{fname}')
    return None


def amer(x):
    """American odds from ESPN's many spellings ('+114', 'EVEN', -110, '-110.0')."""
    if x is None:
        return None
    s = str(x).strip().replace('+', '')
    if s.lower() in ('even', 'ev', 'pk'):
        return 100
    try:
        v = float(s)
    except ValueError:
        return None
    if not math.isfinite(v) or abs(v) < 100:
        return None
    return int(round(v))


def num(x):
    try:
        v = float(str(x).replace('+', ''))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def et_day(ts):
    """US Eastern calendar day (YYYY-MM-DD) of a timestamp; slates are Eastern days."""
    return pd.Timestamp(ts).tz_convert(ET).date().isoformat() if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).tz_localize('UTC').tz_convert(ET).date().isoformat()


def slate_day(now):
    """The day the site leads with: today's Eastern date, until 5am Eastern when last night's games are done."""
    loc = pd.Timestamp(now).tz_convert(ET)
    return (loc - pd.Timedelta(hours=5)).date().isoformat()


# ---------------------------------------------------------------- ESPN feeds
def scoreboard(lg, day):
    """Events on an Eastern day: id, start, status, teams, scores, probable goalies (NHL)."""
    j = get_json(f'https://site.api.espn.com/apis/site/v2/sports/{ESPN_SITE[lg]}/scoreboard?dates={day.replace("-", "")}&limit=100', quiet=True)
    out = []
    for ev in (j or {}).get('events', []):
        try:
            c = (ev.get('competitions') or [{}])[0]
            st = ((c.get('status') or ev.get('status') or {}).get('type')) or {}
            t = {x.get('homeAway'): x for x in c.get('competitors', [])}
            h, a = t.get('home') or {}, t.get('away') or {}
            def side(x):
                tm = x.get('team') or {}
                rec = {r.get('type') or r.get('name'): r.get('summary') for r in x.get('records') or []}
                prob = None
                for p in x.get('probables') or []:
                    ath = p.get('athlete') or {}
                    prob = {'id': str(ath.get('id') or p.get('playerId') or ''), 'name': ath.get('displayName') or ath.get('fullName'),
                            'status': ((p.get('status') or {}).get('name')) or ''}
                return {'abbr': tm.get('abbreviation'), 'name': tm.get('displayName'), 'short': tm.get('shortDisplayName') or tm.get('name'),
                        'color': tm.get('color'), 'alt': tm.get('alternateColor'), 'espn_id': str(tm.get('id') or ''),
                        'score': num(x.get('score')), 'rec': rec, 'probable': prob,
                        'ls': [num(v.get('value')) for v in x.get('linescores') or []]}      # points by quarter / period, overtime last
            out.append({'id': str(ev['id']), 'date': ev.get('date'), 'state': st.get('state'), 'completed': bool(st.get('completed')),
                        'detail': st.get('shortDetail') or st.get('detail') or '', 'neutral': bool(c.get('neutralSite')),
                        'season_type': (ev.get('season') or {}).get('type'), 'venue': ((c.get('venue') or {}).get('fullName')) or '',
                        'home': side(h), 'away': side(a)})
        except Exception as e:
            log('scoreboard event skipped', repr(e)[:100])
    return out


def _side_odds(team_odds, when):
    x = (team_odds or {}).get(when) or {}
    return x


def game_odds(lg, ev):
    """Main lines for one event from ESPN's odds records: home spread, total, moneylines with prices, open and current."""
    j = get_json(f'https://sports.core.api.espn.com/v2/sports/{ESPN_CORE[lg]}/events/{ev}/competitions/{ev}/odds?limit=20', quiet=True)
    items = (j or {}).get('items') or []
    if not items:
        return None
    pref = {'100': 0, '58': 1}
    items.sort(key=lambda it: pref.get(str((it.get('provider') or {}).get('id')), 9))
    for it in items:
        h, a = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
        spread = num(it.get('spread'))
        total = num(it.get('overUnder'))
        mlh, mla = amer(h.get('moneyLine')), amer(a.get('moneyLine'))
        if spread is None and total is None and mlh is None:
            continue
        def ln(side, when, key):
            return ((side.get(when) or {}).get(key) or {})
        o = {'book': (it.get('provider') or {}).get('name') or '', 'book_id': str((it.get('provider') or {}).get('id') or ''),
             'spread': spread, 'total': total, 'ml_h': mlh, 'ml_a': mla,
             'sp_h': amer(h.get('spreadOdds')), 'sp_a': amer(a.get('spreadOdds')), 'o': amer(it.get('overOdds')), 'u': amer(it.get('underOdds')),
             'spread_open': num(ln(h, 'open', 'pointSpread').get('american')), 'total_open': num(((it.get('open') or {}).get('total') or {}).get('american')),
             'ml_h_open': amer(ln(h, 'open', 'moneyLine').get('american')), 'ml_a_open': amer(ln(a, 'open', 'moneyLine').get('american'))}
        lim = 30 if lg == 'nba' else 4
        if o['spread'] is not None and abs(o['spread']) > lim:
            o['spread'] = None
        if o['spread_open'] is not None and abs(o['spread_open']) > lim:
            o['spread_open'] = None
        if o['total_open'] is not None and not (3 <= o['total_open'] <= 300):
            o['total_open'] = None
        return o
    return None


PROP_TYPES = {
    'nba': {'Total Points': 'pts', 'Total Rebounds': 'reb', 'Total Assists': 'ast', 'Total 3-Point Field Goals': 'fg3m', 'Total Points, Rebounds, and Assists': 'pra',
            'Total Points and Rebounds': 'pr', 'Total Points and Assists': 'pa', 'Total Assists and Rebounds': 'ra', 'Total Steals': 'stl', 'Total Blocks': 'blk',
            'Total Turnovers': 'tov', 'To Record a Double Double': 'dd', 'To Record a Triple Double': 'td3',
            'Points Milestones': 'pts+', 'Rebounds Milestones': 'reb+', 'Assists Milestones': 'ast+', '3-Point Field Goals Milestones': 'fg3m+',
            'Points + Assists + Rebounds Milestones': 'pra+', 'Points + Rebounds Milestones': 'pr+', 'Points + Assists Milestones': 'pa+',
            'Rebounds + Assists Milestones': 'ra+', 'Steals Milestones': 'stl+', 'Blocks Milestones': 'blk+'},
    'nhl': {'Anytime Goalscorer': 'atg', 'First Goalscorer': 'first_goal', 'To Score 2+ Goals': 'g2', 'Total Points': 'points', 'Total Assists': 'assists',
            'Total Shots on Goal': 'sog', 'Total Saves': 'saves', 'Total Blocked Shots': 'blocks', 'Shots on Goal Milestones': 'sog+', 'Points Milestones': 'points+',
            'Assists Milestones': 'assists+', 'Goals Milestones': 'goals+', 'Goalkeeper Saves Milestones': 'saves+', 'Blocked Shots Milestones': 'blocks+'}}


_PB = {}


def prop_items(lg, ev):
    """Every prop-bet item ESPN lists for one event (all pages), from DraftKings or else ESPN BET: (items, book name)."""
    if (lg, str(ev)) in _PB:
        return _PB[(lg, str(ev))]
    res = ([], None)
    for pid, book in (('100', 'DraftKings'), ('58', 'ESPN BET')):
        items, page = [], 1
        while page <= 8:
            j = get_json(f'https://sports.core.api.espn.com/v2/sports/{ESPN_CORE[lg]}/events/{ev}/competitions/{ev}/odds/{pid}/propBets?limit=1000'
                         + (f'&page={page}' if page > 1 else ''), quiet=True)
            items += (j or {}).get('items') or []
            if not j or page >= (j.get('pageCount') or 1):
                break
            page += 1
        if items:
            res = (items, book)
            break
    _PB[(lg, str(ev))] = res
    return res


def live_log(live, out_dir, name, now):
    """A log the builds keep between runs on the live site (the repo doesn't track it), or the local copy, or {}."""
    j = get_json(live + name + '?t=' + str(int(pd.Timestamp(now).timestamp())), quiet=True)
    if j is None and os.path.exists(os.path.join(out_dir, name)):
        try:
            j = json.load(open(os.path.join(out_dir, name)))
        except Exception:
            j = None
    return j or {}


def ref_id(o, kind):
    """The id in an ESPN $ref link: ref_id(item.get('team'), 'teams') -> '9'."""
    a = (((o or {}).get('$ref')) or '').split(f'/{kind}/')
    return a[1].split('?')[0].split('/')[0] if len(a) > 1 else ''


def prop_lines(lg, ev):
    """Player-prop lines for one event: [{athlete (ESPN id), key, side ('over'/'under'/'yes'), line, odds, odds_open, line_open, book}].
    Each over/under line is listed twice. DraftKings lists the over first; ESPN BET marks the side."""
    types = PROP_TYPES[lg]
    items, book = prop_items(lg, ev)
    if items:
        pid = '100' if book == 'DraftKings' else '58'
        out, seen = [], {}
        for it in items:
            k = types.get((it.get('type') or {}).get('name'))
            if not k:
                continue
            a = ((it.get('athlete') or {}).get('$ref') or '').split('/athletes/')
            aid = a[1].split('?')[0] if len(a) > 1 else ''
            if not aid:
                continue
            cur, opn = it.get('current') or {}, it.get('open') or {}
            o = (it.get('odds') or {}).get('american') or {}
            line = num((cur.get('target') or {}).get('value'))
            if 'over' in cur or 'under' in cur:
                side = 'over' if 'over' in cur else 'under'
            elif k.endswith('+') or k in ('dd', 'td3', 'atg', 'first_goal', 'g2'):
                side = 'yes'
            else:                                                    # unmarked over/under pair: the first listed is the over
                n = seen.get((aid, k, line), 0); seen[(aid, k, line)] = n + 1
                side = 'over' if n == 0 else 'under' if n == 1 else None
            if side is None:
                continue
            out.append({'athlete': aid, 'key': k, 'side': side, 'line': line, 'odds': amer(o.get('value')), 'odds_open': amer(o.get('open')),
                        'line_open': num((opn.get('target') or {}).get('value')), 'book': 'DraftKings' if pid == '100' else 'ESPN BET'})
        return out
    return []


PART_WORDS = {'1st Quarter': 'q1', '2nd Quarter': 'q2', '3rd Quarter': 'q3', '4th Quarter': 'q4', '1st Half': 'h1', '2nd Half': 'h2',
              '1st Period': 'p1', '2nd Period': 'p2', '3rd Period': 'p3'}
PART_PLAYER = {   # book's market name -> (part, key, kind); kind 'ou' = over/under pair, 'yes' = a milestone or a scorer
    'Points Milestones - 1st Quarter': ('q1', 'pts', 'yes'), 'Assists Milestones - 1st Quarter': ('q1', 'ast', 'yes'),
    'Rebounds Milestones - 1st Quarter': ('q1', 'reb', 'yes'), 'Points Milestones - 1st Half': ('h1', 'pts', 'yes'),
    'Receiving Yards Milestones - 1st Half': ('h1', 'rec_yds', 'yes'), 'Receiving Yards Milestones - 1st Quarter': ('q1', 'rec_yds', 'yes'),
    'Rushing Yards Milestones - 1st Half': ('h1', 'rush_yds', 'yes'), 'Rushing Yards Milestones - 1st Quarter': ('q1', 'rush_yds', 'yes'),
    'Passing Yards Milestones - 1st Half': ('h1', 'pass_yds', 'yes'), 'Passing Yards Milestones - 1st Quarter': ('q1', 'pass_yds', 'yes'),
    '1st Half Total Receiving Yards': ('h1', 'rec_yds', 'ou'), '1st Quarter Total Receiving Yards': ('q1', 'rec_yds', 'ou'),
    '1st Half Total Rushing Yards': ('h1', 'rush_yds', 'ou'), '1st Quarter Total Rushing Yards': ('q1', 'rush_yds', 'ou'),
    '1st Half Total Passing Yards': ('h1', 'pass_yds', 'ou'), '1st Quarter Total Passing Yards': ('q1', 'pass_yds', 'ou'),
    '1st Half Touchdown Scorer': ('h1', 'td', 'yes'), '1st Quarter Touchdown Scorer': ('q1', 'td', 'yes')}


def part_lines(lg, ev, team_of):
    """The book's quarter, half and period lines for one event, plus first-basket and first-to-score prices and player
    props for the 1st quarter and 1st half. team_of maps ESPN team ids to the site's abbreviations.
    {'parts': {part: {'spread': {team: [line, odds]}, 'total': [line, over odds, under odds], 'ml': {team or 'draw': odds}}},
     'fb': {athlete: odds}, 'team_fg': {athlete: odds}, 'first_team': {team: odds},
     'players': {athlete: {'q1_pts': {'yes': {t: odds}} or {'ou': [line, over, under]}}}, 'book': name}"""
    items, book = prop_items(lg, ev)
    out = {'parts': {}, 'fb': {}, 'team_fg': {}, 'first_team': {}, 'players': {}, 'book': book}
    seen = {}
    for it in items:
        nm = ((it.get('type') or {}).get('name')) or ''
        o = amer(((it.get('odds') or {}).get('american') or {}).get('value'))
        line = num((((it.get('current') or {}).get('target')) or {}).get('value'))
        tm = team_of.get(ref_id(it.get('team'), 'teams'))
        aid = ref_id(it.get('athlete'), 'athletes')
        m = re.match(r'^(1st|2nd|3rd|4th) (Quarter|Half|Period) (Spread|Total Goals|Total|Moneyline)$', nm)
        if m:
            part = PART_WORDS.get(f'{m.group(1)} {m.group(2)}'); kind = {'Total Goals': 'total'}.get(m.group(3), m.group(3).lower())
            P = out['parts'].setdefault(part, {})
            if kind == 'spread' and tm and line is not None:
                P.setdefault('spread', {})[tm] = [line, o]
            elif kind == 'moneyline':
                P.setdefault('ml', {})[tm or 'draw'] = o
            elif kind == 'total' and line is not None:
                n_ = seen.get((part, 'total'), 0); seen[(part, 'total')] = n_ + 1
                t_ = P.setdefault('total', [line, None, None])
                if n_ < 2 and t_[0] == line:
                    t_[1 + n_] = o                                                   # DraftKings lists the over first
            continue
        if nm == 'First Basket' and aid:
            out['fb'][aid] = o
        elif nm == '1st Team FG Scorer' and aid:
            out['team_fg'][aid] = o
        elif nm == 'First Team to Score' and tm:
            out['first_team'][tm] = o
        elif nm in PART_PLAYER and aid:
            part, key, kind = PART_PLAYER[nm]
            e = out['players'].setdefault(aid, {}).setdefault(f'{part}_{key}', {})
            if kind == 'yes':
                if o is None:                                                    # a milestone with no price is no use
                    continue
                t = line if line is not None else 1.0
                e.setdefault('yes', {})[int(t)] = o
            elif line is not None:
                n_ = seen.get((aid, part, key, line), 0); seen[(aid, part, key, line)] = n_ + 1
                if n_ == 0:
                    e['ou'] = [line, o, None]
                elif n_ == 1 and e.get('ou') and e['ou'][0] == line:
                    e['ou'][2] = o
    out['parts'] = {k: v for k, v in out['parts'].items() if k and v}
    out['players'] = {a: {k: v for k, v in d.items() if v} for a, d in out['players'].items()}
    out['players'] = {a: d for a, d in out['players'].items() if d}
    return out


def injuries(lg):
    """ESPN's injury list: one row per player listed."""
    j = get_json(f'https://site.api.espn.com/apis/site/v2/sports/{ESPN_SITE[lg]}/injuries', timeout=40, quiet=True)
    out = []
    for team in (j or {}).get('injuries', []):
        for it in team.get('injuries') or []:
            try:
                ath = it.get('athlete') or {}
                det = it.get('details') or {}
                out.append({'team_name': team.get('displayName'), 'team': ((ath.get('team') or {}).get('abbreviation')) or None,
                            'name': ath.get('displayName') or ath.get('fullName'), 'athlete': str(ath.get('id') or ''),
                            'pos': (ath.get('position') or {}).get('abbreviation'), 'status': str(it.get('status') or ((it.get('type') or {}).get('description') or '')).strip(),
                            'fs': str(((det.get('fantasyStatus') or {}).get('abbreviation')) or '').upper(), 'injury': det.get('type'), 'side': det.get('side'),
                            'detail': det.get('detail'), 'ret': det.get('returnDate'), 'date': it.get('date'),
                            'comment': (it.get('shortComment') or it.get('longComment') or '')[:400]})
            except Exception:
                pass
    return out


def summary(lg, ev):
    return get_json(f'https://site.api.espn.com/apis/site/v2/sports/{ESPN_SITE[lg]}/summary?event={ev}', timeout=30, quiet=True)


def parallel(fn, args, workers=8):
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, args))


# ---------------------------------------------------------------- output
def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return None if not math.isfinite(v) else (round(v, 4) if abs(v) < 1e6 else v)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, dt.datetime, dt.date)):
        return o.isoformat()
    if o is pd.NaT:
        return None
    return o


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(clean(obj), f, separators=(',', ':'))
    os.replace(tmp, path)
    log('wrote', path, round(os.path.getsize(path) / 1024), 'KB')


def odds_of(p):
    """Fair American odds for a chance."""
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return -int(round(100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def implied(o):
    o = float(o)
    return -o / (-o + 100) if o < 0 else 100 / (o + 100)


def novig(o1, o2):
    if o1 is None or o2 is None:
        return None
    a, b = implied(o1), implied(o2)
    return a / (a + b)
