"""Rebuild site/nba/data/ (data.json, grade.json, summary.json, odds_log.json) from the latest public data.

Sources: box scores and schedules from the sportsdataverse hoopR release files (refreshed daily), ESPN's scoreboard,
game summaries (box scores for last night before the release files catch up), odds records (game lines and
player-prop lines, DraftKings first) and injury list. The research behind every number ships in static/nba_model.json.

    python pipeline/nba.py
"""
import os, sys, json, math, re, datetime as dt
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sportslib as sl, sports_teams as stt          # noqa: E402

LG = 'nba'
OUT = os.path.join(ROOT, 'site', 'nba', 'data')
CACHE = os.path.join(HERE, '.cache', 'nba')
LIVE = 'https://gunnarc28-hub.github.io/NFL-EDGE/nba/data/'
NOW = pd.Timestamp(os.environ['SE_NOW']).tz_convert('UTC') if os.environ.get('SE_NOW') else pd.Timestamp.now(tz='UTC')     # SE_NOW pins the clock for tests
S = json.load(open(os.path.join(HERE, 'static', 'nba_model.json')))
SEASON = NOW.year + 1 if NOW.month >= 8 else NOW.year            # hoopR labels a season by the year it ends
SLATE = sl.slate_day(NOW)
TEAMS = stt.table('nba')
STATS = ['pts', 'reb', 'ast', 'fg3m', 'stl', 'blk', 'tov']
COMBO = {'pra': ['pts', 'reb', 'ast'], 'pr': ['pts', 'reb'], 'pa': ['pts', 'ast'], 'ra': ['reb', 'ast']}
ALL = STATS + list(COMBO)
LABEL = {'pts': 'Points', 'reb': 'Rebounds', 'ast': 'Assists', 'fg3m': '3-pointers', 'stl': 'Steals', 'blk': 'Blocks', 'tov': 'Turnovers',
         'pra': 'Pts + reb + ast', 'pr': 'Pts + reb', 'pa': 'Pts + ast', 'ra': 'Reb + ast'}
SHORT = {'pts': 'points', 'reb': 'rebounds', 'ast': 'assists', 'fg3m': '3-pointers', 'stl': 'steals', 'blk': 'blocks', 'tov': 'turnovers',
         'pra': 'pts+reb+ast', 'pr': 'pts+reb', 'pa': 'pts+ast', 'ra': 'reb+ast'}
sl.log('NBA season', SEASON, 'slate', SLATE, 'now', NOW.isoformat())


def fix_ab(a):
    a = str(a or '')
    return stt.ESPN_NBA.get(a, a)


# ================================================================== history: box scores and schedules
def load(kind, season, required):
    tag = {'player_box': 'espn_nba_player_boxscores', 'team_box': 'espn_nba_team_boxscores', 'schedule': 'espn_nba_schedules'}[kind]
    fname = f'nba_schedule_{season}.csv' if kind == 'schedule' else f'{kind}_{season}.csv'
    p = sl.sdv_csv(tag, fname, CACHE, required=required)
    if not p:
        return pd.DataFrame()
    return pd.read_csv(p, low_memory=False)


PB = pd.concat([load('player_box', SEASON - 1, True), load('player_box', SEASON, False)], ignore_index=True)
TB = pd.concat([load('team_box', SEASON - 1, True), load('team_box', SEASON, False)], ignore_index=True)
SCH = pd.concat([load('schedule', SEASON - 1, True), load('schedule', SEASON, False)], ignore_index=True)
SCH = SCH[SCH.season_type.isin([2, 3])].drop_duplicates('id')
PB = PB[PB.season_type.isin([2, 3])].drop_duplicates(['game_id', 'athlete_id'])
TB = TB[TB.season_type.isin([2, 3])].drop_duplicates(['game_id', 'team_abbreviation'])
sl.log('history rows: players', len(PB), 'teams', len(TB), 'schedule', len(SCH))

# ================================================================== ESPN: the days around the slate
day0 = pd.Timestamp(SLATE)
DAYS = [(day0 + pd.Timedelta(days=i)).date().isoformat() for i in (-3, -2, -1, 0, 1, 2)]
BOARD = {}
for d_, evs in zip(DAYS, sl.parallel(lambda d: sl.scoreboard(LG, d), DAYS, 6)):
    for e in evs:
        if e['season_type'] in (2, 3, 5, None):
            e['day'] = d_; BOARD[e['id']] = e
sl.log('scoreboard events', len(BOARD), 'by day', {d: sum(1 for e in BOARD.values() if e['day'] == d) for d in DAYS})

# ================================================================== games: schedule + live board
G = {}
for r in SCH.itertuples():
    gid = str(r.id)
    t = pd.Timestamp(r.date) if str(r.date) != 'nan' else None
    if t is None:
        continue
    t = t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')
    done = str(r.status_type_completed).lower() in ('true', '1')
    G[gid] = {'id': gid, 'k': t, 'season': int(r.season), 'st': int(r.season_type), 'home': fix_ab(r.home_abbreviation), 'away': fix_ab(r.away_abbreviation),
              'hs': float(r.home_score) if done and r.home_score == r.home_score else None, 'as': float(r.away_score) if done and r.away_score == r.away_score else None,
              'state': 'post' if done else 'pre', 'detail': 'Final' if done else '', 'neutral': str(r.neutral_site).lower() in ('true', '1'),
              'venue': str(r.venue_full_name) if 'venue_full_name' in SCH.columns and str(r.venue_full_name) != 'nan' else ''}
for e in BOARD.values():
    h, a = fix_ab(e['home']['abbr']), fix_ab(e['away']['abbr'])
    if h not in TEAMS or a not in TEAMS:
        continue
    t = pd.Timestamp(e['date']).tz_convert('UTC') if pd.Timestamp(e['date']).tzinfo else pd.Timestamp(e['date']).tz_localize('UTC')
    g = G.setdefault(e['id'], {'id': e['id'], 'season': SEASON, 'st': e['season_type'] or 2, 'home': h, 'away': a, 'neutral': e['neutral'], 'venue': e['venue']})
    g.update({'k': t, 'state': e['state'] or g.get('state', 'pre'), 'detail': e['detail'], 'venue': e['venue'] or g.get('venue', '')})
    if e['state'] in ('in', 'post') and e['home']['score'] is not None:
        g['hs'], g['as'] = e['home']['score'], e['away']['score']
    if e['state'] == 'in':
        g['live'] = True
    if e['state'] == 'post' and not e['completed']:
        g['state'] = 'post'
    for side, x in (('home', e['home']), ('away', e['away'])):
        g[side + '_rec'] = x['rec']
GAMES = pd.DataFrame(G.values()).rename(columns={'as': 'as_'})
GAMES['day'] = GAMES.k.map(sl.et_day)
GAMES = GAMES.sort_values('k').reset_index(drop=True)
sl.log('games', len(GAMES), 'this season', int((GAMES.season == SEASON).sum()))

# ================================================================== recent box scores the release files don't have yet
have = set(PB.game_id.astype(str))
need = [g for g in GAMES.itertuples() if g.state == 'post' and g.id not in have and g.k > NOW - pd.Timedelta(days=4)]


