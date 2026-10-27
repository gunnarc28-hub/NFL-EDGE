"""Rebuild site/nhl/data/ (data.json, grade.json, summary.json, odds_log.json) from the latest public data.

Sources: box scores and schedules from the sportsdataverse fastRhockey release files (NHL ids, refreshed daily), the
NHL's own schedule and box-score feeds for last night's games, ESPN's scoreboard (probable goalies), rosters, odds
records (game lines and player props) and injury list. The research behind every number is in static/nhl_model.json.

    python pipeline/nhl.py
"""
import os, sys, json, math, re, unicodedata, datetime as dt
import numpy as np, pandas as pd
from scipy.stats import poisson

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sportslib as sl, sports_teams as stt          # noqa: E402

LG = 'nhl'
OUT = os.path.join(ROOT, 'site', 'nhl', 'data')
CACHE = os.path.join(HERE, '.cache', 'nhl')
LIVE = 'https://gunnarc28-hub.github.io/NFL-EDGE/nhl/data/'
NHLAPI = 'https://api-web.nhle.com/v1'
NOW = pd.Timestamp(os.environ['SE_NOW']).tz_convert('UTC') if os.environ.get('SE_NOW') else pd.Timestamp.now(tz='UTC')
S = json.load(open(os.path.join(HERE, 'static', 'nhl_model.json')))
SEASON = NOW.year + 1 if NOW.month >= 8 else NOW.year
SLATE = sl.slate_day(NOW)
TEAMS = stt.table('nhl')
sl.log('NHL season', SEASON, 'slate', SLATE, 'now', NOW.isoformat())


def fix_ab(a):
    a = str(a or '')
    return stt.ESPN_NHL.get(a, a)


def nkey(n):
    """'Stefan Noesen' and 'S. Noesen' both become 's noesen'."""
    n = unicodedata.normalize('NFKD', str(n or '')).encode('ascii', 'ignore').decode().lower()
    p = re.sub(r'[^a-z ]', ' ', n).split()
    p = [x for x in p if x not in ('jr', 'sr', 'ii', 'iii', 'iv')]
    return (p[0][:1] + ' ' + p[-1]) if len(p) >= 2 else (p[0] if p else '')


def toi_min(x):
    try:
        m, s = str(x).split(':'); return int(m) + int(s) / 60
    except Exception:
        return 0.0


# ================================================================== history (NHL ids)
def load(kind, season, required):
    tag = {'skater_box': 'nhl_skater_boxscores', 'goalie_box': 'nhl_goalie_boxscores', 'schedule': 'nhl_schedules'}[kind]
    fname = f'nhl_schedule_{season}.csv' if kind == 'schedule' else f'{kind}_{season}.csv'
    p = sl.sdv_csv(tag, fname, CACHE, required=required)
    return pd.read_csv(p, low_memory=False) if p else pd.DataFrame()


SK = pd.concat([load('skater_box', SEASON - 1, True), load('skater_box', SEASON, False)], ignore_index=True)
GB = pd.concat([load('goalie_box', SEASON - 1, True), load('goalie_box', SEASON, False)], ignore_index=True)
SCH = pd.concat([load('schedule', SEASON - 1, True), load('schedule', SEASON, False)], ignore_index=True)
SCH = SCH[SCH.game_type.astype(str).isin(['R', 'P', '2', '3'])].drop_duplicates('game_id')
sl.log('history: skater rows', len(SK), 'goalie rows', len(GB), 'schedule', len(SCH))

# ================================================================== the NHL's schedule around the slate, and last night's box scores
day0 = pd.Timestamp(SLATE)
DAYS = [(day0 + pd.Timedelta(days=i)).date().isoformat() for i in (-3, -2, -1, 0, 1, 2)]
wk = sl.get_json(f'{NHLAPI}/schedule/{DAYS[0]}', quiet=True) or {}
G = {}
for r in SCH.itertuples():
    t = pd.Timestamp(r.game_time) if str(r.game_time) != 'nan' else pd.Timestamp(r.game_date)
    t = t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')
    G[int(r.game_id)] = {'id': int(r.game_id), 'k': t, 'season': int(str(r.season_full)[-4:]) if 'season_full' in SCH.columns else SEASON,
                         'gt': str(r.game_type), 'home': r.home_team_abbr, 'away': r.away_team_abbr, 'state': 'post' if str(r.game_state) in ('OFF', 'FINAL') else 'pre',
                         'detail': 'Final' if str(r.game_state) in ('OFF', 'FINAL') else '', 'venue': str(r.venue) if str(r.venue) != 'nan' else '', 'hs': None, 'as': None}
STATE = {'FUT': 'pre', 'PRE': 'pre', 'LIVE': 'in', 'CRIT': 'in', 'OFF': 'post', 'FINAL': 'post'}
for d_ in wk.get('gameWeek', []):
    for x in d_.get('games', []):
        if x.get('gameType') not in (2, 3):
            continue
        gid = int(x['id']); g = G.setdefault(gid, {'id': gid, 'season': SEASON, 'gt': 'R' if x['gameType'] == 2 else 'P', 'venue': (x.get('venue') or {}).get('default', '')})
        pdsc = x.get('periodDescriptor') or {}
        st_ = STATE.get(x.get('gameState'), 'pre')
        det = ''
        if st_ == 'in':
            det = f"{'OT' if pdsc.get('periodType') == 'OT' else 'SO' if pdsc.get('periodType') == 'SO' else 'P' + str(pdsc.get('number', ''))}"
        elif st_ == 'post':
            det = 'Final' + ('/OT' if pdsc.get('periodType') == 'OT' else '/SO' if pdsc.get('periodType') == 'SO' else '')
        g.update({'k': pd.Timestamp(x['startTimeUTC']).tz_convert('UTC'), 'home': x['homeTeam']['abbrev'], 'away': x['awayTeam']['abbrev'], 'state': st_, 'detail': det})
        if st_ in ('in', 'post') and x['homeTeam'].get('score') is not None:
            g['hs'], g['as'] = float(x['homeTeam']['score']), float(x['awayTeam']['score'])
GAMES = pd.DataFrame(G.values()).rename(columns={'as': 'as_'})
GAMES = GAMES[GAMES.home.isin(TEAMS) & GAMES.away.isin(TEAMS) | (GAMES.season < SEASON)]
GAMES['day'] = GAMES.k.map(sl.et_day)
GAMES = GAMES.sort_values('k').reset_index(drop=True)

# box scores for finished games the release files don't have yet (and first goal scorers for grading)
SK['game_id'] = SK.game_id.astype(int); GB['game_id'] = GB.game_id.astype(int)
have = set(SK.game_id)
recent_final = [g for g in GAMES.itertuples() if g.state == 'post' and g.k > NOW - pd.Timedelta(days=4)]


def nhl_box(gid):
    j = sl.get_json(f'{NHLAPI}/gamecenter/{gid}/boxscore', quiet=True)
    if not j:
        return [], []
    sk_, gb_ = [], []
    pbs = j.get('playerByGameStats') or {}
    for side in ('awayTeam', 'homeTeam'):
        tm = (j.get(side) or {}).get('abbrev'); t = pbs.get(side) or {}
        for grp in ('forwards', 'defense'):
            for p in t.get(grp) or []:
                sk_.append({'game_id': gid, 'team_abbrev': tm, 'player_id': p.get('playerId'), 'player_name': (p.get('name') or {}).get('default'), 'position': p.get('position'),
                            'goals': p.get('goals', 0), 'assists': p.get('assists', 0), 'points': p.get('points', 0), 'shots_on_goal': p.get('sog', p.get('shots', 0)),
                            'hits': p.get('hits', 0), 'blocked_shots': p.get('blockedShots', 0), 'toi': p.get('toi', '0:00'), 'power_play_goals': p.get('powerPlayGoals', 0)})
        for p in t.get('goalies') or []:
            sa = p.get('shotsAgainst'); sv = p.get('saves')
            if sa is None and p.get('saveShotsAgainst'):
                try: sv, sa = [int(v) for v in str(p['saveShotsAgainst']).split('/')]
                except ValueError: pass
            gb_.append({'game_id': gid, 'team_abbrev': tm, 'player_id': p.get('playerId'), 'player_name': (p.get('name') or {}).get('default'), 'saves': sv, 'shots_against': sa,
                        'goals_against': p.get('goalsAgainst'), 'toi': p.get('toi', '0:00'), 'starter': bool(p.get('starter')), 'decision': p.get('decision')})
    return sk_, gb_