def parse_summary(gid):
    j = sl.summary(LG, gid)
    rows = []
    for tm in ((j or {}).get('boxscore') or {}).get('players') or []:
        ab = fix_ab((tm.get('team') or {}).get('abbreviation'))
        for blk in tm.get('statistics') or []:
            keys = blk.get('keys') or blk.get('names') or []
            for a in blk.get('athletes') or []:
                ath = a.get('athlete') or {}
                st = dict(zip(keys, a.get('stats') or []))
                def n(k):
                    v = st.get(k)
                    try: return float(str(v).split('-')[0]) if v not in (None, '', '--') else 0.0
                    except ValueError: return 0.0
                def ma(k):
                    v = str(st.get(k) or '0-0').split('-')
                    try: return float(v[0]), float(v[1])
                    except (ValueError, IndexError): return 0.0, 0.0
                fgm, fga = ma('fieldGoalsMade-fieldGoalsAttempted'); f3m, f3a = ma('threePointFieldGoalsMade-threePointFieldGoalsAttempted'); ftm, fta = ma('freeThrowsMade-freeThrowsAttempted')
                dnp = bool(a.get('didNotPlay')) or not st
                rows.append({'game_id': gid, 'athlete_id': str(ath.get('id')), 'athlete_display_name': ath.get('displayName'), 'team_abbreviation': ab,
                             'athlete_position_abbreviation': (ath.get('position') or {}).get('abbreviation'), 'minutes': n('minutes') if not dnp else np.nan,
                             'points': n('points'), 'rebounds': n('rebounds'), 'assists': n('assists'), 'three_point_field_goals_made': f3m, 'steals': n('steals'),
                             'blocks': n('blocks'), 'turnovers': n('turnovers'), 'field_goals_made': fgm, 'field_goals_attempted': fga, 'free_throws_made': ftm,
                             'free_throws_attempted': fta, 'offensive_rebounds': n('offensiveRebounds'), 'defensive_rebounds': n('defensiveRebounds'), 'fouls': n('fouls'),
                             'plus_minus': n('plusMinus'), 'starter': bool(a.get('starter')), 'did_not_play': dnp, 'reason': a.get('reason')})
    return rows


extra = []
if need:
    for rows in sl.parallel(parse_summary, [g.id for g in need], 6):
        extra += rows
    sl.log('box scores from ESPN summaries:', len(need), 'games,', len(extra), 'rows')
if extra:
    X = pd.DataFrame(extra)
    gm = GAMES.set_index('id')
    X['game_date_time'] = X.game_id.map(lambda i: gm.at[i, 'k'].isoformat())
    X['season'] = SEASON; X['season_type'] = X.game_id.map(lambda i: gm.at[i, 'st'])
    X['opponent_team_abbreviation'] = [gm.at[r.game_id, 'away'] if r.team_abbreviation == gm.at[r.game_id, 'home'] else gm.at[r.game_id, 'home'] for r in X.itertuples()]
    X['home_away'] = ['home' if r.team_abbreviation == gm.at[r.game_id, 'home'] else 'away' for r in X.itertuples()]
    PB = pd.concat([PB, X], ignore_index=True)

# ================================================================== tidy player box
P = PB.copy()
P['game_id'] = P.game_id.astype(str); P['athlete_id'] = P.athlete_id.astype(str).str.replace(r'\.0$', '', regex=True)
P['team_abbreviation'] = P.team_abbreviation.map(fix_ab); P['opponent_team_abbreviation'] = P.opponent_team_abbreviation.map(fix_ab)
P['t'] = pd.to_datetime(P.game_date_time, utc=True, format='ISO8601')
P['min'] = pd.to_numeric(P.minutes, errors='coerce').fillna(0)
P['played'] = (P['min'] > 0) & (~P.did_not_play.astype(str).str.lower().isin(['true', '1']))
NUM = ['points', 'rebounds', 'assists', 'three_point_field_goals_made', 'steals', 'blocks', 'turnovers', 'field_goals_made', 'field_goals_attempted',
       'free_throws_made', 'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds', 'fouls', 'plus_minus']
for c in NUM:
    P[c] = pd.to_numeric(P[c], errors='coerce').fillna(0)
P['pts'], P['reb'], P['ast'], P['fg3m'], P['stl'], P['blk'], P['tov'] = P.points, P.rebounds, P.assists, P.three_point_field_goals_made, P.steals, P.blocks, P.turnovers
P['gmsc'] = (P.points + 0.4 * P.field_goals_made - 0.7 * P.field_goals_attempted - 0.4 * (P.free_throws_attempted - P.free_throws_made) + 0.7 * P.offensive_rebounds
             + 0.3 * P.defensive_rebounds + P.steals + 0.7 * P.assists + 0.7 * P.blocks - 0.4 * P.fouls - P.turnovers)
P = P.sort_values(['t', 'game_id']).reset_index(drop=True)
P['pos1'] = P.athlete_position_abbreviation.fillna('F').astype(str).str[0].replace({'P': 'G', 'S': 'G'})
NAMES = P.groupby('athlete_id').athlete_display_name.last().to_dict()
LAST_TEAM = P[P.played].groupby('athlete_id').team_abbreviation.last().to_dict()
POS = P.groupby('athlete_id').athlete_position_abbreviation.last().fillna('').to_dict()

# possessions per game from team boxes (+ ESPN-summary games from the player rows)
TB['game_id'] = TB.game_id.astype(str); TB['team_abbreviation'] = TB.team_abbreviation.map(fix_ab)
tov_col = TB.total_turnovers.fillna(TB.turnovers) if 'total_turnovers' in TB else TB.turnovers
TB['poss'] = TB.field_goals_attempted - TB.offensive_rebounds + tov_col + 0.44 * TB.free_throws_attempted
POSS = TB.groupby('game_id').poss.mean().to_dict()
pp = P[P.played].groupby(['game_id', 'team_abbreviation'])[['field_goals_attempted', 'offensive_rebounds', 'turnovers', 'free_throws_attempted']].sum()
pp['poss'] = pp.field_goals_attempted - pp.offensive_rebounds + pp.turnovers + 0.44 * pp.free_throws_attempted
for gid, v in pp.groupby(level=0).poss.mean().items():
    POSS.setdefault(gid, float(v))

# ================================================================== odds: the log of last pre-game lines (kept on the live site between runs)
def load_log():
    j = sl.get_json(LIVE + 'odds_log.json?t=' + str(int(NOW.timestamp())), quiet=True)
    if j is None and os.path.exists(os.path.join(OUT, 'odds_log.json')):
        j = json.load(open(os.path.join(OUT, 'odds_log.json')))
    return j or {}


OLOG = load_log()
upcoming = GAMES[(GAMES.day >= DAYS[2]) & (GAMES.day <= DAYS[-1])]
todo = [g.id for g in upcoming.itertuples() if g.state == 'pre' or g.id not in OLOG]
# backfill: finished games this season with no saved line (first runs, or a missed window); a few dozen per run
missing = [g.id for g in GAMES[(GAMES.season == SEASON) & (GAMES.state == 'post')].itertuples() if g.id not in OLOG]
missing = missing[max(0, len(missing) - int(os.environ.get('SE_BACKFILL', 80))):]
got = dict(zip(todo + missing, sl.parallel(lambda e: sl.game_odds(LG, e), todo + missing, 8)))
n_new = 0
for gid, o in got.items():
    if not o:
        continue
    g = GAMES[GAMES.id == gid].iloc[0]
    if g.state == 'pre' or gid not in OLOG:              # keep the last line seen before the game started
        o['seen'] = NOW.isoformat(timespec='minutes'); OLOG[gid] = o; n_new += 1
sl.log('odds: fetched', sum(1 for v in got.values() if v), 'of', len(got), '| log size', len(OLOG))
LINE = {gid: o for gid, o in OLOG.items()}

# ================================================================== team ratings, game by game (the research model)
R = S['ratings']; MM = S['margin_model']; TM = S['total_model']
done_games = GAMES[(GAMES.state == 'post') & GAMES.hs.notna()]
a_ = 0.5 ** (1 / R['half_life_games']); ap_ = 0.5 ** (1 / R['pace_half_life'])
O, Dd, PACE, LAST, NG = {}, {}, {}, {}, {}
lg_eff, lg_pace = R['lg_eff'], R['lg_pace']
season_ = None
PRE = {}            # game id -> ratings-based prediction made before the game
hist = []
for g in GAMES.itertuples():
    if g.season != season_:
        season_ = g.season
        for t in list(O): O[t] *= R['carry']; Dd[t] *= R['carry']
        NG = {}
    h, w = g.home, g.away
    for t in (h, w):
        O.setdefault(t, 0.0); Dd.setdefault(t, 0.0); PACE.setdefault(t, lg_pace)
    dd = pd.Timestamp(g.day)                         # rest in calendar days (Eastern): a back-to-back is a game yesterday
    rest_h = min((dd - LAST[h]).days, 7) if h in LAST else 7
    rest_a = min((dd - LAST[w]).days, 7) if w in LAST else 7
    pace = (PACE[h] + PACE[w]) / 2
    eff_h = lg_eff + O[h] - Dd[w]; eff_a = lg_eff + O[w] - Dd[h]
    PRE[g.id] = {'rate_m': (eff_h - eff_a) * pace / 100, 'rate_t': (eff_h + eff_a) * pace / 100, 'rest_h': rest_h, 'rest_a': rest_a, 'pace': pace,
                 'n_h': NG.get(h, 0), 'n_a': NG.get(w, 0), 'O_h': O[h], 'D_h': Dd[h], 'O_a': O[w], 'D_a': Dd[w]}
    if g.state == 'post' and g.hs == g.hs and g.hs is not None:
        ph = POSS.get(g.id)
        if ph and ph > 50:
            off_h = g.hs / ph * 100; off_a = g.as_ / ph * 100
            hadj = 0 if g.neutral else R['hca'] / 2
            e_h = off_h - hadj - (lg_eff + O[h] - Dd[w]); e_a = off_a + hadj - (lg_eff + O[w] - Dd[h])
            O[h] += (1 - a_) * e_h; Dd[w] -= (1 - a_) * e_h; O[w] += (1 - a_) * e_a; Dd[h] -= (1 - a_) * e_a
            lg_eff = 0.995 * lg_eff + 0.005 * (off_h + off_a) / 2
            PACE[h] = ap_ * PACE[h] + (1 - ap_) * ph; PACE[w] = ap_ * PACE[w] + (1 - ap_) * ph
            lg_pace = 0.995 * lg_pace + 0.005 * ph
        LAST[h] = dd; LAST[w] = dd; NG[h] = NG.get(h, 0) + 1; NG[w] = NG.get(w, 0) + 1
    elif g.k <= NOW:
        LAST[h] = dd; LAST[w] = dd
RATING = {t: {'off': round(O[t], 2), 'def': round(Dd[t], 2), 'net': round(O[t] + Dd[t], 2), 'pace': round(PACE[t], 1)} for t in TEAMS if t in O}

# ================================================================== who's in the rotation, and what each player is worth
AV = S['availability']; ha = 0.5 ** (1 / AV['half_life'])
ROT = {}                          # team -> {pid: {'min', 'gpm', 'idx', 'n', 'last'}}
TEAM_IDX = {}
MISS_HIST = {}                    # (gid, team) -> (missing value, available value) from who actually played
order = P.drop_duplicates(['game_id', 'team_abbreviation'])[['game_id', 'team_abbreviation', 't']].sort_values('t')
grp = {k: v for k, v in P.groupby(['game_id', 'team_abbreviation'], sort=False)}
for r in order.itertuples():
    team = r.team_abbreviation; x = grp[(r.game_id, team)]
    st_ = ROT.setdefault(team, {}); i = TEAM_IDX.get(team, 0)
    played = set(x[x.played].athlete_id)
    mv = av = 0.0
    for pid, s_ in st_.items():
        if i - s_['idx'] > AV['recent_games'] or s_['min'] < AV['min_minutes']:
            continue
        v = (s_['gpm'] - AV['repl']) * s_['min']
        if pid in played: av += v
        else: mv += v
    MISS_HIST[(r.game_id, team)] = (mv, av)
    for q in x[x.played].itertuples():
        s_ = st_.get(q.athlete_id); gpm = q.gmsc / max(q.min, 1)
        if s_ is None: st_[q.athlete_id] = {'min': q.min, 'gpm': gpm, 'idx': i, 'n': 1, 'last': q.t}
        else:
            w_ = min(ha, 1 - 1 / (s_['n'] + 1))
            s_['min'] = w_ * s_['min'] + (1 - w_) * q.min; s_['gpm'] = w_ * s_['gpm'] + (1 - w_) * gpm; s_['idx'] = i; s_['n'] += 1; s_['last'] = q.t
    TEAM_IDX[team] = i + 1

# ================================================================== injuries (ESPN)
INJ_RAW = sl.injuries(LG)
NAME2AB = {v['name']: k for k, v in TEAMS.items()}
NAME2AB.update({'LA Clippers': 'LAC', 'Los Angeles Clippers': 'LAC'})
INJ = {}
LEVEL = {'out': 'out', 'doubtful': 'doubt', 'questionable': 'gtd', 'day-to-day': 'gtd', 'probable': 'likely', 'suspension': 'out', 'injured reserve': 'out'}
for e in INJ_RAW:
    t = NAME2AB.get(e['team_name']) or fix_ab(e['team'])
    if t not in TEAMS or not e['name']:
        continue
    stt_ = e['status'].lower()
    lvl = next((v for k, v in LEVEL.items() if k in stt_), 'gtd')
    if e['fs'] in ('OUT', 'O'): lvl = 'out'
    INJ.setdefault(t, []).append({'name': e['name'], 'id': e['athlete'], 'pos': e['pos'], 'status': e['status'], 'level': lvl, 'injury': e['injury'] or '',
                                  'detail': e['detail'] or '', 'ret': e['ret'], 'date': e['date'], 'comment': e['comment']})
OUT_W = {'out': 1.0, 'doubt': 0.8, 'gtd': 0.35, 'likely': 0.0}
sl.log('injuries: teams', len(INJ), 'players', sum(len(v) for v in INJ.values()))


def out_weight(team, pid, name):
    for e in INJ.get(team, []):
        if (e['id'] and e['id'] == pid) or sl_norm(e['name']) == sl_norm(name):
            return OUT_W.get(e['level'], 0.0), e
    return 0.0, None


def sl_norm(n):
    import unicodedata
    n = unicodedata.normalize('NFKD', str(n or '')).encode('ascii', 'ignore').decode().lower()
    n = re.sub(r'\s+(jr|sr|ii|iii|iv|v)\.?$', '', n.strip())
    return re.sub(r'[^a-z]', '', n)


def availability(team, at):
    """(missing value, available value, [players expected out]) for a team's next game, from the injury list."""
    st_ = ROT.get(team, {}); i = TEAM_IDX.get(team, 0)
    mv = av = 0.0; outs = []
    for pid, s_ in st_.items():
        if i - s_['idx'] > AV['recent_games'] or s_['min'] < AV['min_minutes'] or LAST_TEAM.get(pid) != team:
            continue
        v = (s_['gpm'] - AV['repl']) * s_['min']
        w_, e = out_weight(team, pid, NAMES.get(pid))
        mv += w_ * v; av += (1 - w_) * v
        if e and w_ > 0:
            outs.append({'id': pid, 'name': NAMES.get(pid), 'min': round(s_['min'], 1), 'value': round(v, 1), 'level': e['level'], 'w': w_})
    outs.sort(key=lambda x: -x['value'] * x['w'])
    return mv, av, outs