def first_goal(gid):
    j = sl.get_json(f'{NHLAPI}/gamecenter/{gid}/landing', quiet=True)
    for per in ((j or {}).get('summary') or {}).get('scoring') or []:
        if (per.get('periodDescriptor') or {}).get('periodType') == 'SO':
            continue
        for gl in per.get('goals') or []:
            nm = gl.get('name') or {}
            return gid, int(gl.get('playerId')), (gl.get('firstName') or {}).get('default', '') + ' ' + (gl.get('lastName') or {}).get('default', '') if gl.get('firstName') else nm.get('default', '')
    return gid, (None if not j else ''), ''


need = [g.id for g in recent_final if g.id not in have]
if need:
    xs, xg = [], []
    for a, b in sl.parallel(nhl_box, need, 6):
        xs += a; xg += b
    if xs:
        SK = pd.concat([SK, pd.DataFrame(xs)], ignore_index=True)
    if xg:
        GB = pd.concat([GB, pd.DataFrame(xg)], ignore_index=True)
    sl.log('box scores from the NHL feed:', len(need), 'games')
FIRST = {gid: (pid, nm) for gid, pid, nm in sl.parallel(first_goal, [g.id for g in recent_final], 6)}

# ================================================================== tidy boxes; finals from the boxes (the schedule file's scores are unreliable)
SK = SK.drop_duplicates(['game_id', 'player_id'], keep='last').copy()
GB = GB.drop_duplicates(['game_id', 'player_id'], keep='last').copy()
SK['player_id'] = SK.player_id.astype(int); GB['player_id'] = GB.player_id.astype(int)
for c in ['goals', 'assists', 'points', 'shots_on_goal', 'hits', 'blocked_shots', 'power_play_goals']:
    SK[c] = pd.to_numeric(SK[c], errors='coerce').fillna(0)
SK['toi_m'] = SK.toi.map(toi_min)
SK = SK[SK.toi_m > 0]
GB['saves'] = pd.to_numeric(GB.saves, errors='coerce'); GB['shots_against'] = pd.to_numeric(GB.shots_against, errors='coerce')
GB['is_start'] = GB.starter.astype(str).str.lower().isin(['true', '1'])
goals = SK.groupby(['game_id', 'team_abbrev']).goals.sum()
winner = GB[GB.decision == 'W'].drop_duplicates('game_id').set_index('game_id').team_abbrev
for i, g in GAMES.iterrows():
    if g.state != 'post':
        continue
    bh, ba = goals.get((g.id, g.home)), goals.get((g.id, g.away))
    w = winner.get(g.id)
    if bh is not None and ba is not None and w is not None:
        so = bh == ba
        GAMES.at[i, 'hs'] = bh + (1 if so and w == g.home else 0); GAMES.at[i, 'as_'] = ba + (1 if so and w == g.away else 0)
        GAMES.at[i, 'so'] = bool(so)
OT = (GB.assign(m=GB.toi.map(toi_min)).groupby(['game_id', 'team_abbrev']).m.sum().groupby('game_id').max() > 60.2).to_dict()
GAMES['ot'] = GAMES.id.map(lambda i: bool(OT.get(i, False)))
gi = GAMES.set_index('id')
SK = SK[SK.game_id.isin(gi.index)].copy()
SK['t'] = SK.game_id.map(gi.k); SK['home'] = SK.game_id.map(gi.home); SK['away'] = SK.game_id.map(gi.away)
SK['opp'] = np.where(SK.team_abbrev == SK.home, SK.away, SK.home)
SK['pos1'] = np.where(SK.position.astype(str).str.upper().str[0] == 'D', 'D', 'F')
SK = SK.sort_values(['t', 'game_id']).reset_index(drop=True)
GB = GB[GB.game_id.isin(gi.index)].copy(); GB['t'] = GB.game_id.map(gi.k); GB = GB.sort_values('t')
PNAME = SK.groupby('player_id').player_name.last().to_dict(); PNAME.update(GB.groupby('player_id').player_name.last().to_dict())
PTEAM = SK.groupby('player_id').team_abbrev.last().to_dict(); PTEAM.update(GB.groupby('player_id').team_abbrev.last().to_dict())
PPOS = SK.groupby('player_id').position.last().to_dict()
sl.log('games', len(GAMES), 'finals this season', int(((GAMES.season == SEASON) & (GAMES.state == 'post')).sum()))

# ================================================================== ESPN: scoreboard (event ids, probable goalies), rosters (names), injuries
BOARD = {}
for d_, evs in zip(DAYS, sl.parallel(lambda d: sl.scoreboard(LG, d), DAYS, 6)):
    for e in evs:
        BOARD[e['id']] = dict(e, day=d_)
E2G, G2E, PROB, ESPN_TEAM = {}, {}, {}, {}
for e in BOARD.values():
    h, a = fix_ab(e['home']['abbr']), fix_ab(e['away']['abbr'])
    ESPN_TEAM[h] = e['home']['espn_id']; ESPN_TEAM[a] = e['away']['espn_id']
    m = GAMES[(GAMES.home == h) & (GAMES.away == a) & (abs((GAMES.k - pd.Timestamp(e['date'])).dt.total_seconds()) < 20 * 3600)]
    if len(m):
        gid = int(m.id.iloc[0]); E2G[e['id']] = gid; G2E[gid] = e['id']
        PROB[gid] = {'h': e['home']['probable'], 'a': e['away']['probable']}
        for side, x in (('home', e['home']), ('away', e['away'])):
            GAMES.loc[GAMES.id == gid, side + '_rec'] = json.dumps(x['rec'])
sl.log('ESPN events matched', len(E2G), 'of', len(BOARD))
show_ids = set(GAMES[(GAMES.day >= SLATE) & (GAMES.day <= DAYS[-2])].id)
teams_today = sorted({t for g in GAMES[GAMES.id.isin(show_ids)].itertuples() for t in (g.home, g.away)})
ROSTER = {}                     # team -> {espn athlete id: (name, pos)}
def roster(t):
    tid = ESPN_TEAM.get(t)
    if not tid:
        return t, {}
    j = sl.get_json(f'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams/{tid}/roster', quiet=True) or {}
    out = {}
    for grp in j.get('athletes') or []:
        for a in grp.get('items') or []:
            out[str(a.get('id'))] = (a.get('fullName') or a.get('displayName'), (a.get('position') or {}).get('abbreviation'))
    return t, out
for t, r in sl.parallel(roster, teams_today, 8):
    ROSTER[t] = r
E2N = {}                        # ESPN athlete id -> NHL player id
for t, r in ROSTER.items():
    keys = {}
    for pid in set(SK[SK.team_abbrev == t].player_id) | set(GB[GB.team_abbrev == t].player_id):
        keys.setdefault(nkey(PNAME.get(pid)), []).append(pid)
    for eid, (nm, pos) in r.items():
        c = keys.get(nkey(nm))
        if c and len(c) == 1:
            E2N[eid] = c[0]
sl.log('rosters', len(ROSTER), 'ESPN ids matched', len(E2N))
for t, r in ROSTER.items():
    for eid, (nm, pos) in r.items():
        if eid in E2N and nm:
            PNAME[E2N[eid]] = nm