# ================================================================== predictions: every game (finished ones use who actually played)
B = MM['coef']; BT = TM['coef']; SD = MM['resid_sd']; SDT = TM['resid_sd']


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def predict(g, upcoming):
    f = PRE[g.id]
    if upcoming:
        mh, avh, outs_h = availability(g.home, g.k); ma, ava, outs_a = availability(g.away, g.k)
    else:
        mh, avh = MISS_HIST.get((g.id, g.home), (0.0, 0.0)); ma, ava = MISS_HIST.get((g.id, g.away), (0.0, 0.0)); outs_h = outs_a = []
    hfa = 0 if g.neutral else 1
    b2b_h, b2b_a = int(f['rest_h'] <= 1), int(f['rest_a'] <= 1)
    x = {'rate_m': f['rate_m'], 'hfa': hfa, 'b2b_h': b2b_h, 'b2b_a': b2b_a, 'miss_d': ma - mh, 'av_d': avh - ava}
    margin = B[0] + sum(B[i + 1] * x[c] for i, c in enumerate(MM['features']))
    total = BT[0] + BT[1] * f['rate_t'] + BT[2] * (b2b_h + b2b_a)
    parts = {'ratings': round(B[1] * f['rate_m'], 2), 'home': round(B[0] + B[2] * hfa, 2), 'rest': round(B[3] * b2b_h + B[4] * b2b_a, 2),
             'lineups': round(B[5] * x['miss_d'] + B[6] * x['av_d'], 2)}
    return {'margin': round(margin, 2), 'total': round(total, 1), 'wp_home': round(ncdf(margin / SD), 4), 'parts': parts,
            'rest_h': f['rest_h'], 'rest_a': f['rest_a'], 'b2b_h': bool(b2b_h), 'b2b_a': bool(b2b_a), 'outs_h': outs_h[:4], 'outs_a': outs_a[:4],
            'n_h': f['n_h'], 'n_a': f['n_a']}


PRED = {}
for g in GAMES.itertuples():
    if g.season < SEASON - 1:
        continue
    PRED[g.id] = predict(g, upcoming=g.state != 'post')

# model record this season against the saved lines
REC = {'su': [0, 0], 'ats': [0, 0, 0], 'ats_all': [0, 0, 0], 'ou': [0, 0, 0], 'units': 0.0}
model_log = []
for g in GAMES[(GAMES.season == SEASON) & (GAMES.state == 'post') & GAMES.hs.notna()].itertuples():
    p = PRED.get(g.id); o = LINE.get(g.id) or {}
    if not p:
        continue
    m = g.hs - g.as_
    if m != 0:
        REC['su'][0 if (p['margin'] > 0) == (m > 0) else 1] += 1
    row = {'id': g.id, 'day': g.day, 'a': g.away, 'h': g.home, 'as': int(g.as_), 'hs': int(g.hs), 'margin': p['margin'], 'pick': g.home if p['margin'] > 0 else g.away,
           'su': 'W' if (p['margin'] > 0) == (m > 0) else 'L'}
    if o.get('spread') is not None:
        mkt = -o['spread']; cov = m + o['spread']
        side = 1 if p['margin'] > mkt else -1
        r_ = 'P' if cov == 0 else ('W' if (cov > 0) == (side > 0) else 'L')
        REC['ats_all']['WLP'.index(r_)] += 1
        row.update({'line': o['spread'], 'ats_pick': g.home if side > 0 else g.away, 'gap': round(p['margin'] - mkt, 1), 'ats': r_})
        if abs(p['margin'] - mkt) >= 3:
            REC['ats']['WLP'.index(r_)] += 1
    if o.get('total') is not None:
        tot = g.hs + g.as_
        side = 1 if p['total'] > o['total'] else -1
        r_ = 'P' if tot == o['total'] else ('W' if (tot > o['total']) == (side > 0) else 'L')
        if abs(p['total'] - o['total']) >= 5:
            REC['ou']['WLP'.index(r_)] += 1
        row.update({'tl': o['total'], 'ou_pick': 'O' if side > 0 else 'U', 'ou': r_, 'mt': p['total']})
    model_log.append(row)
sl.log('model this season: SU', REC['su'], 'ATS 3+', REC['ats'], 'ATS all', REC['ats_all'], 'O/U 5+', REC['ou'])

# ================================================================== player projections (the research model, as of now)
PR = S['props']
pl = P[P.played].copy()
grp = pl.groupby('athlete_id', sort=False)
def ew_last(s, hl):
    return s.ewm(halflife=hl, min_periods=1).mean().iloc[-1]
FORM = {}
lg_rate = {}
cur = pl[pl.t > NOW - pd.Timedelta(days=400)]
for pos1, x in cur.groupby('pos1'):
    lg_rate[pos1] = {k: float(x[k].sum() / max(x['min'].sum(), 1)) for k in STATS}
for pid, x in grp:
    if x.t.iloc[-1] < NOW - pd.Timedelta(days=200):
        continue
    n = len(x); m_ewr = ew_last(x['min'], PR['half_life_rate'])
    f = {'n': n, 'min_ew': ew_last(x['min'], PR['half_life_min']), 'min_l10': float(x['min'].tail(10).mean()), 'min_ewr': m_ewr,
         'started': float(x.starter.astype(str).str.lower().isin(['true', '1']).astype(float).ewm(halflife=3, min_periods=1).mean().iloc[-1]),
         'team': x.team_abbreviation.iloc[-1], 'last': x.t.iloc[-1], 'last_day': pd.Timestamp(sl.et_day(x.t.iloc[-1])), 'pos1': x.pos1.iloc[-1]}
    lr = lg_rate.get(f['pos1']) or lg_rate.get('F')
    w = m_ewr * min(n, 30)
    for k in STATS:
        r = ew_last(x[k], PR['half_life_rate']) / max(m_ewr, 1)
        f[k + '_rate'] = (r * w + lr[k] * PR['prior_minutes']) / (w + PR['prior_minutes'])
    FORM[pid] = f
# opponents: what each defense allows per 48, and pace
tg = pl.groupby(['game_id', 'team_abbreviation', 'opponent_team_abbreviation', 't'])[STATS + ['min']].sum().reset_index().sort_values('t')
for k in STATS:
    tg[k + '_pm'] = tg[k] / tg['min'].clip(lower=200) * 240
ALLOW, LGALLOW = {}, {}
for k in STATS:
    LGALLOW[k] = float(tg[k + '_pm'].ewm(halflife=400, min_periods=1).mean().iloc[-1])
    for d_, x in tg.groupby('opponent_team_abbreviation'):
        ALLOW.setdefault(d_, {})[k] = float(x[k + '_pm'].ewm(halflife=15, min_periods=1).mean().iloc[-1])
PACE_LG = float(np.mean([v for v in PACE.values()])) if PACE else 98.0


def project(pid, g, team, opp, line_abs, minutes_scale=1.0):
    f = FORM.get(pid)
    if not f or f['n'] < 3:
        return None
    b2b = int((pd.Timestamp(g.day) - f['last_day']).days <= 1)        # he played yesterday (calendar days, Eastern)
    c = PR['min_coef']
    mp = c[0] + c[1] * f['min_ew'] + c[2] * f['min_l10'] + c[3] * f['started'] + c[4] * f['min_ew'] * line_abs / 10 + c[5] * b2b
    mp = float(np.clip(mp * minutes_scale, 0, 44))
    pace_f = ((PACE.get(team, PACE_LG) + PACE.get(opp, PACE_LG)) / 2) / PACE_LG
    out = {'min': round(mp, 1)}
    for k in STATS:
        a, b = PR['adj'][k]
        opp_f = min(max(ALLOW.get(opp, {}).get(k, LGALLOW[k]) / LGALLOW[k], 0.6), 1.6)
        out[k] = mp * f[k + '_rate'] * opp_f ** a * pace_f ** b
    for c_, parts in COMBO.items():
        out[c_] = sum(out[p] for p in parts)
    return out