INJ_RAW = sl.injuries(LG)
NAME2AB = {v['name']: k for k, v in TEAMS.items()}
NAME2AB.update({'Montreal Canadiens': 'MTL', 'Utah Hockey Club': 'UTA', 'Utah Mammoth': 'UTA', 'St Louis Blues': 'STL'})
INJ = {}
LEVEL = {'out': 'out', 'injured reserve': 'out', 'long term': 'out', 'ltir': 'out', 'doubtful': 'doubt', 'questionable': 'gtd', 'day-to-day': 'gtd', 'probable': 'likely', 'suspension': 'out'}
for e in INJ_RAW:
    t = NAME2AB.get(e['team_name']) or fix_ab(e['team'])
    if t not in TEAMS or not e['name']:
        continue
    s_ = e['status'].lower()
    lvl = next((v for k, v in LEVEL.items() if k in s_), 'gtd')
    pid = E2N.get(e['athlete'])
    if pid is None:
        c = [p for p in set(SK[SK.team_abbrev == t].player_id) | set(GB[GB.team_abbrev == t].player_id) if nkey(PNAME.get(p)) == nkey(e['name'])]
        pid = c[0] if len(c) == 1 else None
    INJ.setdefault(t, []).append({'name': e['name'], 'pid': pid, 'pos': e['pos'], 'status': e['status'], 'level': lvl, 'injury': e['injury'] or '',
                                  'ret': e['ret'], 'date': e['date'], 'comment': e['comment']})
OUT_IDS = {i['pid'] for lst in INJ.values() for i in lst if i['pid'] and i['level'] in ('out', 'doubt')}
sl.log('injuries: teams', len(INJ), 'players', sum(len(v) for v in INJ.values()))

# ================================================================== odds log (ESPN event ids), kept on the live site between runs
def load_log():
    j = sl.get_json(LIVE + 'odds_log.json?t=' + str(int(NOW.timestamp())), quiet=True)
    if j is None and os.path.exists(os.path.join(OUT, 'odds_log.json')):
        j = json.load(open(os.path.join(OUT, 'odds_log.json')))
    return j or {}


OLOG = load_log()                      # keyed by NHL game id (string)
up = [g for g in GAMES.itertuples() if g.day >= DAYS[2] and g.day <= DAYS[-1] and g.id in G2E and (g.state == 'pre' or str(g.id) not in OLOG)]
got = dict(zip([g.id for g in up], sl.parallel(lambda gid: sl.game_odds(LG, G2E[gid]), [g.id for g in up], 8)))
for gid, o in got.items():
    g = GAMES[GAMES.id == gid].iloc[0]
    if o and (g.state == 'pre' or str(gid) not in OLOG):
        o['seen'] = NOW.isoformat(timespec='minutes'); o['eid'] = G2E[gid]; OLOG[str(gid)] = o
sl.log('odds fetched', sum(1 for v in got.values() if v), 'of', len(got), '| log', len(OLOG))
LINE = {int(k): v for k, v in OLOG.items()}

# ================================================================== the research model: goals and shots ratings, the starting goalie, home ice
GP = S['game']
a_ = 0.5 ** (1 / GP['H']); as_ = 0.5 ** (1 / GP['Hs']); ag = 0.5 ** (1 / GP['Hg'])
O, Dd, SO, SD, LAST, GK = {}, {}, {}, {}, {}, {}
lg_g, lg_s = GP['lg_goals'], GP['lg_shots']
shots = SK.groupby(['game_id', 'team_abbrev']).shots_on_goal.sum().to_dict()
starters = GB[GB.is_start].drop_duplicates(['game_id', 'team_abbrev']).set_index(['game_id', 'team_abbrev']).player_id.to_dict()
gl_line = {(r.game_id, r.player_id): (r.saves, r.shots_against) for r in GB.itertuples() if r.shots_against == r.shots_against}
PRE = {}
season_ = None
TEAM_STARTS = {}                       # team -> recent starters, to guess when nobody is announced
for g in GAMES.itertuples():
    if g.season != season_:
        season_ = g.season
        for t in list(O): O[t] *= GP['carry']; Dd[t] *= GP['carry']; SO[t] *= GP['carry']; SD[t] *= GP['carry']
    h, w = g.home, g.away
    for t in (h, w):
        for X in (O, Dd, SO, SD): X.setdefault(t, 0.0)
    PRE[g.id] = {'O_h': O[h], 'D_h': Dd[h], 'SO_h': SO[h], 'SD_h': SD[h], 'O_a': O[w], 'D_a': Dd[w], 'SO_a': SO[w], 'SD_a': SD[w], 'lg_g': lg_g, 'lg_s': lg_s,
                 'rest_h': min((g.k - LAST[h]).days, 5) if h in LAST else 5, 'rest_a': min((g.k - LAST[w]).days, 5) if w in LAST else 5,
                 'gk_h': starters.get((g.id, h)), 'gk_a': starters.get((g.id, w)), 'GK': None}
    if g.state != 'post' or g.hs is None or g.hs != g.hs:
        continue
    eg_h = lg_g * math.exp(O[h] - Dd[w] + GP['hca'] / 2); eg_a = lg_g * math.exp(O[w] - Dd[h] - GP['hca'] / 2)
    es_h = lg_s * math.exp(SO[h] - SD[w] + GP['hca'] / 2); es_a = lg_s * math.exp(SO[w] - SD[h] - GP['hca'] / 2)
    gh, ga = g.hs, g.as_
    O[h] += (1 - a_) * math.log((gh + 0.5) / (eg_h + 0.5)); Dd[w] -= (1 - a_) * math.log((gh + 0.5) / (eg_h + 0.5))
    O[w] += (1 - a_) * math.log((ga + 0.5) / (eg_a + 0.5)); Dd[h] -= (1 - a_) * math.log((ga + 0.5) / (eg_a + 0.5))
    sh, sa = shots.get((g.id, h)), shots.get((g.id, w))
    if sh and sa and sh > 5 and sa > 5:
        SO[h] += (1 - as_) * math.log(sh / es_h); SD[w] -= (1 - as_) * math.log(sh / es_h)
        SO[w] += (1 - as_) * math.log(sa / es_a); SD[h] -= (1 - as_) * math.log(sa / es_a)
        lg_s = 0.998 * lg_s + 0.002 * (sh + sa) / 2
    lg_g = 0.998 * lg_g + 0.002 * (gh + ga) / 2
    for t in (h, w):
        pid = starters.get((g.id, t))
        if pid is None:
            continue
        TEAM_STARTS.setdefault(t, []).append(pid)
        x = gl_line.get((g.id, pid))
        if x:
            cur = GK.get(pid, [0.0, 0.0]); GK[pid] = [ag * cur[0] + x[0], ag * cur[1] + x[1]]
    LAST[h] = g.k; LAST[w] = g.k
LG_SV = 1 - lg_g / lg_s


def gk_sv(pid):
    if pid is None or pid not in GK:
        return LG_SV
    sv, sh = GK[pid]
    return (sv + LG_SV * GP['gk_prior']) / (sh + GP['gk_prior'])


def usual_starter(team):
    lst = TEAM_STARTS.get(team, [])[-12:]
    return max(set(lst), key=lst.count) if lst else None


def win_prob(lh, la, maxg=12):
    ph = poisson.pmf(np.arange(maxg), lh); pa = poisson.pmf(np.arange(maxg), la)
    m = np.outer(ph, pa)
    return float(np.tril(m, -1).sum() + np.trace(m) * 0.5), m