QS = np.linspace(0, 1, 201)
DIST = {k: [(b['hi'], np.array(b['q'])) for b in PR['dist'][k]] for k in ALL}


def p_over(k, proj, L):
    """Chance the stat beats line L (L ends in .5) or reaches L when L is a whole number."""
    if proj is None or proj <= 0.05:
        return 0.0 if L > 0 else 1.0
    q = next((q for hi, q in DIST[k] if proj <= hi), DIST[k][-1][1])
    t = (L if L % 1 else L - 0.5) / proj
    return float(1 - np.interp(t, q, QS, left=0, right=1))


def cal(name, p):
    pts = PR['cal'].get(name)
    if not pts or p is None:
        return p
    xs = [0.0] + [a for a, b in pts] + [1.0]; ys = [0.0] + [b for a, b in pts] + [1.0]
    return float(np.interp(p, xs, ys))


def p_dd(pr, need):
    """Double- (need 2) or triple-double (need 3): categories at 10+, treated as independent, then recalibrated."""
    ps = [p_over(k, pr[k], 9.5) for k in ('pts', 'reb', 'ast', 'stl', 'blk')]
    from itertools import product
    tot = 0.0
    for combo in product([0, 1], repeat=5):
        if sum(combo) >= need:
            v = 1.0
            for c_, p_ in zip(combo, ps): v *= p_ if c_ else 1 - p_
            tot += v
    return cal('dd' if need == 2 else 'td3', tot)

# ================================================================== this slate: lines, projections, props, high-chance picks and long shots
SHOW = GAMES[(GAMES.day >= SLATE) & (GAMES.day <= DAYS[-2])]            # today and tomorrow
PROP_GAMES = [g for g in SHOW.itertuples() if g.state == 'pre']
PLINES = dict(zip([g.id for g in PROP_GAMES], sl.parallel(lambda e: sl.prop_lines(LG, e), [g.id for g in PROP_GAMES], 8)))
sl.log('prop lines:', {k: len(v) for k, v in PLINES.items()})
BL = PR['blend']
lgt = lambda p: math.log(p / (1 - p)); sgm = lambda x: 1 / (1 + math.exp(-x))


def blend(k, p_model, p_book):
    if p_book is None:
        return p_model
    w = BL.get(k, 0.0)
    pm = min(max(p_model, 0.02), 0.98); pb = min(max(p_book, 0.02), 0.98)
    return sgm((1 - w) * lgt(pb) + w * lgt(pm))


def dec(o):
    return 1 + (o / 100 if o > 0 else 100 / abs(o))


def book_lines(gid):
    """{athlete: {key: {'main': {...}, 'alts': {...}, 'yes': {...}}}} from the raw prop lines."""
    out = {}
    pairs = {}
    for x in PLINES.get(gid) or []:
        k = x['key']
        if x['side'] in ('over', 'under') and k in ALL:
            pairs.setdefault((x['athlete'], k, x['line']), {})[x['side']] = x
        elif x['side'] == 'yes':
            out.setdefault(x['athlete'], {}).setdefault('yes', {})[(k, x['line'])] = x
    for (aid, k, L), sides in pairs.items():
        if 'over' not in sides or 'under' not in sides or sides['over']['odds'] is None or sides['under']['odds'] is None:
            continue
        pb = sl.novig(sides['over']['odds'], sides['under']['odds'])
        cur = out.setdefault(aid, {}).get(k)
        cand = {'line': L, 'o': sides['over']['odds'], 'u': sides['under']['odds'], 'p_book': pb, 'open': sides['over'].get('line_open'), 'book': sides['over']['book']}
        if cur is None or abs(pb - 0.5) < abs(cur['p_book'] - 0.5):
            out[aid][k] = cand
    return out


def last_n(pid, k, n=10):
    x = pl[pl.athlete_id == pid].tail(n)
    if k in COMBO:
        return (x[COMBO[k]].sum(axis=1)).tolist()
    return x[k].tolist()