def predict(g):
    f = PRE[g.id]; lgg, lgs = f['lg_g'], f['lg_s']
    lgsv = 1 - lgg / lgs
    if g.state == 'post':
        gh, ga = f['gk_h'], f['gk_a']; src_h = src_a = 'played'
    else:
        pr_ = PROB.get(g.id) or {}
        def pick(side, team):
            p = (pr_.get(side) or {})
            pid = E2N.get(str(p.get('id'))) if p else None
            if pid is None and p and p.get('name'):
                c = [x for x in set(GB[GB.team_abbrev == team].player_id) if nkey(PNAME.get(x)) == nkey(p['name'])]
                pid = c[0] if len(c) == 1 else None
            if pid is not None:
                return pid, (p.get('status') or 'Probable')
            return usual_starter(team), 'Expected'
        gh, src_h = pick('h', g.home); ga, src_a = pick('a', g.away)
    sv_h, sv_a = gk_sv(gh), gk_sv(ga)
    eg_h = lgg * math.exp(f['O_h'] - f['D_a'] + GP['hca'] / 2); eg_a = lgg * math.exp(f['O_a'] - f['D_h'] - GP['hca'] / 2)
    es_h = lgs * math.exp(f['SO_h'] - f['SD_a'] + GP['hca'] / 2); es_a = lgs * math.exp(f['SO_a'] - f['SD_h'] - GP['hca'] / 2)
    lam_h0 = GP['w_shot'] * es_h * (1 - lgsv) + (1 - GP['w_shot']) * eg_h          # with league-average goalies
    lam_a0 = GP['w_shot'] * es_a * (1 - lgsv) + (1 - GP['w_shot']) * eg_a
    lam_h = lam_h0 * (1 - sv_a) / (1 - lgsv); lam_a = lam_a0 * (1 - sv_h) / (1 - lgsv)
    p, m = win_prob(lam_h, lam_a)
    home_ice = lgg * (math.exp(GP['hca'] / 2) - math.exp(-GP['hca'] / 2))
    parts = {'home': round(home_ice, 3), 'skaters': round((lam_h0 - lam_a0) - home_ice, 3), 'goalies': round((lam_h - lam_a) - (lam_h0 - lam_a0), 3)}
    diff = np.subtract.outer(np.arange(12), np.arange(12))
    return {'lam_h': round(lam_h, 3), 'lam_a': round(lam_a, 3), 'wp_home': round(p, 4), 'total': round(lam_h + lam_a, 2),
            'p_h_by2': round(float(m[diff >= 2].sum()), 4), 'p_a_by2': round(float(m[diff <= -2].sum()), 4),
            'gk_h': gh, 'gk_a': ga, 'gk_src_h': src_h, 'gk_src_a': src_a, 'sv_h': round(sv_h, 4), 'sv_a': round(sv_a, 4),
            'rest_h': f['rest_h'], 'rest_a': f['rest_a'], 'b2b_h': f['rest_h'] <= 1, 'b2b_a': f['rest_a'] <= 1, 'parts': parts}


PRED = {g.id: predict(g) for g in GAMES.itertuples() if g.season >= SEASON - 1}
REC = {'su': [0, 0], 'ml': [0, 0, 0.0], 'ou': [0, 0, 0]}
model_log = []
for g in GAMES[(GAMES.season == SEASON) & (GAMES.state == 'post') & GAMES.hs.notna()].itertuples():
    p = PRED.get(g.id); o = LINE.get(g.id) or {}
    if not p or g.hs == g.as_:
        continue
    win_h = g.hs > g.as_
    REC['su'][0 if (p['wp_home'] > 0.5) == win_h else 1] += 1
    row = {'id': g.id, 'day': g.day, 'a': g.away, 'h': g.home, 'as': int(g.as_), 'hs': int(g.hs), 'wp_home': p['wp_home'], 'pick': g.home if p['wp_home'] > 0.5 else g.away,
           'su': 'W' if (p['wp_home'] > 0.5) == win_h else 'L', 'so': bool(getattr(g, 'so', False) is True)}
    if o.get('ml_h') and o.get('ml_a'):
        mk = sl.novig(o['ml_h'], o['ml_a']); row['mkt'] = round(mk, 4)
        if abs(p['wp_home'] - mk) >= 0.05:
            side_h = p['wp_home'] > mk; won = side_h == win_h
            REC['ml'][0 if won else 1] += 1
            px = o['ml_h'] if side_h else o['ml_a']
            REC['ml'][2] += (px / 100 if px > 0 else 100 / abs(px)) if won else -1.0
            row['value'] = g.home if side_h else g.away; row['value_r'] = 'W' if won else 'L'
    if o.get('total') is not None:
        tot = g.hs + g.as_
        pover = 1 - poisson.cdf(math.floor(o['total']), p['lam_h'] + p['lam_a'])
        row.update({'tl': o['total'], 'p_over': round(float(pover), 3)})
        if abs(pover - 0.5) >= 0.06 and tot != o['total']:
            REC['ou'][0 if (pover > 0.5) == (tot > o['total']) else 1] += 1
    model_log.append(row)
REC['ml'][2] = round(REC['ml'][2], 2)
sl.log('model this season: SU', REC['su'], 'value ML', REC['ml'], 'O/U', REC['ou'])

# ================================================================== skater and goalie projections (the research model, as of now)
PP = S['props']; CAL = PP['cal']
pl = SK.copy()
tc = PP['toi_coef']
lgr = {}
cur = pl[pl.t > NOW - pd.Timedelta(days=400)]
for pos1, x in cur.groupby('pos1'):
    tot = x.toi_m.sum()
    lgr[pos1] = {'g': x.goals.sum() / tot, 'a': x.assists.sum() / tot, 'p': x.points.sum() / tot, 'sog': x.shots_on_goal.sum() / tot,
                 'hit': x.hits.sum() / tot, 'blk': x.blocked_shots.sum() / tot, 'sh': x.goals.sum() / max(x.shots_on_goal.sum(), 1)}
FORM = {}
for pid, x in pl.groupby('player_id', sort=False):
    if x.t.iloc[-1] < NOW - pd.Timedelta(days=200) or len(x) < 3:
        continue
    ew = lambda s, hl: float(s.ewm(halflife=hl, min_periods=1).mean().iloc[-1])
    toi_ewr = ew(x.toi_m, PP['half_life_rate']); n = len(x); pos1 = x.pos1.iloc[-1]; L = lgr.get(pos1) or lgr['F']
    f = {'n': n, 'toi_ew': ew(x.toi_m, PP['half_life_toi']), 'toi_ewr': toi_ewr, 'team': x.team_abbrev.iloc[-1], 'pos1': pos1, 'last': x.t.iloc[-1]}
    w = toi_ewr * min(n, 40)
    for k, c in (('g', 'goals'), ('a', 'assists'), ('p', 'points'), ('sog', 'shots_on_goal'), ('hit', 'hits'), ('blk', 'blocked_shots')):
        r = ew(x[c], PP['half_life_rate']) / max(toi_ewr, 3)
        f[k + '_rate'] = (r * w + L[k] * PP['prior_minutes']) / (w + PP['prior_minutes'])
    gs_ = float(x.goals.ewm(halflife=60, min_periods=1).mean().iloc[-1]); ss_ = float(x.shots_on_goal.ewm(halflife=60, min_periods=1).mean().iloc[-1])
    nsh = ss_ * min(n, 80)
    f['sh'] = ((gs_ / max(ss_, 0.1)) * nsh + L['sh'] * PP['sh_prior_shots']) / (nsh + PP['sh_prior_shots'])
    FORM[pid] = f
tg = pl.groupby(['game_id', 'team_abbrev', 'opp', 't']).shots_on_goal.sum().reset_index().sort_values('t')
SOG_ALLOW = {o: float(x.shots_on_goal.ewm(halflife=15, min_periods=1).mean().iloc[-1]) for o, x in tg.groupby('opp')}
SOG_LG = float(tg.shots_on_goal.ewm(halflife=600, min_periods=1).mean().iloc[-1]) if len(tg) else 30.0


def project(pid, opp, opp_sv):
    f = FORM.get(pid)
    if not f:
        return None
    toi = max(0.0, tc[0] + tc[1] * f['toi_ew'] + tc[2] * f['toi_ewr'])
    of = min(max(SOG_ALLOW.get(opp, SOG_LG) / SOG_LG, 0.75), 1.3) ** PP['opp_sog_exp']
    gk = min(max((1 - opp_sv) / (1 - 0.905), 0.7), 1.4)
    sog = toi * f['sog_rate'] * of
    g = (0.5 * sog * f['sh'] + 0.5 * toi * f['g_rate']) * gk
    a = toi * f['a_rate'] * gk ** 0.5
    return {'toi': round(toi, 1), 'sog': sog, 'goals': g, 'assists': a, 'points': g + a, 'hits': toi * f['hit_rate'], 'blocks': toi * f['blk_rate']}


def calp(name, p):
    pts = CAL.get(name)
    if not pts or p is None:
        return p
    xs = [0.0] + [x for x, y in pts] + [1.0]; ys = [0.0] + [y for x, y in pts] + [1.0]
    return float(np.interp(p, xs, ys))


CALNAME = {'goals': 'goal', 'points': 'point', 'assists': 'assist', 'sog': 'sog', 'blocks': 'blk', 'hits': 'hit'}


def p_atleast(k, lam, t):
    """Chance of t or more (Poisson, then the research's calibration for that count)."""
    if lam is None:
        return None
    p = float(1 - poisson.cdf(t - 1, max(lam, 1e-6)))
    return calp(f'{CALNAME[k]}{t}', p)


def p_over(k, lam, L):
    return p_atleast(k, lam, int(math.floor(L)) + 1)


def dec(o):
    return 1 + (o / 100 if o > 0 else 100 / abs(o))


lgt = lambda p: math.log(p / (1 - p)); sgm = lambda x: 1 / (1 + math.exp(-x))
BLEND = {'points': PP['blend'].get('points', 0), 'assists': PP['blend'].get('assists', 0), 'sog': PP['blend'].get('shots_on_goal', 0),
         'blocks': PP['blend'].get('blocked_shots', 0), 'saves': 0.3}


def blend(k, pm, pb):
    if pb is None:
        return pm
    w = BLEND.get(k, 0.0); pm = min(max(pm, 0.02), 0.98); pb = min(max(pb, 0.02), 0.98)
    return sgm((1 - w) * lgt(pb) + w * lgt(pm))


# ================================================================== the slate: lines, props, high-chance picks and long shots
SHOW = GAMES[(GAMES.day >= SLATE) & (GAMES.day <= DAYS[-2])]
PROP_GAMES = [g for g in SHOW.itertuples() if g.state == 'pre' and g.id in G2E]
PLINES = dict(zip([g.id for g in PROP_GAMES], sl.parallel(lambda gid: sl.prop_lines(LG, G2E[gid]), [g.id for g in PROP_GAMES], 8)))
sl.log('prop lines:', {k: len(v) for k, v in PLINES.items()})
OU_KEYS = ('points', 'assists', 'sog', 'blocks', 'saves')


def book_lines(gid):
    out, pairs = {}, {}
    for x in PLINES.get(gid) or []:
        pid = E2N.get(x['athlete'])
        if pid is None:
            continue
        if x['side'] in ('over', 'under') and x['key'] in OU_KEYS:
            pairs.setdefault((pid, x['key'], x['line']), {})[x['side']] = x
        elif x['side'] == 'yes':
            out.setdefault(pid, {}).setdefault('yes', {})[(x['key'], x['line'])] = x
    for (pid, k, L), sd in pairs.items():
        if 'over' not in sd or 'under' not in sd or sd['over']['odds'] is None or sd['under']['odds'] is None:
            continue
        pb = sl.novig(sd['over']['odds'], sd['under']['odds'])
        cand = {'line': L, 'o': sd['over']['odds'], 'u': sd['under']['odds'], 'p_book': pb, 'open': sd['over'].get('line_open'), 'book': sd['over']['book']}
        cur_ = out.setdefault(pid, {}).get(k)
        if cur_ is None or abs(pb - 0.5) < abs(cur_['p_book'] - 0.5):
            out[pid][k] = cand
    return out


def recent(pid, col, n=10):
    return pl[pl.player_id == pid].tail(n)[col].tolist()


PROPS, GOALIES, HC, LS = [], [], [], []
LAM = {}
for g in SHOW.itertuples():
    p = PRED.get(g.id)
    if not p:
        continue
    lines = book_lines(g.id) if g.state == 'pre' else {}
    LAM[g.id] = p['lam_h'] + p['lam_a']
    for team, opp, side in ((g.home, g.away, 'h'), (g.away, g.home, 'a')):
        opp_sv = p['sv_a'] if side == 'h' else p['sv_h']
        last_g = pl[pl.team_abbrev == team].game_id.drop_duplicates().tail(3)
        regulars = set(pl[(pl.team_abbrev == team) & pl.game_id.isin(last_g)].player_id)
        regulars = {x for x in regulars if PTEAM.get(x) == team} | {x for x in lines if PTEAM.get(x) == team and x in FORM}
        for pid in regulars:
            if pid in OUT_IDS:
                continue
            pr = project(pid, opp, opp_sv)
            if not pr or pr['toi'] < 8:
                continue
            lns = lines.get(pid, {})
            name = PNAME.get(pid)
            item = {'id': str(pid), 'name': name, 'team': team, 'opp': opp, 'game': str(g.id), 'home': side == 'h', 'pos': PPOS.get(pid, ''), 'toi': pr['toi'],
                    'proj': {k: round(pr[k], 3) for k in ('sog', 'goals', 'assists', 'points', 'hits', 'blocks')},
                    'avg': {'sog': round(float(np.mean(recent(pid, 'shots_on_goal'))), 2), 'points': round(float(np.mean(recent(pid, 'points'))), 2),
                            'goals': round(float(np.mean(recent(pid, 'goals'))), 2)},
                    'p_goal': round(p_atleast('goals', pr['goals'], 1), 4), 'p_point': round(p_atleast('points', pr['points'], 1), 4),
                    'p_first': round(pr['goals'] / max(LAM[g.id], 0.1) * (1 - math.exp(-LAM[g.id])), 4), 'lines': {}, 'yes': {}}
            for k, ln in lns.items():
                if k not in OU_KEYS:
                    continue
                pm = p_over(k, pr[k], ln['line']); pb = ln['p_book']; pp_ = blend(k, pm, pb)
                item['lines'][k] = {'line': ln['line'], 'o': ln['o'], 'u': ln['u'], 'open': ln['open'], 'p_book': round(pb, 4), 'p_model': round(pm, 4), 'p': round(pp_, 4),
                                    'ev_o': round(pp_ * dec(ln['o']) - 1, 4), 'ev_u': round((1 - pp_) * dec(ln['u']) - 1, 4), 'book': ln['book']}
            for (yk, yl), x in lns.get('yes', {}).items():
                if yk in ('atg', 'first_goal', 'g2') and x['odds']:
                    item['yes'][yk] = x['odds']
            if g.state == 'pre':
                PROPS.append(item)
            if g.state != 'pre':
                continue
            nm = name or ''
            short = nm.split(' ')[-1] if nm else ''
            # ---- high-chance: shots on goal and blocks he reaches 80%+ of the time
            for k, ts, col in (('sog', (2, 3, 4), 'shots_on_goal'), ('blocks', (1, 2), 'blocked_shots')):
                best = None
                for t in ts:
                    pt = p_atleast(k, pr[k], t)
                    if pt is not None and 0.80 <= pt <= 0.97:
                        best = (t, pt)
                if best:
                    t, pt = best; r = recent(pid, col); hits = sum(1 for v in r if v >= t)
                    word = 'shots on goal' if k == 'sog' else 'blocked shots'
                    HC.append({'kind': 'player', 'id': str(pid), 'name': nm, 'team': team, 'opp': opp, 'game': str(g.id), 'k': g.k.isoformat(), 'key': k, 't': t,
                               'p': round(pt, 4), 'fair': sl.odds_of(pt), 'proj': round(pr[k], 2), 'avg': round(float(np.mean(r)), 2) if r else None, 'hits': [hits, len(r)],
                               'book': (lns.get('yes', {}).get((k + '+', float(t))) or {}).get('odds'), 'label': f"{nm} {t}+ {word}",
                               'reason': f"{short} has {t}+ {word} in {hits} of his last {len(r)} games and is projected for {pr[k]:.1f} in about {pr['toi']:.0f} minutes."})
            # ---- long shots: goals, multi-point games, the first goal, big shot nights
            yes = lns.get('yes', {})
            for key, pt, label, book_key in (('atg', p_atleast('goals', pr['goals'], 1), 'to score', ('atg', None)),
                                             ('g2', p_atleast('goals', pr['goals'], 2), '2+ goals', ('g2', None)),
                                             ('pts2', p_atleast('points', pr['points'], 2), '2+ points', ('points+', 2.0)),
                                             ('pts3', p_atleast('points', pr['points'], 3), '3+ points', ('points+', 3.0)),
                                             ('first_goal', item['p_first'], 'first goal of the game', ('first_goal', None)),
                                             ('sog5', p_atleast('sog', pr['sog'], 5), '5+ shots on goal', ('sog+', 5.0))):
                lo = {'atg': 0.18, 'g2': 0.035, 'pts2': 0.10, 'pts3': 0.04, 'first_goal': 0.055, 'sog5': 0.07}[key]
                hi = {'atg': 0.50, 'g2': 0.25, 'pts2': 0.45, 'pts3': 0.25, 'first_goal': 0.30, 'sog5': 0.40}[key]
                if pt is None or not (lo <= pt <= hi):
                    continue
                bo = yes.get(book_key) or next((v for (kk, _), v in yes.items() if kk == book_key[0] and book_key[1] is None), None)
                col = 'points' if key.startswith('pts') else 'shots_on_goal' if key == 'sog5' else 'goals'
                need = {'atg': 1, 'g2': 2, 'pts2': 2, 'pts3': 3, 'sog5': 5, 'first_goal': 1}[key]
                r = recent(pid, col, 20); hits = sum(1 for v in r if v >= need)
                LS.append({'type': key, 'key': key, 'id': str(pid), 'name': nm, 'team': team, 'opp': opp, 'game': str(g.id), 'k': g.k.isoformat(), 'p': round(pt, 4),
                           'fair': sl.odds_of(pt), 'book': bo['odds'] if bo else None, 'hits': [hits, len(r)], 'label': f"{nm} {label}", 'group': key,
                           'proj': round(pr['goals'] if col == 'goals' else pr['points'] if col == 'points' else pr['sog'], 2),
                           'reason': (f"{short} has {'scored' if col == 'goals' else 'had ' + str(need) + '+ ' + ('points' if col == 'points' else 'shots')} in {hits} of his last {len(r)} games. "
                                      f"Expected goals tonight {pr['goals']:.2f}, shots {pr['sog']:.1f}." if key != 'first_goal' else
                                      f"About {pr['goals'] / max(LAM[g.id], 0.1) * 100:.0f}% of the goals the model expects in this game are his, and {(1 - math.exp(-LAM[g.id])) * 100:.0f}% that anyone scores.")})
        # ---- goalies: the probable starter's saves
        gid_ = p['gk_h'] if side == 'h' else p['gk_a']
        if gid_ is not None:
            es = (PRE[g.id]['lg_s'] * math.exp((PRE[g.id]['SO_a'] - PRE[g.id]['SD_h'] - GP['hca'] / 2) if side == 'h' else (PRE[g.id]['SO_h'] - PRE[g.id]['SD_a'] + GP['hca'] / 2)))
            sv = p['sv_h'] if side == 'h' else p['sv_a']
            mu = es * sv; sd = PP['sv_sd']
            ln = lines.get(gid_, {}).get('saves')
            gi_ = {'id': str(gid_), 'name': PNAME.get(gid_), 'team': team, 'opp': opp, 'game': str(g.id), 'src': p['gk_src_h'] if side == 'h' else p['gk_src_a'],
                   'sv_pct': round(sv, 4), 'shots': round(es, 1), 'saves': round(mu, 1), 'lines': {}}
            if ln:
                pm = 1 - 0.5 * (1 + math.erf((ln['line'] - mu) / (sd * math.sqrt(2)))); pb = ln['p_book']; pp_ = blend('saves', pm, pb)
                gi_['lines']['saves'] = {'line': ln['line'], 'o': ln['o'], 'u': ln['u'], 'p_book': round(pb, 4), 'p_model': round(pm, 4), 'p': round(pp_, 4),
                                         'ev_o': round(pp_ * dec(ln['o']) - 1, 4), 'ev_u': round((1 - pp_) * dec(ln['u']) - 1, 4), 'book': ln['book']}
            if g.state == 'pre':
                GOALIES.append(gi_)
                for t in (30, 28, 26, 24, 22, 20, 18):
                    pt = 1 - 0.5 * (1 + math.erf((t - 0.5 - mu) / (sd * math.sqrt(2))))
                    if 0.80 <= pt <= 0.95:
                        HC.append({'kind': 'goalie', 'id': str(gid_), 'name': PNAME.get(gid_), 'team': team, 'opp': opp, 'game': str(g.id), 'k': g.k.isoformat(), 'key': 'saves',
                                   't': t, 'p': round(pt, 4), 'fair': sl.odds_of(pt), 'proj': round(mu, 1), 'label': f"{PNAME.get(gid_)} {t}+ saves", 'src': gi_['src'],
                                   'reason': f"{opp} is expected to put about {es:.0f} shots on goal; at his {sv * 100:.1f}% save rate that's {mu:.0f} saves. Starter status: {gi_['src'].lower()}."})
                        break