PROPS, HC, LS = [], [], []
GAME_PROPS = {}
for g in SHOW.itertuples():
    o = LINE.get(g.id) or {}
    pred = PRED.get(g.id) or {}
    lines = book_lines(g.id) if g.state == 'pre' else {}
    for team, opp, side in ((g.home, g.away, 'h'), (g.away, g.home, 'a')):
        tl = None if o.get('spread') is None else (o['spread'] if side == 'h' else -o['spread'])
        st_ = ROT.get(team, {}); i = TEAM_IDX.get(team, 0)
        cands = {pid for pid, s_ in st_.items() if i - s_['idx'] <= AV['recent_games'] and s_['min'] >= 8 and LAST_TEAM.get(pid) == team}
        cands |= {aid for aid in lines if LAST_TEAM.get(aid) == team}
        rows = []
        for pid in cands:
            w_out, e = out_weight(team, pid, NAMES.get(pid))
            pr = project(pid, g, team, opp, abs(tl) if tl is not None else 6.0)
            if not pr:
                continue
            rows.append([pid, pr, w_out, e])
        # minutes freed by players who sit go to the rest of the rotation (at most 15% more each, 42 minutes max)
        tot_avail = sum(r[1]['min'] * (1 - r[2]) for r in rows); freed = sum(r[1]['min'] * r[2] for r in rows)
        scale = min(1.15, (tot_avail + freed * 0.8) / tot_avail) if tot_avail > 0 and freed > 2 else 1.0
        for pid, pr, w_out, e in rows:
            if scale != 1.0 and w_out < 0.5:
                pr = project(pid, g, team, opp, abs(tl) if tl is not None else 6.0, minutes_scale=scale)
            if pr['min'] < 10 and pid not in lines:
                continue
            lns = lines.get(pid, {})
            item = {'id': pid, 'name': NAMES.get(pid), 'team': team, 'opp': opp, 'game': g.id, 'home': side == 'h', 'pos': POS.get(pid, ''),
                    'min': pr['min'], 'proj': {k: round(pr[k], 2) for k in ALL},
                    'avg': {k: round(float(np.mean(v)), 1) for k in ('pts', 'reb', 'ast', 'fg3m', 'pra') for v in [last_n(pid, k)] if v},
                    'inj': {'level': e['level'], 'status': e['status'], 'detail': e['injury']} if e else None, 'lines': {}}
            for k, ln in lns.items():
                if k not in ALL or not isinstance(ln, dict):
                    continue
                pm = p_over(k, pr[k], ln['line']); pb = ln['p_book']; p = blend(k, pm, pb)
                item['lines'][k] = {'line': ln['line'], 'o': ln['o'], 'u': ln['u'], 'open': ln['open'], 'p_book': round(pb, 4), 'p_model': round(pm, 4), 'p': round(p, 4),
                                    'ev_o': round(p * dec(ln['o']) - 1, 4), 'ev_u': round((1 - p) * dec(ln['u']) - 1, 4), 'book': ln['book']}
            if g.state == 'pre' and w_out < 0.5:
                PROPS.append(item)
            GAME_PROPS.setdefault(g.id, []).append(item)
            if g.state != 'pre' or w_out >= 0.3 or pr['min'] < 16:
                continue
            # ---- high-chance: the biggest round number he reaches 80%+ of the time
            yes = lns.get('yes', {})
            for k in ('pts', 'reb', 'ast', 'fg3m', 'pra', 'pr', 'pa'):
                best = None
                for t in range(1, 80):
                    pt = p_over(k, pr[k], t)
                    if pt < 0.80:
                        break
                    if pt <= 0.97:
                        best = (t, pt)
                MIN_T = {'pts': 10, 'pra': 15, 'pr': 12, 'pa': 12, 'reb': 4, 'ast': 3, 'fg3m': 2}
                if not best or best[0] < MIN_T[k] or best[0] < 0.6 * pr[k]:
                    continue
                t, pt = best
                ln = last_n(pid, k); hits = sum(1 for v in ln if v >= t)
                bo = yes.get((k + '+', float(t)))
                HC.append({'kind': 'player', 'id': pid, 'name': NAMES.get(pid), 'team': team, 'opp': opp, 'game': g.id, 'k': g.k.isoformat(), 'key': k, 't': t,
                           'p': round(pt, 4), 'fair': sl.odds_of(pt), 'proj': round(pr[k], 1), 'min': pr['min'], 'avg': round(float(np.mean(ln)), 1) if ln else None,
                           'hits': [hits, len(ln)], 'book': bo['odds'] if bo else None, 'label': f"{NAMES.get(pid)} {t}+ {SHORT[k]}",
                           'reason': f"{NAMES.get(pid).split(' ')[-1]} has reached {t}+ {SHORT[k]} in {hits} of his last {len(ln)} games, averaging {np.mean(ln):.1f}. "
                                     f"Projected for {pr[k]:.1f} in about {pr['min']:.0f} minutes against {opp}."})
            # ---- long shots: big games with a real chance
            for k, ts in (('pts', [25, 30, 35, 40, 45, 50]), ('reb', [10, 12, 15, 18]), ('ast', [8, 10, 12, 15]), ('fg3m', [4, 5, 6, 7]), ('pra', [40, 45, 50, 55])):
                for t in ts:
                    pt = cal(k + '_hi', p_over(k, pr[k], t))
                    if 0.05 <= pt <= 0.33 and t >= pr[k] * 1.25:
                        ln = last_n(pid, k, 20); hits = sum(1 for v in ln if v >= t)
                        bo = yes.get((k + '+', float(t)))
                        LS.append({'type': k + '+', 'key': k, 't': t, 'id': pid, 'name': NAMES.get(pid), 'team': team, 'opp': opp, 'game': g.id, 'k': g.k.isoformat(),
                                   'p': round(pt, 4), 'fair': sl.odds_of(pt), 'book': bo['odds'] if bo else None, 'proj': round(pr[k], 1), 'hits': [hits, len(ln)],
                                   'label': f"{NAMES.get(pid)} {t}+ {SHORT[k]}", 'group': k,
                                   'reason': f"Projected {pr[k]:.1f} {SHORT[k]}; reached {t}+ in {hits} of his last {len(ln)} games."})
                        break
            for need, nm, key in ((2, 'double-double', 'dd'), (3, 'triple-double', 'td3')):
                pt = p_dd(pr, need)
                if (key == 'dd' and 0.12 <= pt <= 0.40) or (key == 'td3' and 0.04 <= pt <= 0.40):
                    x = pl[pl.athlete_id == pid].tail(20)
                    cnt = ((x[['pts', 'reb', 'ast', 'stl', 'blk']] >= 10).sum(axis=1) >= need).sum()
                    bo = yes.get((key, None)) or next((v for (kk, _), v in yes.items() if kk == key), None)
                    LS.append({'type': key, 'key': key, 't': None, 'id': pid, 'name': NAMES.get(pid), 'team': team, 'opp': opp, 'game': g.id, 'k': g.k.isoformat(),
                               'p': round(pt, 4), 'fair': sl.odds_of(pt), 'book': bo['odds'] if bo else None, 'proj': None, 'hits': [int(cnt), len(x)],
                               'label': f"{NAMES.get(pid)} {nm}", 'group': key,
                               'reason': f"{int(cnt)} {nm}s in his last {len(x)} games. Projected {pr['pts']:.0f} pts, {pr['reb']:.0f} reb, {pr['ast']:.0f} ast."})
# team-level high-chance: the model's strongest moneyline favorites
for g in SHOW.itertuples():
    p = PRED.get(g.id); o = LINE.get(g.id) or {}
    if g.state != 'pre' or not p:
        continue
    for team, wp, ml in ((g.home, p['wp_home'], o.get('ml_h')), (g.away, 1 - p['wp_home'], o.get('ml_a'))):
        mk = sl.implied(ml) if ml else None
        if wp >= 0.80 and (mk is None or mk >= 0.70):
            HC.append({'kind': 'ml', 'team': team, 'opp': g.away if team == g.home else g.home, 'game': g.id, 'k': g.k.isoformat(), 'p': round(wp, 4), 'fair': sl.odds_of(wp),
                       'book': ml, 'mkt_p': round(mk, 4) if mk else None, 'label': f"{team} to win",
                       'reason': f"The model makes {team} {wp * 100:.0f}% to win{f', the market {mk * 100:.0f}%' if mk else ''}. Favorites this big lose about one game in {max(2, round(1 / (1 - wp)))}."})
HC.sort(key=lambda x: -x['p']); LS.sort(key=lambda x: -x['p'])
# keep the list readable: two per player at most
seen = {}
HC = [x for x in HC if x.get('kind') != 'player' or (seen.setdefault(x['id'], 0) < 2 and not seen.__setitem__(x['id'], seen[x['id']] + 1))][:40]
seen = {}
LS = [x for x in LS if seen.setdefault(x['id'], 0) < 2 and not seen.__setitem__(x['id'], seen[x['id']] + 1)][:60]
sl.log('props', len(PROPS), 'with book lines', sum(1 for x in PROPS if x['lines']), '| high-chance', len(HC), '| long shots', len(LS))

# ================================================================== team records, against the spread and totals (saved lines), streaks
def team_records():
    out = {}
    cur = GAMES[(GAMES.season == SEASON) & (GAMES.state == 'post') & GAMES.hs.notna()]
    for t in TEAMS:
        x = cur[(cur.home == t) | (cur.away == t)].sort_values('k')
        res, ats_, ou_, margins = [], [], [], []
        for g in x.itertuples():
            home = g.home == t; m = (g.hs - g.as_) * (1 if home else -1); margins.append(m)
            res.append('W' if m > 0 else 'L')
            o = LINE.get(g.id) or {}
            if o.get('spread') is not None:
                ln = o['spread'] if home else -o['spread']; c = m + ln
                ats_.append('P' if c == 0 else 'W' if c > 0 else 'L')
            if o.get('total') is not None:
                tot = g.hs + g.as_
                ou_.append('P' if tot == o['total'] else 'O' if tot > o['total'] else 'U')
        def rec(lst, a='W', b='L'):
            return {a: lst.count(a), b: lst.count(b), 'P': lst.count('P')}
        streak = ''
        if res:
            n = 1
            while n < len(res) and res[-n - 1] == res[-1]:
                n += 1
            streak = res[-1] + str(n)
        home_r = [r for r, g in zip(res, x.itertuples()) if g.home == t]; away_r = [r for r, g in zip(res, x.itertuples()) if g.away == t]
        out[t] = {'rec': rec(res), 'l10': rec(res[-10:]), 'home': rec(home_r), 'away': rec(away_r), 'ats': rec(ats_), 'ou': rec(ou_, 'O', 'U'),
                  'last': res[-5:], 'ats_last': ats_[-5:], 'ou_last': ou_[-5:], 'streak': streak, 'pd': round(float(np.mean(margins)), 1) if margins else None, 'gp': len(res)}
    return out


TREC = team_records()
rk = lambda key, rev=True: {t: i + 1 for i, (t, v) in enumerate(sorted(RATING.items(), key=lambda kv: -kv[1][key] if rev else kv[1][key]))}
RK_NET, RK_OFF, RK_DEF, RK_PACE = rk('net'), rk('off'), rk('def'), rk('pace')
TEAMS_OUT = {}
for t, v in TEAMS.items():
    TEAMS_OUT[t] = dict(v, **TREC.get(t, {}), rating=RATING.get(t), rk={'net': RK_NET.get(t), 'off': RK_OFF.get(t), 'def': RK_DEF.get(t), 'pace': RK_PACE.get(t)},
                        inj=len([e for e in INJ.get(t, []) if e['level'] in ('out', 'doubt')]))

# ================================================================== trends: players on runs, teams on runs (with what the research says about carrying over)
TRENDS_P, TRENDS_T = [], []
for it in PROPS:
    pid = it['id']; x = pl[pl.athlete_id == pid].tail(12)
    if len(x) < 5:
        continue
    for k in ('pts', 'reb', 'ast', 'fg3m', 'pra'):
        vals = (x[COMBO[k]].sum(axis=1) if k in COMBO else x[k]).tolist()
        ln = it['lines'].get(k, {}).get('line')
        if ln is None and it['proj'][k] < {'pts': 8, 'reb': 3, 'ast': 2, 'fg3m': 1.5, 'pra': 12}[k]:
            continue
        base = ln if ln is not None else math.floor(it['proj'][k]) + 0.5
        n = 0
        for v in reversed(vals):
            if v > base: n += 1
            else: break
        m = 0
        for v in reversed(vals):
            if v < base: m += 1
            else: break
        if max(n, m) >= 4:
            TRENDS_P.append({'id': pid, 'name': it['name'], 'team': it['team'], 'opp': it['opp'], 'game': it['game'], 'key': k, 'line': base, 'book': ln is not None,
                             'dir': 'over' if n else 'under', 'n': max(n, m), 'vals': vals[-8:], 'proj': it['proj'][k],
                             'p': it['lines'].get(k, {}).get('p')})
TRENDS_P.sort(key=lambda x: (-x['n'], -x['proj']))
for t, v in TREC.items():
    res_all = GAMES[(GAMES.season == SEASON) & (GAMES.state == 'post') & ((GAMES.home == t) | (GAMES.away == t))].sort_values('k')
    def run(seq, a):
        n = 0
        for s_ in reversed(seq):
            if s_ == a: n += 1
            else: break
        return n
    full = TREC[t]
    ats_seq = []; ou_seq = []; su_seq = []
    for g in res_all.itertuples():
        home = g.home == t; m = (g.hs - g.as_) * (1 if home else -1); su_seq.append('W' if m > 0 else 'L')
        o = LINE.get(g.id) or {}
        if o.get('spread') is not None:
            c = m + (o['spread'] if home else -o['spread']); ats_seq.append('P' if c == 0 else 'W' if c > 0 else 'L')
        if o.get('total') is not None:
            tot = g.hs + g.as_; ou_seq.append('P' if tot == o['total'] else 'O' if tot > o['total'] else 'U')
    for seq, a, what in ((su_seq, 'W', 'won'), (su_seq, 'L', 'lost'), (ats_seq, 'W', 'covered'), (ats_seq, 'L', 'failed to cover'), (ou_seq, 'O', 'gone over'), (ou_seq, 'U', 'gone under')):
        n = run(seq, a)
        if n >= 3:
            TRENDS_T.append({'team': t, 'what': what, 'n': n, 'kind': 'su' if seq is su_seq else 'ats' if seq is ats_seq else 'ou', 'seq': seq[-10:]})
TRENDS_T.sort(key=lambda x: -x['n'])

# ================================================================== chart logs: recent games for every player on the slate, and every team
PCOLS = ['day', 'opp', 'home', 'min', 'pts', 'reb', 'ast', 'fg3m', 'stl', 'blk', 'tov', 'start']
PLOGS = {}
ids = {x['id'] for x in PROPS} | {x['id'] for x in HC if x.get('kind') == 'player'} | {x['id'] for x in LS} | {x['id'] for x in TRENDS_P}
for pid in ids:
    x = pl[pl.athlete_id == pid].tail(25)
    PLOGS[pid] = {'n': NAMES.get(pid), 't': LAST_TEAM.get(pid), 'p': POS.get(pid, ''),
                  'rows': [[sl.et_day(r.t), r.opponent_team_abbreviation, 1 if str(r.home_away) == 'home' else 0, round(float(r.min), 1), int(r.pts), int(r.reb), int(r.ast), int(r.fg3m),
                            int(r.stl), int(r.blk), int(r.tov), 1 if str(r.starter).lower() in ('true', '1') else 0] for r in x.itertuples()]}
TCOLS = ['day', 'opp', 'home', 'pf', 'pa', 'line', 'total']
TLOGS = {}
for t in TEAMS:
    x = GAMES[((GAMES.home == t) | (GAMES.away == t)) & (GAMES.state == 'post') & GAMES.hs.notna()].sort_values('k').tail(30)
    rows = []
    for g in x.itertuples():
        home = g.home == t; o = LINE.get(g.id) or {}
        rows.append([g.day, g.away if home else g.home, 1 if home else 0, int(g.hs if home else g.as_), int(g.as_ if home else g.hs),
                     None if o.get('spread') is None else (o['spread'] if home else -o['spread']), o.get('total')])
    TLOGS[t] = rows

# ================================================================== output
def odds_out(o):
    if not o:
        return None
    return {k: o.get(k) for k in ('spread', 'total', 'ml_h', 'ml_a', 'sp_h', 'sp_a', 'o', 'u', 'spread_open', 'total_open', 'ml_h_open', 'ml_a_open', 'book')}


games_out = []
for g in GAMES[(GAMES.day >= DAYS[1]) & (GAMES.day <= DAYS[-1])].itertuples():
    p = PRED.get(g.id); o = LINE.get(g.id) if g.state == 'post' else (got.get(g.id) or LINE.get(g.id))
    m = None
    if p:
        mkt = -o['spread'] if o and o.get('spread') is not None else None
        edge = round(p['margin'] - mkt, 1) if mkt is not None else None
        tedge = round(p['total'] - o['total'], 1) if o and o.get('total') is not None else None
        m = {'margin': p['margin'], 'total': p['total'], 'wp_home': p['wp_home'], 'pick_su': g.home if p['margin'] > 0 else g.away, 'edge': edge, 'total_edge': tedge,
             'pick_ats': (g.home if edge > 0 else g.away) if edge is not None and abs(edge) >= 3 else None,
             'pick_total': ('O' if tedge > 0 else 'U') if tedge is not None and abs(tedge) >= 5 else None,
             'mkt_wp_home': round(sl.novig(o['ml_h'], o['ml_a']), 4) if o and o.get('ml_h') and o.get('ml_a') else None, 'parts': p['parts']}
    games_out.append({'id': g.id, 'day': g.day, 'k': g.k.isoformat(), 'away': g.away, 'home': g.home, 'state': g.state, 'detail': g.detail if isinstance(g.detail, str) else '',
                      'as': None if g.as_ != g.as_ or g.as_ is None else int(g.as_), 'hs': None if g.hs != g.hs or g.hs is None else int(g.hs),
                      'neutral': bool(g.neutral), 'venue': g.venue if isinstance(g.venue, str) else '', 'odds': odds_out(o), 'model': m,
                      'rest': {'h': p['rest_h'], 'a': p['rest_a'], 'b2b_h': p['b2b_h'], 'b2b_a': p['b2b_a']} if p else None,
                      'outs': {'h': p['outs_h'], 'a': p['outs_a']} if p else None,
                      'rec': {'h': getattr(g, 'home_rec', None) if isinstance(getattr(g, 'home_rec', None), dict) else None,
                              'a': getattr(g, 'away_rec', None) if isinstance(getattr(g, 'away_rec', None), dict) else None}})