# team-level: big moneyline favorites
for g in SHOW.itertuples():
    p = PRED.get(g.id); o = LINE.get(g.id) or {}
    if g.state != 'pre' or not p:
        continue
    for team, wp, ml in ((g.home, p['wp_home'], o.get('ml_h')), (g.away, 1 - p['wp_home'], o.get('ml_a'))):
        mk = sl.implied(ml) if ml else None
        if wp >= 0.68 and (mk is None or mk >= 0.62):
            HC.append({'kind': 'ml', 'team': team, 'opp': g.away if team == g.home else g.home, 'game': str(g.id), 'k': g.k.isoformat(), 'p': round(wp, 4), 'fair': sl.odds_of(wp),
                       'book': ml, 'mkt_p': round(mk, 4) if mk else None, 'label': f"{team} to win",
                       'reason': f"The model makes {team} {wp * 100:.0f}% to win{f', the market {mk * 100:.0f}%' if mk else ''}, counting the starting goalies."})
HC.sort(key=lambda x: -x['p']); LS.sort(key=lambda x: -x['p'])
cnt = {}
HC = [x for x in HC if x.get('kind') != 'player' or (cnt.setdefault(x['id'], 0) < 1 and not cnt.__setitem__(x['id'], 1))][:40]
cnt = {}
LS = [x for x in LS if cnt.setdefault(x['id'], 0) < 2 and not cnt.__setitem__(x['id'], cnt[x['id']] + 1)][:80]
sl.log('props', len(PROPS), 'with lines', sum(1 for x in PROPS if x['lines'] or x['yes']), '| goalies', len(GOALIES), '| high-chance', len(HC), '| long shots', len(LS))

# ================================================================== records, trends, chart logs
def team_records():
    out = {}
    cur_ = GAMES[(GAMES.season == SEASON) & (GAMES.state == 'post') & GAMES.hs.notna()].sort_values('k')
    for t in TEAMS:
        x = cur_[(cur_.home == t) | (cur_.away == t)]
        res, ouv, gf, ga, mlr = [], [], [], [], []
        for g in x.itertuples():
            home = g.home == t; f_, a_2 = (g.hs, g.as_) if home else (g.as_, g.hs)
            gf.append(f_); ga.append(a_2)
            extra = bool(g.ot) or (isinstance(g.detail, str) and ('OT' in g.detail or 'SO' in g.detail))
            res.append('W' if f_ > a_2 else ('OTL' if extra else 'L'))
            o = LINE.get(g.id) or {}
            if o.get('total') is not None:
                tot = g.hs + g.as_; ouv.append('P' if tot == o['total'] else 'O' if tot > o['total'] else 'U')
        W = res.count('W'); L = res.count('L'); OTL = res.count('OTL')
        streak = ''
        if res:
            n = 1
            while n < len(res) and res[-n - 1] == res[-1]:
                n += 1
            streak = ('W' if res[-1] == 'W' else 'L') + str(n)
        out[t] = {'rec': {'W': W, 'L': L, 'OTL': OTL}, 'pts': 2 * W + OTL, 'gp': len(res), 'l10': {'W': res[-10:].count('W'), 'L': res[-10:].count('L'), 'OTL': res[-10:].count('OTL')},
                  'gf': round(float(np.mean(gf)), 2) if gf else None, 'ga': round(float(np.mean(ga)), 2) if ga else None, 'last': res[-5:], 'ou': {'O': ouv.count('O'), 'U': ouv.count('U'), 'P': ouv.count('P')},
                  'ou_last': ouv[-5:], 'streak': streak}
    return out


TREC = team_records()
RATING = {t: {'att': round(O.get(t, 0), 3), 'def': round(Dd.get(t, 0), 3), 'shots_for': round(SO.get(t, 0), 3), 'shots_against': round(SD.get(t, 0), 3),
              'gk': usual_starter(t)} for t in TEAMS}
for t, r in RATING.items():
    r['gk_name'] = PNAME.get(r['gk']); r['gk_sv'] = round(gk_sv(r['gk']), 4) if r['gk'] else None
rk = lambda key, rev=True: {t: i + 1 for i, (t, v) in enumerate(sorted(RATING.items(), key=lambda kv: (-kv[1][key] if rev else kv[1][key])))}
RK_A, RK_D, RK_S = rk('att'), rk('def'), rk('shots_for')
TEAMS_OUT = {t: dict(v, **TREC.get(t, {}), rating=RATING.get(t), rk={'att': RK_A.get(t), 'def': RK_D.get(t), 'shots': RK_S.get(t)},
                     inj=len([e for e in INJ.get(t, []) if e['level'] in ('out', 'doubt')])) for t, v in TEAMS.items()}
TRENDS_P, TRENDS_T = [], []
for it in PROPS:
    pid = int(it['id']); x = pl[pl.player_id == pid].tail(12)
    if len(x) < 5:
        continue
    for k, col, base in (('goals', 'goals', 0.5), ('points', 'points', 0.5), ('sog', 'shots_on_goal', None)):
        vals = x[col].tolist()
        ln = it['lines'].get(k, {}).get('line') if k in it['lines'] else None
        b = base if base is not None else (ln if ln is not None else math.floor(it['proj']['sog']) + 0.5)
        if k == 'sog' and b < 1.5:
            continue
        n = 0
        for v in reversed(vals):
            if v > b: n += 1
            else: break
        if n >= (3 if k == 'goals' else 4):
            TRENDS_P.append({'id': it['id'], 'name': it['name'], 'team': it['team'], 'opp': it['opp'], 'game': it['game'], 'key': k, 'line': b, 'dir': 'over', 'n': n,
                             'vals': vals[-8:], 'proj': it['proj'][k], 'book': ln is not None})
TRENDS_P.sort(key=lambda x: (-x['n'], -x['proj']))
for t in TEAMS:
    x = GAMES[(GAMES.season == SEASON) & (GAMES.state == 'post') & GAMES.hs.notna() & ((GAMES.home == t) | (GAMES.away == t))].sort_values('k')
    su, ou_ = [], []
    for g in x.itertuples():
        home = g.home == t; su.append('W' if (g.hs > g.as_) == home else 'L')
        o = LINE.get(g.id) or {}
        if o.get('total') is not None:
            tot = g.hs + g.as_; ou_.append('P' if tot == o['total'] else 'O' if tot > o['total'] else 'U')
    for seq, a, what, kind in ((su, 'W', 'won', 'su'), (su, 'L', 'lost', 'su'), (ou_, 'O', 'gone over', 'ou'), (ou_, 'U', 'gone under', 'ou')):
        n = 0
        for s_ in reversed(seq):
            if s_ == a: n += 1
            else: break
        if n >= 3:
            TRENDS_T.append({'team': t, 'what': what, 'n': n, 'kind': kind, 'seq': seq[-10:]})
TRENDS_T.sort(key=lambda x: -x['n'])
PCOLS = ['day', 'opp', 'home', 'toi', 'goals', 'assists', 'points', 'sog', 'hits', 'blocks']
PLOGS = {}
for pid in {int(x['id']) for x in PROPS} | {int(x['id']) for x in LS} | {int(x['id']) for x in HC if x.get('kind') == 'player'}:
    x = pl[pl.player_id == pid].tail(25)
    PLOGS[str(pid)] = {'n': PNAME.get(pid), 't': PTEAM.get(pid), 'p': PPOS.get(pid, ''),
                       'rows': [[sl.et_day(r.t), r.opp, 1 if r.team_abbrev == r.home else 0, round(r.toi_m, 1), int(r.goals), int(r.assists), int(r.points), int(r.shots_on_goal),
                                 int(r.hits), int(r.blocked_shots)] for r in x.itertuples()]}
GCOLS = ['day', 'opp', 'home', 'saves', 'shots', 'ga', 'start']
GLOGS = {}
for gk in {int(x['id']) for x in GOALIES}:
    x = GB[GB.player_id == gk].tail(20)
    GLOGS[str(gk)] = {'n': PNAME.get(gk), 't': PTEAM.get(gk), 'rows': [[sl.et_day(r.t), (gi.at[r.game_id, 'away'] if gi.at[r.game_id, 'home'] == r.team_abbrev else gi.at[r.game_id, 'home']) if r.game_id in gi.index else '',
                                                                       1 if r.game_id in gi.index and gi.at[r.game_id, 'home'] == r.team_abbrev else 0,
                                                                       None if r.saves != r.saves else int(r.saves), None if r.shots_against != r.shots_against else int(r.shots_against),
                                                                       None if r.shots_against != r.shots_against else int(r.shots_against - r.saves), 1 if r.is_start else 0] for r in x.itertuples()]}
TCOLS = ['day', 'opp', 'home', 'gf', 'ga', 'total', 'ml']
TLOGS = {}
for t in TEAMS:
    x = GAMES[((GAMES.home == t) | (GAMES.away == t)) & (GAMES.state == 'post') & GAMES.hs.notna()].sort_values('k').tail(30)
    TLOGS[t] = [[g.day, g.away if g.home == t else g.home, 1 if g.home == t else 0, int(g.hs if g.home == t else g.as_), int(g.as_ if g.home == t else g.hs),
                 (LINE.get(g.id) or {}).get('total'), (LINE.get(g.id) or {}).get('ml_h' if g.home == t else 'ml_a')] for g in x.itertuples()]

# ================================================================== output
def odds_out(o):
    if not o:
        return None
    return {k: o.get(k) for k in ('spread', 'total', 'ml_h', 'ml_a', 'sp_h', 'sp_a', 'o', 'u', 'total_open', 'ml_h_open', 'ml_a_open', 'book')}


games_out = []
for g in GAMES[(GAMES.day >= DAYS[1]) & (GAMES.day <= DAYS[-1])].itertuples():
    p = PRED.get(g.id); o = LINE.get(g.id) if g.state == 'post' else (got.get(g.id) or LINE.get(g.id))
    m = None
    if p:
        mk = sl.novig(o['ml_h'], o['ml_a']) if o and o.get('ml_h') and o.get('ml_a') else None
        pov = float(1 - poisson.cdf(math.floor(o['total']), p['lam_h'] + p['lam_a'])) if o and o.get('total') is not None else None
        m = {'lam_h': p['lam_h'], 'lam_a': p['lam_a'], 'total': p['total'], 'wp_home': p['wp_home'], 'mkt_wp_home': round(mk, 4) if mk else None,
             'pick_su': g.home if p['wp_home'] > 0.5 else g.away, 'edge': round(p['wp_home'] - mk, 4) if mk else None,
             'value': (g.home if p['wp_home'] > mk else g.away) if mk and abs(p['wp_home'] - mk) >= 0.05 else None,
             'p_over': round(pov, 4) if pov is not None else None, 'p_h_by2': p['p_h_by2'], 'p_a_by2': p['p_a_by2'], 'parts': p['parts']}
    rec_h = getattr(g, 'home_rec', None); rec_a = getattr(g, 'away_rec', None)
    games_out.append({'id': str(g.id), 'eid': G2E.get(g.id), 'day': g.day, 'k': g.k.isoformat(), 'away': g.away, 'home': g.home, 'state': g.state,
                      'detail': g.detail if isinstance(g.detail, str) else '', 'as': None if g.as_ is None or g.as_ != g.as_ else int(g.as_),
                      'hs': None if g.hs is None or g.hs != g.hs else int(g.hs), 'venue': g.venue if isinstance(g.venue, str) else '', 'odds': odds_out(o), 'model': m,
                      'goalies': {'h': {'id': str(p['gk_h']) if p and p['gk_h'] else None, 'name': PNAME.get(p['gk_h']) if p else None, 'src': p['gk_src_h'] if p else None, 'sv': p['sv_h'] if p else None},
                                  'a': {'id': str(p['gk_a']) if p and p['gk_a'] else None, 'name': PNAME.get(p['gk_a']) if p else None, 'src': p['gk_src_a'] if p else None, 'sv': p['sv_a'] if p else None}} if p else None,
                      'rest': {'h': p['rest_h'], 'a': p['rest_a'], 'b2b_h': bool(p['b2b_h']), 'b2b_a': bool(p['b2b_a'])} if p else None,
                      'rec': {'h': json.loads(rec_h) if isinstance(rec_h, str) else None, 'a': json.loads(rec_a) if isinstance(rec_a, str) else None}})