# injuries, with whether each player is in the rotation
inj_out = {}
for t, lst in INJ.items():
    st_ = ROT.get(t, {}); i = TEAM_IDX.get(t, 0)
    rows = []
    for e in lst:
        pid = e['id'] if e['id'] in st_ else next((p_ for p_ in st_ if sl_norm(NAMES.get(p_)) == sl_norm(e['name'])), None)
        s_ = st_.get(pid) if pid else None
        mins = round(s_['min'], 1) if s_ and i - s_['idx'] <= 25 else None
        rows.append(dict(e, pid=pid, min=mins, key=bool(mins and mins >= 20)))
    order = {'out': 0, 'doubt': 1, 'gtd': 2, 'likely': 3}
    rows.sort(key=lambda r: (not r['key'], order.get(r['level'], 9), -(r['min'] or 0)))
    inj_out[t] = rows
# grading: recent finals and box-score lines for the shared bet slip
cut = NOW - pd.Timedelta(days=21)
gg = {}
for g in GAMES[(GAMES.k >= cut) & (GAMES.day <= DAYS[-1])].itertuples():
    o = LINE.get(g.id) or {}
    gg[g.id] = {'a': g.away, 'h': g.home, 'k': g.k.isoformat(), 'd': g.day, 'hs': None if g.state != 'post' or g.hs != g.hs else int(g.hs),
                'as': None if g.state != 'post' or g.as_ != g.as_ else int(g.as_), 'sp': None if o.get('spread') is None else -o['spread'], 'tl': o.get('total'),
                'mlh': o.get('ml_h'), 'mla': o.get('ml_a')}
box_games = set(P[P.played].game_id)
for gid in gg:
    if gid in box_games and gg[gid]['hs'] is not None:
        gg[gid]['b'] = 1
gp = {}
for r in P[P.played & P.game_id.isin(gg.keys())].itertuples():
    e = gp.setdefault(r.athlete_id, {'n': r.athlete_display_name, 't': r.team_abbreviation, 'p': POS.get(r.athlete_id, ''), 'g': {}})
    e['g'][r.game_id] = [round(float(r.min)), int(r.pts), int(r.reb), int(r.ast), int(r.fg3m), int(r.stl), int(r.blk), int(r.tov)]
GRADE = {'sport': LG, 'asof': NOW.isoformat(timespec='seconds'), 'games': gg, 'players': gp}
# the client recomputes chances when a line is typed: compact outcome tables
dist_out = {k: [[round(b['hi'], 3), [round(v, 3) for v in np.array(b['q'])[::5].tolist()]] for b in PR['dist'][k]] for k in ALL}
season_label = f'{SEASON - 1}-{str(SEASON)[-2:]}'
BT_ = S['backtest']; PBT = S['prop_backtest']
meta = {'sport': LG, 'season': season_label, 'asof': NOW.isoformat(timespec='seconds'), 'slate': SLATE, 'days': DAYS[1:], 'espn': 'basketball/nba',
        'stats_through': (P[P.played].t.max().tz_convert(sl.ET).date().isoformat() if len(P) else None), 'resid_sd': SD, 'resid_t': SDT,
        'sources': ['hoopR box scores and schedules (sportsdataverse), refreshed daily', 'ESPN scoreboard, game summaries and injury list',
                    'ESPN odds records: game lines and player props (DraftKings, ESPN BET when DraftKings has none)'],
        'injuries_ok': bool(INJ_RAW), 'odds_ok': any(v for v in got.values()), 'props_ok': any(PLINES.values())}
data = {'meta': meta, 'teams': TEAMS_OUT, 'games': games_out, 'injuries': inj_out, 'props': PROPS, 'high_chance': HC, 'long_shots': LS,
        'trends': {'player': TRENDS_P[:60], 'team': TRENDS_T[:40]},
        'model': {'record': REC, 'log': model_log[-400:], 'backtest': BT_, 'coef': MM['coef'], 'features': MM['features']},
        'research': {'props': PBT, 'situational': S['situational'], 'carry': S['carry'], 'blend': BL},
        'dist': dist_out}
sl.write_json(os.path.join(OUT, 'data.json'), data)
sl.write_json(os.path.join(OUT, 'logs.json'), {'pcols': PCOLS, 'players': PLOGS, 'tcols': TCOLS, 'teams': TLOGS})
sl.write_json(os.path.join(OUT, 'grade.json'), GRADE)
# keep the line log to the current and last season
keep = set(GAMES[GAMES.season >= SEASON - 1].id)
sl.write_json(os.path.join(OUT, 'odds_log.json'), {k: v for k, v in OLOG.items() if k in keep})
# the home page card
today = [g for g in games_out if g['day'] == SLATE] or [g for g in games_out if g['day'] > SLATE][:15]
def fav(g):
    o = g['odds'] or {}
    if o.get('spread') is None: return None
    if o['spread'] == 0: return 'PK'
    return f"{g['home'] if o['spread'] < 0 else g['away']} {-abs(o['spread']):+g}".replace('+', '')
picks = []
hc_ = [x for x in HC if x.get('kind') == 'player']
if hc_: picks.append({'tag': 'hc', 't': hc_[0]['label'], 's': f"{hc_[0]['team']} vs {hc_[0]['opp']}", 'v': f"{round(hc_[0]['p'] * 100)}%", 'view': 'hc'})
if LS: picks.append({'tag': 'ls', 't': LS[0]['label'], 's': f"{LS[0]['team']} vs {LS[0]['opp']} · fair {sl.odds_of(LS[0]['p']):+d}", 'v': f"{round(LS[0]['p'] * 100)}%", 'view': 'ls'})
mg = [g for g in games_out if g['state'] == 'pre' and g['model']]
if mg:
    g = max(mg, key=lambda g: abs(g['model']['wp_home'] - 0.5)); t_ = g['model']['pick_su']; wp_ = g['model']['wp_home'] if t_ == g['home'] else 1 - g['model']['wp_home']
    picks.append({'tag': 'md', 't': f"{t_} to win", 's': f"{g['away']} @ {g['home']}", 'v': f"{round(wp_ * 100)}%", 'view': 'model'})
nxt = next((g for g in games_out if g['state'] == 'pre'), None)
summ = {'sport': LG, 'asof': meta['asof'], 'season': season_label, 'period': 'Today' if today and today[0]['day'] == SLATE else 'Next games', 'espn': 'basketball/nba',
        'games': [{'id': g['id'], 'eid': g['id'], 'a': g['away'], 'h': g['home'], 'k': g['k'], 'st': g['state'], 'as': g['as'], 'hs': g['hs'], 'det': g['detail'],
                   'line': fav(g), 'pick': (g['model'] or {}).get('pick_su')} for g in today],
        'next': {'k': nxt['k'], 'a': nxt['away'], 'h': nxt['home']} if nxt else None, 'picks': picks,
        'record': f"Model {REC['su'][0]}-{REC['su'][1]} picking winners this season" if sum(REC['su']) else None,
        'links': [['games', 'Games'], ['props', 'Props'], ['hc', 'High-chance'], ['ls', 'Long shots'], ['trends', 'Trends']]}
if not today:
    summ['note'] = 'No games on the schedule in the next few days.'
sl.write_json(os.path.join(OUT, 'summary.json'), summ)