inj_out = {}
for t, lst in INJ.items():
    rows = []
    for e in lst:
        toi = FORM.get(e['pid'], {}).get('toi_ew') if e['pid'] else None
        rows.append(dict(e, pid=str(e['pid']) if e['pid'] else None, toi=round(toi, 1) if toi else None, key=bool(toi and toi >= 16) or (e['pid'] in TEAM_STARTS.get(t, [])[-10:])))
    order = {'out': 0, 'doubt': 1, 'gtd': 2, 'likely': 3}
    rows.sort(key=lambda r: (not r['key'], order.get(r['level'], 9), -(r['toi'] or 0)))
    inj_out[t] = rows
cut = NOW - pd.Timedelta(days=21)
gg = {}
for g in GAMES[(GAMES.k >= cut) & (GAMES.day <= DAYS[-1])].itertuples():
    o = LINE.get(g.id) or {}
    rec_ = {'a': g.away, 'h': g.home, 'k': g.k.isoformat(), 'd': g.day, 'hs': None if g.state != 'post' or g.hs is None or g.hs != g.hs else int(g.hs),
            'as': None if g.state != 'post' or g.as_ is None or g.as_ != g.as_ else int(g.as_), 'sp': None if o.get('spread') is None else -o['spread'], 'tl': o.get('total'),
            'mlh': o.get('ml_h'), 'mla': o.get('ml_a')}
    if rec_['hs'] is not None and g.id in set(SK.game_id):
        rec_['b'] = 1
    if g.id in FIRST and FIRST[g.id][0] is not None:
        rec_['f'] = str(FIRST[g.id][0]) if FIRST[g.id][0] else ''; rec_['fn'] = FIRST[g.id][1]
    gg[str(g.id)] = rec_
gp = {}
recent_ids = set(int(k) for k in gg)
for r in SK[SK.game_id.isin(recent_ids)].itertuples():
    e = gp.setdefault(str(r.player_id), {'n': r.player_name, 't': r.team_abbrev, 'p': r.position, 'g': {}})
    e['g'][str(r.game_id)] = [int(r.goals), int(r.assists), int(r.points), int(r.shots_on_goal), int(r.hits), int(r.blocked_shots), round(r.toi_m), 0, 0, 0]
for r in GB[GB.game_id.isin(recent_ids) & (GB.shots_against > 0)].itertuples():
    e = gp.setdefault(str(r.player_id), {'n': r.player_name, 't': r.team_abbrev, 'p': 'G', 'g': {}})
    e['g'][str(r.game_id)] = [0, 0, 0, 0, 0, 0, round(toi_min(r.toi)), int(r.saves), int(r.shots_against - r.saves), int(r.shots_against)]
GRADE = {'sport': LG, 'asof': NOW.isoformat(timespec='seconds'), 'games': gg, 'players': gp}
season_label = f'{SEASON - 1}-{str(SEASON)[-2:]}'
meta = {'sport': LG, 'season': season_label, 'asof': NOW.isoformat(timespec='seconds'), 'slate': SLATE, 'days': DAYS[1:], 'espn': 'hockey/nhl',
        'stats_through': SK.t.max().tz_convert(sl.ET).date().isoformat() if len(SK) else None, 'lg_sv': round(LG_SV, 4),
        'sources': ['fastRhockey box scores and schedules (sportsdataverse), refreshed daily', "The NHL's schedule, box-score and scoring feeds",
                    'ESPN scoreboard (probable goalies), rosters and injury list', 'ESPN odds records: game lines and player props (DraftKings, ESPN BET when DraftKings has none)'],
        'injuries_ok': bool(INJ_RAW), 'odds_ok': any(v for v in got.values()), 'props_ok': any(PLINES.values())}
data = {'meta': meta, 'teams': TEAMS_OUT, 'games': games_out, 'injuries': inj_out, 'props': PROPS, 'goalies': GOALIES, 'high_chance': HC, 'long_shots': LS,
        'trends': {'player': TRENDS_P[:60], 'team': TRENDS_T[:40]},
        'model': {'record': REC, 'log': model_log[-400:], 'backtest': S['backtest']},
        'research': {'props': S['prop_backtest'], 'situational': S['situational'], 'carry': S['carry'], 'blend': BLEND},
        'cal': CAL, 'sv_sd': PP['sv_sd']}
sl.write_json(os.path.join(OUT, 'data.json'), data)
sl.write_json(os.path.join(OUT, 'logs.json'), {'pcols': PCOLS, 'players': PLOGS, 'gcols': GCOLS, 'goalies': GLOGS, 'tcols': TCOLS, 'teams': TLOGS})
sl.write_json(os.path.join(OUT, 'grade.json'), GRADE)
keep = {str(x) for x in GAMES[GAMES.season >= SEASON - 1].id}
sl.write_json(os.path.join(OUT, 'odds_log.json'), {k: v for k, v in OLOG.items() if k in keep})
today = [g for g in games_out if g['day'] == SLATE] or [g for g in games_out if g['day'] > SLATE][:16]
picks = []
hp = [x for x in HC if x.get('kind') in ('player', 'goalie')]
if hp: picks.append({'tag': 'hc', 't': hp[0]['label'], 's': f"{hp[0]['team']} vs {hp[0]['opp']}", 'v': f"{round(hp[0]['p'] * 100)}%", 'view': 'hc'})
la = [x for x in LS if x['type'] == 'atg']
if la: picks.append({'tag': 'ls', 't': la[0]['label'], 's': f"{la[0]['team']} vs {la[0]['opp']} · fair {sl.odds_of(la[0]['p']):+d}", 'v': f"{round(la[0]['p'] * 100)}%", 'view': 'ls'})
mg = [g for g in games_out if g['state'] == 'pre' and g['model']]
if mg:
    g = max(mg, key=lambda g: abs(g['model']['wp_home'] - 0.5)); t_ = g['model']['pick_su']; wp_ = g['model']['wp_home'] if t_ == g['home'] else 1 - g['model']['wp_home']
    picks.append({'tag': 'md', 't': f"{t_} to win", 's': f"{g['away']} @ {g['home']}", 'v': f"{round(wp_ * 100)}%", 'view': 'model'})
nxt = next((g for g in games_out if g['state'] == 'pre'), None)
summ = {'sport': LG, 'asof': meta['asof'], 'season': season_label, 'period': 'Today' if today and today[0]['day'] == SLATE else 'Next games', 'espn': 'hockey/nhl',
        'games': [{'id': g['id'], 'eid': g['eid'], 'a': g['away'], 'h': g['home'], 'k': g['k'], 'st': g['state'], 'as': g['as'], 'hs': g['hs'], 'det': g['detail'],
                   'line': (f"{g['home']} {g['odds']['ml_h']:+d}" if g['odds']['ml_h'] < 0 else f"{g['away']} {g['odds']['ml_a']:+d}") if g['odds'] and g['odds'].get('ml_h') and g['odds'].get('ml_a') else None,
                   'pick': (g['model'] or {}).get('pick_su')} for g in today],
        'next': {'k': nxt['k'], 'a': nxt['away'], 'h': nxt['home']} if nxt else None, 'picks': picks,
        'record': f"Model {REC['su'][0]}-{REC['su'][1]} picking winners this season" if sum(REC['su']) else None,
        'links': [['games', 'Games'], ['props', 'Props'], ['hc', 'High-chance'], ['ls', 'Long shots'], ['trends', 'Trends']]}
if not today:
    summ['note'] = 'No games on the schedule in the next few days.'
sl.write_json(os.path.join(OUT, 'summary.json'), summ)
