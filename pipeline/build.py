"""Rebuild site/data/data.json from the latest public data.

Runs on a schedule in GitHub Actions. Pulls the current season from nflverse (play-by-play, player stats, schedules
and lines, official injury reports, snap counts, Next Gen Stats) plus ESPN's injury and scoreboard feeds, then
computes records, ratings, model lines, stat ranks, injury outlooks, prop projections, 2+ week trends and the
model's pick record. The research behind the model (2017-2025) ships in static/ and does not need to be rerun.

    python pipeline/build.py            # writes site/data/data.json
"""
import os, sys, json, re, math, time, gzip, shutil, datetime as dt, urllib.request, urllib.error
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.environ.get('NFL_RAW', os.path.join(HERE, '.cache'))
os.environ['NFL_RAW'] = RAW
os.makedirs(RAW, exist_ok=True)
sys.path.insert(0, HERE)
from teams import TEAMS, INTERNATIONAL          # noqa: E402
import pbp_agg, metrics, players as pa, espn    # noqa: E402

OUT = os.path.join(ROOT, 'site', 'data', 'data.json')
BASE = 'https://github.com/nflverse/nflverse-data/releases/download'
NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.date()
SEASON = int(os.environ.get('NFL_SEASON', TODAY.year if TODAY.month >= 3 else TODAY.year - 1))


# ------------------------------------------------------------------ helpers
def fetch(url, dest, required=True, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'nfl-edge-refresh'})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest + '.part', 'wb') as f:
                shutil.copyfileobj(r, f)
            os.replace(dest + '.part', dest)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            time.sleep(3 * (i + 1))
        except Exception:
            time.sleep(3 * (i + 1))
    if required:
        raise SystemExit(f'Could not download {url}')
    print('missing (ok):', url)
    return False


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 4)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def am_prob(ml):
    if ml is None or not np.isfinite(ml):
        return None
    return -ml / (-ml + 100) if ml < 0 else 100 / (ml + 100)


def norm(n):
    return re.sub(r'[^a-z]', '', str(n).lower().replace(' jr.', '').replace(' sr.', '').replace(' iii', '').replace(' ii', ''))


def run_len(flags):
    n = 0
    for f in reversed(flags):
        if f:
            n += 1
        else:
            break
    return n


# ------------------------------------------------------------------ downloads
print('Season', SEASON)
fetch(f'{BASE}/schedules/games.csv', f'{RAW}/games.csv')
have_pbp = {y: fetch(f'{BASE}/pbp/play_by_play_{y}.csv.gz', f'{RAW}/pbp_{y}.csv.gz', required=(y == SEASON - 1)) for y in (SEASON - 2, SEASON - 1, SEASON)}
have_ps = {y: fetch(f'{BASE}/stats_player/stats_player_week_{y}.csv', f'{RAW}/stats_player_week_{y}.csv', required=(y < SEASON)) for y in (SEASON - 1, SEASON)}
have_inj = fetch(f'{BASE}/injuries/injuries_{SEASON}.csv', f'{RAW}/injuries_{SEASON}.csv', required=False)
have_rost = fetch(f'{BASE}/weekly_rosters/roster_weekly_{SEASON}.csv', f'{RAW}/roster_weekly_{SEASON}.csv', required=False)
have_snap = fetch(f'{BASE}/snap_counts/snap_counts_{SEASON}.csv', f'{RAW}/snap_counts_{SEASON}.csv', required=False)
for t in ('passing', 'receiving', 'rushing'):
    fetch(f'{BASE}/nextgen_stats/ngs_{t}.csv.gz', f'{RAW}/ngs_{t}.csv.gz', required=False)

R = json.load(open(os.path.join(HERE, 'static', 'team_research.json')))
PR = json.load(open(os.path.join(HERE, 'static', 'player_research.json')))
TR = json.load(open(os.path.join(HERE, 'static', 'trend_research.json')))
BINS = json.load(open(os.path.join(HERE, 'static', 'prop_bins.json')))
STYLE_BASE = json.load(open(os.path.join(HERE, 'static', 'league_style_baseline.json')))
M2 = json.load(open(os.path.join(HERE, 'static', 'model_v2.json')))
SR = json.load(open(os.path.join(HERE, 'static', 'spread_research.json')))
params = R['params']

# ------------------------------------------------------------------ team games and metrics
tgs, rzs = [], []
for y in (SEASON - 1, SEASON):
    if have_pbp.get(y):
        tg_y, rz_y = pbp_agg.season_frames(y, f'{RAW}/pbp_{y}.csv.gz')
        tgs.append(tg_y); rzs.append(rz_y)
tg_all = pd.concat(tgs, ignore_index=True)
qb_g = pd.concat([pbp_agg.qb_frames(y, f'{RAW}/pbp_{y}.csv.gz') for y in (SEASON - 2, SEASON - 1, SEASON) if have_pbp.get(y)], ignore_index=True)
rz_all = pd.concat(rzs, ignore_index=True)
m_all = metrics.add_pregame(metrics.team_metric_frame(tg_all), params)
m26 = m_all[m_all.season == SEASON].copy()

# ------------------------------------------------------------------ schedule + live scoreboard
sched = pd.read_csv(f'{RAW}/games.csv', low_memory=False)
S = sched[sched.season == SEASON].copy()
if S.empty:
    raise SystemExit(f'No {SEASON} schedule yet; keeping the existing data.')
board = espn.scoreboard()
live = {}
for idx, g in S.iterrows():
    b = board.get((g.away_team, g.home_team))
    if not b:
        continue
    if pd.isna(g.home_score) and b['completed'] and b['home_score'] is not None:
        S.at[idx, 'home_score'] = b['home_score']; S.at[idx, 'away_score'] = b['away_score']
        S.at[idx, 'result'] = b['home_score'] - b['away_score']
    if b['state'] == 'in':
        live[g.game_id] = {'detail': b['detail'], 'home_score': b['home_score'], 'away_score': b['away_score']}
    if pd.isna(g.spread_line) and b.get('odds_detail'):
        mm_ = re.match(r'([A-Z]{2,3})\s+(-?\d+(?:\.\d+)?)', str(b['odds_detail']))
        if mm_:
            fav = espn.ESPN_ABBR.get(mm_.group(1), mm_.group(1)); pts = abs(float(mm_.group(2)))
            S.at[idx, 'spread_line'] = pts if fav == g.home_team else -pts
        elif 'EVEN' in str(b['odds_detail']).upper():
            S.at[idx, 'spread_line'] = 0.0
    if pd.isna(g.total_line) and b.get('over_under') is not None:
        S.at[idx, 'total_line'] = float(b['over_under'])
S['final'] = S.home_score.notna()
S['neutral'] = S.stadium.fillna('').apply(lambda s: any(k in s for k in INTERNATIONAL)) | (S.location == 'Neutral')
open_weeks = S[~S.final].week
WEEK = int(open_weeks.min()) if len(open_weeks) else int(S.week.max())
wk_games = S[S.week == WEEK].copy()
print('Week', WEEK, 'games', len(wk_games), 'final', int(wk_games.final.sum()), 'live', len(live))

# ------------------------------------------------------------------ records and game logs
done = S[S.final].copy()
rows = []
for _, g in done.iterrows():
    for side in ('home', 'away'):
        t = g[f'{side}_team']; o = g['away_team' if side == 'home' else 'home_team']
        pf = g[f'{side}_score']; pa_ = g['away_score' if side == 'home' else 'home_score']
        sp = g.spread_line if pd.notna(g.spread_line) else 0.0
        tl = g.total_line if pd.notna(g.total_line) else np.nan
        exp = sp if side == 'home' else -sp
        rows.append({'team': t, 'opp': o, 'week': int(g.week), 'home': side == 'home', 'pf': int(pf), 'pa': int(pa_),
                     'res': 'W' if pf > pa_ else ('L' if pf < pa_ else 'T'),
                     'ats': 'W' if (pf - pa_) - exp > 0 else ('L' if (pf - pa_) - exp < 0 else 'P'),
                     'ou': '' if np.isnan(tl) else ('O' if (pf + pa_) > tl else ('U' if (pf + pa_) < tl else 'P')),
                     'line': float(-exp), 'total': None if np.isnan(tl) else float(tl), 'game_id': g.game_id})
LOG_COLS = ['team', 'opp', 'week', 'home', 'pf', 'pa', 'res', 'ats', 'ou', 'line', 'total', 'game_id']
logs = pd.DataFrame(rows, columns=LOG_COLS).sort_values(['team', 'week'])


def wlt(lst, keys=('W', 'L', 'T')):
    return {k: int(sum(1 for x in lst if x == k)) for k in keys}


teams = {}
for t, (city, nick, div, c1, c2) in TEAMS.items():
    lg = logs[logs.team == t]
    res = lg.res.tolist(); ats = lg.ats.tolist(); ou = [x for x in lg.ou.tolist() if x]
    streak = ''
    if res:
        last = res[-1]; n = run_len([x == last for x in res]); streak = f'{last}{n}'
    teams[t] = {'abbr': t, 'city': city, 'nick': nick, 'div': div, 'c1': c1, 'c2': c2,
                'rec': wlt(res), 'l4': wlt(res[-4:]), 'l4_list': res[-4:], 'ats': wlt(ats, ('W', 'L', 'P')),
                'ou': wlt(ou, ('O', 'U', 'P')), 'pf': int(lg.pf.sum()), 'pa': int(lg.pa.sum()), 'gp': int(len(lg)),
                'streak': streak, 'log': lg[['week', 'opp', 'home', 'pf', 'pa', 'res', 'ats', 'ou', 'line', 'total']].to_dict('records')}

# ------------------------------------------------------------------ ratings and model
POST = metrics.post_ratings(m_all, params, SEASON, list(TEAMS))
FEATS = R['margin_features']; MU = R['feat_mu']; SD = R['feat_sd']
beta = np.array(R['margin_beta']); coef, const = beta[:-1], beta[-1]
RESID = R['margin_resid_sd']; TBETA = np.array(R['total_beta'])


TZ = M2['tz']; QBP = M2['qb']; M2F = M2['features']; M2B = np.array(M2['beta']); M2I = M2['intercept']; RESID = M2['resid_sd']


def situation(g):
    hr = g.home_rest if pd.notna(g.home_rest) else 7; ar = g.away_rest if pd.notna(g.away_rest) else 7
    th, ta = TZ.get(g.home_team, -5), TZ.get(g.away_team, -5)
    return {'rest_diff': float(np.clip(hr - ar, -7, 7)), 'bye_diff': int(hr >= 13) - int(ar >= 13),
            'short_diff': int(hr <= 5) - int(ar <= 5), 'tz_diff': th - ta,
            'west_early': 1 if (ta <= -7 and th == -4 and str(g.gametime).startswith('13')) else 0,
            'altitude': 1 if g.home_team == 'DEN' else 0, 'neutral_i': 1 if bool(g.neutral) else 0}


def model_margin(h, a, neutral=False, src=None, g=None, qb_h=None, qb_a=None):
    src = src or POST
    x = {f: src[f][h] - src[f][a] for f in FEATS}
    x['qb_diff'] = (qb_h if qb_h is not None else QB_MEAN) - (qb_a if qb_a is not None else QB_MEAN)
    x.update(situation(g) if g is not None else {'rest_diff': 0, 'bye_diff': 0, 'short_diff': 0, 'tz_diff': 0, 'west_early': 0,
                                                    'altitude': 0, 'neutral_i': 1 if neutral else 0})
    z = np.array([(x[f] - M2['mu'][f]) / M2['sd'][f] for f in M2F])
    return float(z @ M2B + M2I)


def model_total(h, a, roof, src=None):
    src = src or POST
    ppd_sum = src['o_ppd'][h] + src['d_ppd'][a] + src['o_ppd'][a] + src['d_ppd'][h]
    pace = (src['o_plays'][h] + src['o_plays'][a] + src['d_plays'][h] + src['d_plays'][a]) / 2
    dome = 1.0 if roof in ('dome', 'closed') else 0.0
    return float(np.array([ppd_sum, pace, dome, 1.0]) @ TBETA)


QB_MEAN = M2['qb_mean_starter']
qb_g = qb_g.merge(sched[['game_id', 'gameday']], on='game_id', how='left').sort_values(['gameday', 'game_id'])
starter_ids = {}
for _, r in sched[sched.season.between(SEASON - 2, SEASON)].iterrows():
    starter_ids[(r.game_id, r.home_team)] = r.home_qb_id if pd.notna(r.home_qb_id) else None
    starter_ids[(r.game_id, r.away_team)] = r.away_qb_id if pd.notna(r.away_qb_id) else None
top_db = qb_g.sort_values('db', ascending=False).groupby(['game_id', 'posteam']).head(1).set_index(['game_id', 'posteam'])
QB_NAME = dict(zip(qb_g.qb, qb_g.name))
_names = pd.concat([pd.read_csv(f'{RAW}/stats_player_week_{y}.csv', usecols=['player_id', 'player_display_name', 'position'], low_memory=False)
                    for y in (SEASON - 1, SEASON) if have_ps.get(y)], ignore_index=True).drop_duplicates('player_id', keep='last')
FULLNAME = dict(zip(_names.player_id, _names.player_display_name))
QB_ID_BY_NAME = dict(zip(_names[_names.position == 'QB'].player_display_name, _names[_names.position == 'QB'].player_id))
_hist = {}            # qb -> list of (season, dropbacks, epa)
_qb_pre = {}          # (game_id, team) -> (qb id, rating entering that game)


def qb_rating(qb, season):
    h = [(s, d, e) for s, d, e in _hist.get(qb, []) if season - s <= QBP['seasons_back']]
    num = sum(e * QBP['season_decay'] ** (season - s) for s, d, e in h)
    den = sum(d * QBP['season_decay'] ** (season - s) for s, d, e in h)
    return (QBP['k'] * QBP['target'] + num) / (QBP['k'] + den)


for gid, d in qb_g.groupby('game_id', sort=False):
    season = int(d.season.iloc[0])
    for team in d.posteam.unique():
        q = starter_ids.get((gid, team)) or (top_db.loc[(gid, team), 'qb'] if (gid, team) in top_db.index else None)
        if q:
            _qb_pre[(gid, team)] = (q, qb_rating(q, season))
    for _, r in d.iterrows():
        _hist.setdefault(r.qb, []).append((season, r.db, r.qb_epa))
last_starter = {}
for (gid, team), (q, _) in sorted(_qb_pre.items(), key=lambda kv: str(kv[0][0])):
    last_starter[team] = q


def current_qb(team, listed_id=None):
    q = listed_id if (listed_id and isinstance(listed_id, str)) else last_starter.get(team)
    if not q:
        return None, QB_MEAN
    return q, qb_rating(q, SEASON)


def qb_name(q, fallback=None):
    return FULLNAME.get(q) or fallback or QB_NAME.get(q) or 'Unknown QB'


for t in TEAMS:
    q, qr = current_qb(t)
    POST_AVG = {f: {t: POST[f][t], 'AVG': 0.0} for f in FEATS}
    teams[t]['power'] = model_margin(t, 'AVG', True, POST_AVG, None, qr, QB_MEAN)
    teams[t]['qb'] = {'name': qb_name(q), 'rating': qr} if q else None

hm = m26[m26.home == 1].set_index('game_id'); am = m26[m26.home == 0].set_index('game_id')


def pregame_src(gid, h, a):
    if gid not in hm.index or gid not in am.index:
        return None
    src = {f: {h: hm.at[gid, 'pre_' + f], a: am.at[gid, 'pre_' + f]} for f in FEATS}
    for c in ['o_ppd', 'd_ppd', 'o_plays', 'd_plays']:
        src[c] = {h: hm.at[gid, 'pre_' + c], a: am.at[gid, 'pre_' + c]}
    return src


# ------------------------------------------------------------------ season stat values and ranks
tg26 = tg_all[tg_all.season == SEASON]
STAT_COLS = ['off_epa', 'def_epa', 'off_sr', 'def_sr', 'off_early', 'def_early', 'off_pass', 'def_pass', 'off_rush', 'def_rush',
             'pd_g', 'ppd_off', 'ppd_def', 'sack_off', 'sack_def', 'to_g', 'expl_off', 'expl_def', 'third_off', 'third_def',
             'rz_off', 'rz_def', 'pts_g', 'opp_pts_g', 'plays_g']
LOW_GOOD = {'def_epa', 'def_sr', 'def_early', 'def_pass', 'def_rush', 'ppd_def', 'sack_off', 'expl_def', 'third_def', 'rz_def', 'opp_pts_g'}
if len(tg26):
    agg = tg26.groupby('team').sum(numeric_only=True)
    gp = tg26.groupby('team').size()

    def safe(a, b):
        return a / b.replace(0, np.nan)
    STAT = pd.DataFrame(index=agg.index)
    STAT['off_epa'] = safe(agg.epa_sum, agg.plays); STAT['def_epa'] = safe(agg.d_epa_sum, agg.d_plays)
    STAT['off_sr'] = safe(agg.succ_sum, agg.plays); STAT['def_sr'] = safe(agg.d_succ_sum, agg.d_plays)
    STAT['off_early'] = safe(agg.early_epa_sum, agg.early_n); STAT['def_early'] = safe(agg.d_early_epa_sum, agg.d_early_n)
    STAT['off_pass'] = safe(agg.pass_epa_sum, agg.dropbacks); STAT['def_pass'] = safe(agg.d_pass_epa_sum, agg.d_dropbacks)
    STAT['off_rush'] = safe(agg.rush_epa_sum, agg.rushes); STAT['def_rush'] = safe(agg.d_rush_epa_sum, agg.d_rushes)
    STAT['pd_g'] = (agg.pf - agg.pa) / gp
    STAT['ppd_off'] = safe(agg.drive_pts, agg.drives); STAT['ppd_def'] = safe(agg.d_drive_pts, agg.d_drives)
    STAT['sack_off'] = safe(agg.sacks, agg.dropbacks); STAT['sack_def'] = safe(agg.d_sacks, agg.d_dropbacks)
    STAT['to_g'] = (agg.d_to_n - agg.to_n) / gp
    STAT['expl_off'] = safe(agg.explosive_n, agg.plays); STAT['expl_def'] = safe(agg.d_explosive_n, agg.d_plays)
    STAT['third_off'] = safe(agg.third_conv, agg.third_conv + agg.third_fail)
    STAT['third_def'] = safe(agg.d_third_conv, agg.d_third_conv + agg.d_third_fail)
    STAT['rz_off'] = safe(agg.rz_tds, agg.rz_trips); STAT['rz_def'] = safe(agg.d_rz_tds, agg.d_rz_trips)
    STAT['pts_g'] = agg.pf / gp; STAT['opp_pts_g'] = agg.pa / gp; STAT['plays_g'] = agg.plays / gp
    RANK = pd.DataFrame({c: STAT[c].rank(ascending=c in LOW_GOOD, method='min') for c in STAT.columns})
else:
    STAT = pd.DataFrame(columns=STAT_COLS); RANK = pd.DataFrame(columns=STAT_COLS)
for t in TEAMS:
    teams[t]['stats'] = {c: (float(STAT.at[t, c]) if t in STAT.index and pd.notna(STAT.at[t, c]) else None) for c in STAT_COLS}
    teams[t]['ranks'] = {c: (int(RANK.at[t, c]) if t in RANK.index and pd.notna(RANK.at[t, c]) else None) for c in STAT_COLS}

# ------------------------------------------------------------------ QB changes
_p = pd.read_csv(f'{RAW}/stats_player_week_{SEASON}.csv', low_memory=False) if have_ps[SEASON] else pd.DataFrame(columns=['season_type', 'position', 'team', 'week', 'attempts', 'player_display_name'])
_p = _p[(_p.season_type == 'REG') & (_p.position == 'QB')]
_lead = _p.sort_values('attempts', ascending=False).groupby(['team', 'week']).head(1)
qb_starts = {t_: d_.player_display_name.value_counts().to_dict() for t_, d_ in _lead.groupby('team')}


def qb_change(team, listed):
    starts = qb_starts.get(team, {})
    if not listed or not starts:
        return None
    usual = max(starts, key=starts.get)
    if listed == usual or starts.get(listed, 0) >= starts[usual]:
        return None
    return {'starter': listed, 'usual': usual, 'starter_starts': int(starts.get(listed, 0)), 'usual_starts': int(starts[usual])}


def qb_change_at(team, listed, week):
    d_ = _lead[(_lead.team == team) & (_lead.week < week)]
    if d_.empty or pd.isna(listed):
        return None
    usual = d_.player_display_name.value_counts().idxmax()
    return None if listed == usual else {'starter': listed, 'usual': usual}


# ------------------------------------------------------------------ this week's games
def kickoff_iso(row):
    # nflverse times are US Eastern; EDT runs to the first Sunday in November
    d = dt.date.fromisoformat(str(row.gameday))
    nov1 = dt.date(d.year, 11, 1); first_sun_nov = nov1 + dt.timedelta(days=(6 - nov1.weekday()) % 7)
    mar1 = dt.date(d.year, 3, 1); second_sun_mar = mar1 + dt.timedelta(days=(6 - mar1.weekday()) % 7 + 7)
    off = '-04:00' if second_sun_mar <= d < first_sun_nov else '-05:00'
    return f"{row.gameday}T{row.gametime}:00{off}"


games = []
for _, g in wk_games.sort_values(['gameday', 'gametime']).iterrows():
    h, a = g.home_team, g.away_team
    neutral = bool(g.neutral)
    pre_src = pregame_src(g.game_id, h, a) if g.final else None
    srcg = pre_src or POST
    if pre_src is not None and (g.game_id, h) in _qb_pre and (g.game_id, a) in _qb_pre:
        (qh_id, qh), (qa_id, qa) = _qb_pre[(g.game_id, h)], _qb_pre[(g.game_id, a)]
    else:
        qh_id, qh = current_qb(h, g.home_qb_id if pd.notna(g.home_qb_id) else None)
        qa_id, qa = current_qb(a, g.away_qb_id if pd.notna(g.away_qb_id) else None)
    mm = model_margin(h, a, neutral, srcg, g, qh, qa); wp = ncdf(mm / RESID); mt = model_total(h, a, g.roof, srcg)
    ih, ia = am_prob(g.home_moneyline), am_prob(g.away_moneyline)
    nv_h = ih / (ih + ia) if ih and ia else None
    spread = float(g.spread_line) if pd.notna(g.spread_line) else None
    total = float(g.total_line) if pd.notna(g.total_line) else None
    s_edge = mm - spread if spread is not None else None
    t_edge = mt - total if total is not None else None
    qbc = {'home': qb_change(h, g.home_qb_name if pd.notna(g.home_qb_name) else None),
           'away': qb_change(a, g.away_qb_name if pd.notna(g.away_qb_name) else None)}
    pick_ats = None
    if s_edge is not None and abs(s_edge) >= 2.5:
        pick_ats = h if s_edge > 0 else a
    for side_, qid_, qr_ in (('home', qh_id, qh), ('away', qa_id, qa)):
        if qbc[side_]:
            usual_id = QB_ID_BY_NAME.get(qbc[side_]['usual'])
            qbc[side_]['starter_rating'] = qr_
            qbc[side_]['usual_rating'] = qb_rating(usual_id, SEASON) if usual_id else None
    teaser = []
    if spread is not None:
        for t_, ln_ in ((h, -spread), (a, spread)):
            if -8.5 <= ln_ <= -7.5:
                teaser.append({'team': t_, 'from': ln_, 'to': ln_ + 6, 'kind': 'fav', 'rate': SR['teaser']['fav_leg'], 'n': SR['teaser']['fav_n']})
            if 1.5 <= ln_ <= 2.5:
                teaser.append({'team': t_, 'from': ln_, 'to': ln_ + 6, 'kind': 'dog',
                               'rate': SR['teaser']['dog_leg_lowtotal'] if (total or 99) <= 49 else SR['teaser']['dog_leg'], 'n': SR['teaser']['dog_n']})
    mism = []
    for off, de, unit in (('off_pass', 'def_pass', 'pass'), ('off_rush', 'def_rush', 'run')):
        for o_t, d_t in ((h, a), (a, h)):
            ro, rd = teams[o_t]['ranks'].get(off), teams[d_t]['ranks'].get(de)
            if ro is not None and rd is not None and ro <= 8 and rd >= 25:
                mism.append({'off': o_t, 'def': d_t, 'unit': unit, 'off_rank': ro, 'def_rank': rd, 'kind': 'edge'})
    games.append({
        'id': g.game_id, 'week': int(g.week), 'away': a, 'home': h, 'kickoff': kickoff_iso(g), 'weekday': g.weekday,
        'stadium': g.stadium, 'roof': g.roof if pd.notna(g.roof) else None, 'neutral': neutral, 'div': bool(g.div_game),
        'spread': spread, 'total': total, 'ml_home': None if pd.isna(g.home_moneyline) else int(g.home_moneyline),
        'ml_away': None if pd.isna(g.away_moneyline) else int(g.away_moneyline),
        'final': bool(g.final), 'home_score': None if pd.isna(g.home_score) else int(g.home_score),
        'away_score': None if pd.isna(g.away_score) else int(g.away_score), 'live': live.get(g.game_id),
        'temp': None if pd.isna(g.temp) else int(g.temp), 'wind': None if pd.isna(g.wind) else int(g.wind),
        'qb_home': g.home_qb_name if pd.notna(g.home_qb_name) else None, 'qb_away': g.away_qb_name if pd.notna(g.away_qb_name) else None,
        'model': {'margin': mm, 'wp_home': wp, 'total': mt, 'spread_edge': s_edge, 'total_edge': t_edge, 'mkt_wp_home': nv_h,
                  'pick_ats': pick_ats, 'pick_total': None, 'pick_su': h if mm > 0 else a},
        'mismatches': mism, 'qb_change': qbc, 'teaser': teaser,
        'qb': {'home': {'name': qb_name(qh_id, g.home_qb_name if pd.notna(g.home_qb_name) else None), 'rating': qh},
               'away': {'name': qb_name(qa_id, g.away_qb_name if pd.notna(g.away_qb_name) else None), 'rating': qa}},
        'rest': {'home': None if pd.isna(g.home_rest) else int(g.home_rest), 'away': None if pd.isna(g.away_rest) else int(g.away_rest)}})

# ------------------------------------------------------------------ model pick record (pre-game info only)
model_picks = []
PRE_MM = {}
for _, g in done.sort_values(['week', 'gameday', 'gametime']).iterrows():
    gid, h, a = g.game_id, g.home_team, g.away_team
    src = pregame_src(gid, h, a)
    if src is None:
        if int(g.week) != WEEK:
            continue
        src = POST     # final per the scoreboard but not in play-by-play yet, so current ratings are still pre-game
    if (gid, h) in _qb_pre and (gid, a) in _qb_pre:
        qh_, qa_ = _qb_pre[(gid, h)][1], _qb_pre[(gid, a)][1]
    else:
        qh_, qa_ = current_qb(h, g.home_qb_id if pd.notna(g.home_qb_id) else None)[1], current_qb(a, g.away_qb_id if pd.notna(g.away_qb_id) else None)[1]
    mm = model_margin(h, a, bool(g.neutral), src, g, qh_, qa_)
    PRE_MM[gid] = mm
    margin = g.home_score - g.away_score
    base = {'week': int(g.week), 'game': gid, 'away': a, 'home': h, 'score': f"{a} {int(g.away_score)} - {h} {int(g.home_score)}"}
    su = h if mm > 0 else a
    model_picks.append({**base, 'type': 'Winner', 'pick': su, 'detail': f"{su} to win (model {abs(mm):.1f})",
                        'result': 'P' if margin == 0 else ('W' if (margin > 0) == (su == h) else 'L')})
    if pd.isna(g.spread_line):
        continue
    edge = mm - g.spread_line
    if abs(edge) >= 2.5:
        side = h if edge > 0 else a
        line = -g.spread_line if side == h else g.spread_line
        cov = margin - g.spread_line
        res = 'P' if cov == 0 else ('W' if (cov > 0) == (side == h) else 'L')
        model_picks.append({**base, 'type': 'Spread', 'pick': side, 'detail': f"{side} {line:+.1f}", 'edge': abs(edge), 'result': res})

# ------------------------------------------------------------------ injuries: official report + ESPN status / return date
PRAC = {'Did Not Participate In Practice': 'DNP', 'Limited Participation in Practice': 'LP', 'Full Participation in Practice': 'FP'}
inj = pd.read_csv(f'{RAW}/injuries_{SEASON}.csv', low_memory=False) if have_inj else pd.DataFrame(columns=['week', 'team', 'full_name', 'position', 'practice_status', 'report_status', 'practice_primary_injury', 'report_primary_injury'])
inj = inj[inj.week == WEEK].copy()
inj['key'] = inj.team + '|' + inj.full_name.map(norm)
esp = espn.injuries()
snaps = pd.read_csv(f'{RAW}/snap_counts_{SEASON}.csv', low_memory=False) if have_snap else pd.DataFrame(columns=['team', 'player', 'offense_pct', 'defense_pct', 'pfr_player_id', 'week'])
p26_all = pa.load_players([SEASON]) if have_ps[SEASON] else pd.DataFrame(columns=pa.COLS)
snap_avg = snaps.groupby(['team', 'player']).agg(o=('offense_pct', 'mean'), d=('defense_pct', 'mean')).reset_index()
snap_avg['key'] = snap_avg.team + '|' + snap_avg.player.map(norm)
starters = set(snap_avg[(snap_avg.o >= 0.5) | (snap_avg.d >= 0.5)].key)
usage = p26_all.groupby(['team', 'player_display_name']).agg(t=('targets', 'mean'), c=('carries', 'mean'), a=('attempts', 'mean')).reset_index()
usage['key'] = usage.team + '|' + usage.player_display_name.map(norm)
skill_keys = set(usage[(usage.t >= 3) | (usage.c >= 6) | (usage.a >= 15)].key)
played_teams = {x for gm in games if gm['final'] for x in (gm['home'], gm['away'])}


def week_for_date(team, date_str):
    try:
        d = str(date_str)[:10]
        g = S[((S.home_team == team) | (S.away_team == team)) & (S.gameday >= d)]
        return int(g.week.min()) if len(g) else None
    except Exception:
        return None


def outlook(team, status, prac, e):
    """Plain-language outlook from official game status, latest practice day and ESPN's status/return date."""
    es = (e or {}).get('status') or ''
    ret_wk = week_for_date(team, e['return_date']) if e and e.get('return_date') else None
    long_list = any(k in es for k in ('Injured Reserve', 'Physically Unable', 'Non-Football', 'Suspension', 'Reserve'))
    if long_list and prac in ('FP', 'LP'):
        return ('likely' if prac == 'FP' else 'gtd'), f'Back at practice from {"IR" if "Injured" in es else "a reserve list"} ({"full" if prac == "FP" else "limited"}), could be activated', ret_wk
    if long_list:
        lst = 'IR' if 'Injured' in es else ('suspension' if 'Suspension' in es else 'a reserve list')
        if ret_wk and ret_wk > WEEK:
            return 'ir', f'On {lst}, expected back Week {ret_wk}', ret_wk
        return 'ir', f'On {lst}', ret_wk
    if team in played_teams:
        if status == 'Out' or es == 'Out':
            return 'out', f'Missed Week {WEEK}' + (f'; expected back Week {ret_wk}' if ret_wk and ret_wk > WEEK else ''), ret_wk
        return 'ok', f'Available Week {WEEK}', ret_wk
    if status == 'Out' or es == 'Out':
        return 'out', 'Out this week' + (f', expected back Week {ret_wk}' if ret_wk and ret_wk > WEEK else ''), ret_wk
    if status == 'Doubtful' or es == 'Doubtful':
        return 'doubt', 'Unlikely to play', ret_wk
    if prac == 'FP':
        return 'likely', 'Full practice, expected to play', ret_wk
    if prac == 'LP':
        return 'gtd', 'Limited in practice, game-time call', ret_wk
    if prac == 'DNP':
        return 'risk', 'Did not practice, in doubt', ret_wk
    if status == 'Questionable' or es == 'Questionable':
        return 'gtd', 'Questionable', ret_wk
    return 'gtd', 'Monitor', ret_wk


injuries = {t: [] for t in TEAMS}
seen = set()
for _, r in inj.iterrows():
    k = r.key; e = esp.get(k)
    prac = PRAC.get(r.practice_status)
    status = r.report_status if pd.notna(r.report_status) else None
    reason = r.practice_primary_injury if pd.notna(r.practice_primary_injury) else (r.report_primary_injury if pd.notna(r.report_primary_injury) else '')
    if 'resting player' in str(reason).lower():
        lvl, ol, rw = 'likely', 'Rest day, not injured', None
    elif 'personal matter' in str(reason).lower():
        lvl, ol, rw = 'gtd', 'Personal matter', None
    else:
        lvl, ol, rw = outlook(r.team, status, prac, e)
    if r.team in injuries:
        injuries[r.team].append({'name': r.full_name, 'pos': r.position, 'injury': str(reason).replace('Not injury related - ', '') or None,
                                 'status': status, 'practice': prac, 'level': lvl, 'outlook': ol, 'ret_wk': rw,
                                 'key': (k in starters) or (k in skill_keys), 'skill': k in skill_keys})
    seen.add(k)
for k, e in esp.items():
    if k in seen or e['team'] not in injuries:
        continue
    es = e.get('status') or ''
    if not any(s in es for s in ('Injured Reserve', 'Physically Unable', 'Out', 'Doubtful', 'Non-Football', 'Suspension')):
        continue
    lvl, ol, rw = outlook(e['team'], None, None, e)
    injuries[e['team']].append({'name': e['name'], 'pos': e.get('pos'), 'injury': e.get('injury'), 'status': None, 'practice': None,
                                'level': lvl, 'outlook': ol, 'ret_wk': rw, 'key': (k in starters) or (k in skill_keys), 'skill': k in skill_keys})
_rost = pd.read_csv(f'{RAW}/roster_weekly_{SEASON}.csv', low_memory=False) if have_rost else pd.DataFrame(columns=['week', 'team', 'full_name', 'position', 'status', 'gsis_id'])
_rw = _rost[_rost.week <= WEEK]
_rw = _rw[_rw.week == _rw.week.max()] if len(_rw) else _rw
RESERVE_IDS = set(_rw[_rw.status.isin(['RES'])].gsis_id.dropna())
GONE_IDS = set(_rw[_rw.status.isin(['CUT', 'RET', 'TRD', 'TRT'])].gsis_id.dropna())
for _, r in _rw[_rw.status == 'RES'].iterrows():
    k = str(r.team) + '|' + norm(r.full_name)
    if k in seen or r.team not in injuries or any(norm(x['name']) == norm(r.full_name) for x in injuries[r.team]):
        continue
    injuries[r.team].append({'name': r.full_name, 'pos': r.position, 'injury': None, 'status': None, 'practice': None,
                             'level': 'ir', 'outlook': 'On injured reserve or another reserve list', 'ret_wk': None,
                             'key': (k in starters) or (k in skill_keys), 'skill': k in skill_keys})
ORDER = {'out': 0, 'doubt': 1, 'risk': 2, 'gtd': 3, 'likely': 4, 'ir': 5, 'ok': 6}
for t in injuries:
    injuries[t].sort(key=lambda x: (not x['key'], ORDER.get(x['level'], 9), x['name']))
inj_status = {t + '|' + norm(x['name']): x for t, lst in injuries.items() for x in lst}

# ------------------------------------------------------------------ players: projections and logs
ngs = pa.load_ngs()
p25 = pa.load_players([SEASON - 1]); p26 = p26_all
rost = pd.read_csv(f'{RAW}/roster_weekly_{SEASON}.csv', low_memory=False) if have_rost else pd.DataFrame(columns=['week', 'gsis_id', 'pfr_id'])
latest_rost = rost.sort_values('week').groupby('gsis_id').tail(1)
snaps = snaps.merge(latest_rost[['pfr_id', 'gsis_id']].dropna().drop_duplicates('pfr_id'), left_on='pfr_player_id', right_on='pfr_id', how='left')
snap26 = snaps.groupby(['gsis_id', 'week']).offense_pct.max().reset_index()
MODELS = PR['models']


def project(row, key):
    mdl = MODELS[key]
    x = [row.get(f) for f in mdl['feats']]
    if any(v is None or (isinstance(v, float) and not np.isfinite(v)) for v in x):
        return None
    return float(np.dot(np.r_[x, 1.0], mdl['beta']))


def snap_info(pid):
    s = snap26[snap26.gsis_id == pid].sort_values('week')
    if s.empty:
        return None, []
    return float(s.offense_pct.tail(2).mean()), [[int(w), float(v)] for w, v in zip(s.week, s.offense_pct)]


def player_log(pid):
    d = p26[p26.player_id == pid].sort_values('week')
    return [{'wk': int(r.week), 'opp': r.opponent_team, 'cmp': int(r.completions or 0), 'att': int(r.attempts or 0),
             'py': int(r.passing_yards or 0), 'ptd': int(r.passing_tds or 0), 'int': int(r.passing_interceptions or 0),
             'car': int(r.carries or 0), 'ry': int(r.rushing_yards or 0), 'rtd': int(r.rushing_tds or 0),
             'rec': int(r.receptions or 0), 'tgt': int(r.targets or 0), 'recy': int(r.receiving_yards or 0),
             'rectd': int(r.receiving_tds or 0), 'ts': None if pd.isna(r.target_share) else round(float(r.target_share), 3)}
            for _, r in d.iterrows()]


def r_(v, n=1):
    return None if v is None or not np.isfinite(v) else round(float(v), n)


props_by_game = {}
upcoming = [gm for gm in games if not gm['final']]
if len(p26) and upcoming:
    cur_team = p26.sort_values('week').groupby('player_id').tail(1)[['player_id', 'player_display_name', 'position', 'team']]
    up = pd.DataFrame([{'player_id': pl.player_id, 'player_display_name': pl.player_display_name, 'position': pl.position,
                        'season': SEASON, 'week': WEEK, 'season_type': 'REG', 'game_id': gm['id'], 'team': t, 'opponent_team': o}
                       for gm in upcoming for t, o in ((gm['home'], gm['away']), (gm['away'], gm['home']))
                       for _, pl in cur_team[cur_team.team == t].iterrows()])
    if len(up):
        feat = pa.add_defense_vs_position(pa.build_features(pd.concat([p26, up], ignore_index=True), sched, rz_all[rz_all.season == SEASON], ngs))
        cur = feat[(feat.week == WEEK) & feat.game_id.isin(up.game_id)].drop_duplicates(['player_id', 'game_id'])
        for gm in upcoming:
            out = []
            for t in (gm['away'], gm['home']):
                c = cur[(cur.game_id == gm['id']) & (cur.team == t) & (cur.n_prior >= 2)]
                if c.empty:
                    continue
                qb = c[c.position == 'QB'].sort_values('pg_attempts', ascending=False).head(1)
                rb = c[(c.position == 'RB') & (c.pg_carries >= 5)].sort_values('pg_carries', ascending=False).head(2)
                rc = c[c.position.isin(['WR', 'TE']) & (c.pg_targets >= 3)].sort_values('pg_targets', ascending=False).head(4)
                for _, r in pd.concat([qb, rb, rc]).iterrows():
                    row = r.to_dict()
                    ist = inj_status.get(t + '|' + norm(r.player_display_name))
                    if (ist and ist['level'] == 'ir') or r.player_id in RESERVE_IDS or r.player_id in GONE_IDS:
                        continue
                    pos = r.position; pj = {}
                    if pos == 'QB':
                        pj['pass_yds'] = project(row, 'pass_yds')
                    if pos == 'RB':
                        pj['rush_yds'] = project(row, 'rush_yds')
                        if r.pg_targets >= 2.5:
                            pj['receptions'] = project(row, 'receptions')
                        pj['any_td'] = project(row, 'any_td')
                    if pos in ('WR', 'TE'):
                        pj['rec_yds'] = project(row, 'rec_yds'); pj['receptions'] = project(row, 'receptions'); pj['any_td'] = project(row, 'any_td')
                    if pj.get('any_td') is not None:
                        pj['any_td'] = float(np.clip(pj['any_td'], 0.02, 0.85))
                    snap_now, snap_series = snap_info(r.player_id)
                    out.append({'id': r.player_id, 'name': r.player_display_name, 'pos': pos, 'team': t, 'gp': int(r.n_prior),
                                'proj': {k: r_(v, 2 if k == 'any_td' else 1) for k, v in pj.items()},
                                'avg': {'pass_yds': r_(r.pg_passing_yards), 'att': r_(r.pg_attempts), 'rush_yds': r_(r.pg_rushing_yards),
                                        'car': r_(r.pg_carries), 'rec_yds': r_(r.pg_receiving_yards), 'rec': r_(r.pg_receptions),
                                        'tgt': r_(r.pg_targets), 'td': r_(r.pg_any_td, 2)},
                                'l3': {'pass_yds': r_(r.l3_passing_yards), 'rush_yds': r_(r.l3_rushing_yards), 'rec_yds': r_(r.l3_receiving_yards),
                                       'tgt': r_(r.l3_targets), 'car': r_(r.l3_carries)},
                                'share': {'tgt': r_(r.avg_target_share, 3), 'ay': r_(r.avg_air_yards_share, 3), 'car': r_(r.avg_carry_share, 3),
                                          'wopr': r_(r.avg_wopr, 3)},
                                'rz': r_((r.pg_rz_carries or 0) + (r.pg_rz_targets or 0), 2), 'implied': r_(r.implied_tt),
                                'snap': r_(snap_now, 3), 'snaps': snap_series,
                                'inj': ({'level': ist['level'], 'outlook': ist['outlook'], 'status': ist['status'], 'practice': ist['practice']} if ist else None),
                                'log': player_log(r.player_id)})
            props_by_game[gm['id']] = out
for gm in games:
    gm['props'] = props_by_game.get(gm['id'], [])

# ------------------------------------------------------------------ trends (must last 2+ weeks)
CARRY = {r['trend']: r for r in TR['team'] + TR['player']}


def carry_note(label):
    r = CARRY.get(label)
    if not r or r['rate'] is None:
        return None
    return {'rate': r['rate'], 'base': r['base'], 'n': r['n'], 'next': r['next']}


team_trends = []
mt26 = m26.sort_values(['team', 'week'])
for t in TEAMS:
    lg = logs[logs.team == t]
    if len(lg) < 2:
        continue
    weeks = lg.week.tolist()

    def add(kind, label, n, series, note_key, tone, detail=None, metric=None):
        team_trends.append({'team': t, 'kind': kind, 'label': label, 'weeks': n, 'series': series, 'tone': tone,
                            'detail': detail, 'carry': carry_note(note_key) if note_key else None, 'metric': metric})
    res, ats, ou = lg.res.tolist(), lg.ats.tolist(), lg.ou.tolist()
    for flag, word, tone, note in (('W', 'Won', 'up', 'Won {n}+ straight'), ('L', 'Lost', 'down', 'Lost {n}+ straight')):
        n = run_len([x == flag for x in res])
        if n >= 2:
            add('streak', f'{word} {n} straight', n, [[w, 1 if r == 'W' else 0] for w, r in zip(weeks, res)], note.format(n=min(n, 3)), tone, metric='su')
    for flag, word, tone, note in (('W', 'Covered', 'up', 'Covered {n}+ straight'), ('L', 'Failed to cover', 'down', 'Failed to cover {n}+ straight')):
        n = run_len([x == flag for x in ats])
        if n >= 2:
            add('betting', f'{word} {n} straight', n, [[w, 1 if r == 'W' else 0] for w, r in zip(weeks, ats)], note.format(n=min(n, 3)), tone, metric='ats')
    for flag, word, tone, note in (('O', 'Overs', 'up', 'Games went over {n}+ straight'), ('U', 'Unders', 'down', 'Games went under {n}+ straight')):
        n = run_len([x == flag for x in ou])
        if n >= 2:
            add('betting', f'{word} {n} straight', n, [[w, 1 if r == 'O' else 0] for w, r in zip(weeks, ou)], note.format(n=min(n, 3)), tone, metric='ou')
    tm = mt26[mt26.team == t]
    if len(tm):
        o_d = (tm.o_epa_play - tm.pre_o_epa_play).tolist(); d_d = (tm.d_epa_play - tm.pre_d_epa_play).tolist(); wks = tm.week.tolist()
        for vals, cond, lbl, note, tone, series_col, det, metric in (
                (o_d, lambda x: x > 0.05, 'Offense beating its rating', 'Offense+defense beat its rating {n}+ straight', 'up', 'o_epa_play', 'EPA/play vs. expected', 'off_epa'),
                (o_d, lambda x: x < -0.05, 'Offense below its rating', 'Played below its rating {n}+ straight', 'down', 'o_epa_play', 'EPA/play vs. expected', 'off_epa'),
                (d_d, lambda x: x < -0.05, 'Defense beating its rating', 'Offense+defense beat its rating {n}+ straight', 'up', 'd_epa_play', 'EPA/play allowed vs. expected', 'def_epa'),
                (d_d, lambda x: x > 0.05, 'Defense below its rating', 'Played below its rating {n}+ straight', 'down', 'd_epa_play', 'EPA/play allowed vs. expected', 'def_epa')):
            n = run_len([cond(x) for x in vals])
            if n >= 2:
                add('form', f'{lbl} {n} straight', n, [[w, round(float(v), 3)] for w, v in zip(wks, tm[series_col])],
                    note.format(n=min(n, 3)), tone, f'{det}: ' + ', '.join(f'{v:+.2f}' for v in vals[-n:]), metric)
    n = run_len([x >= 27 for x in lg.pf])
    if n >= 2:
        add('form', f'Scored 27+ in {n} straight', n, [[w, int(v)] for w, v in zip(weeks, lg.pf)], None, 'up', metric='pts')
    n = run_len([x <= 17 for x in lg.pa])
    if n >= 2:
        add('form', f'Held opponents to 17 or fewer {n} straight', n, [[w, int(v)] for w, v in zip(weeks, lg.pa)], None, 'up', metric='opp_pts')
    n = run_len([x >= 27 for x in lg.pa])
    if n >= 2:
        add('form', f'Allowed 27+ in {n} straight', n, [[w, int(v)] for w, v in zip(weeks, lg.pa)], None, 'down', metric='opp_pts')

hist_g = sched[(sched.season.between(SEASON - 5, SEASON - 1)) & (sched.game_type == 'REG') & sched.home_score.notna()].copy()


def league_week_frame(df):
    df = df.copy()
    df['pts'] = df.home_score + df.away_score
    df['over'] = np.sign(df.pts - df.total_line)
    df['fav_cover'] = np.where(df.spread_line > 0, np.sign(df.result - df.spread_line), np.where(df.spread_line < 0, np.sign(df.spread_line - df.result), np.nan))
    df['home_cover'] = np.sign(df.result - df.spread_line)
    df['upset'] = np.where(df.spread_line != 0, ((df.spread_line > 0) & (df.result < 0)) | ((df.spread_line < 0) & (df.result > 0)), np.nan)
    df['home_win'] = np.where(df.result != 0, (df.result > 0).astype(float), np.nan)
    return df


hist_g = league_week_frame(hist_g)
cur_g = league_week_frame(done[done.game_type == 'REG'] if 'game_type' in done.columns else done)


def wrate(x):
    x = x[x != 0].dropna()
    return float((x > 0).mean()) if len(x) else np.nan


LEAGUE_METRICS = [('pts', 'Points per game', lambda d: float(d.pts.mean()), 'pts'),
                  ('over', 'Overs hitting', lambda d: wrate(d.over), 'pct'),
                  ('fav_cover', 'Favorites covering', lambda d: wrate(d.fav_cover), 'pct'),
                  ('home_cover', 'Home teams covering', lambda d: wrate(d.home_cover), 'pct'),
                  ('upset', 'Underdogs winning outright', lambda d: float(d.upset.dropna().mean()), 'pct'),
                  ('home_win', 'Home teams winning', lambda d: float(d.home_win.dropna().mean()), 'pct')]
league_trends, league_weekly = [], {}
full_weeks = sorted(cur_g.groupby('week').size()[lambda s: s >= 8].index.tolist())
KIND = {'over': 'betting', 'fav_cover': 'betting', 'home_cover': 'betting', 'upset': 'results', 'home_win': 'results', 'pts': 'scoring'}
for key, label, f, fmt in LEAGUE_METRICS:
    base = f(hist_g)
    series = [[int(w), f(cur_g[cur_g.week == w])] for w in full_weeks]
    league_weekly[key] = {'label': label, 'base': base, 'series': series, 'fmt': fmt}
    vals = [v for _, v in series]; tol = 1.0 if fmt == 'pts' else 0.03
    for n, tone, word in ((run_len([v > base + tol for v in vals]), 'up', 'above'), (run_len([v < base - tol for v in vals]), 'down', 'below')):
        if n >= 2:
            league_trends.append({'key': key, 'label': f'{label} {word} normal for {n} straight weeks', 'weeks': n, 'tone': tone,
                                  'series': series, 'base': base, 'fmt': fmt, 'kind': KIND[key]})
pbp_week = m26.groupby('week').agg(proe=('o_proe', 'mean'), sack=('o_sack_rate', 'mean'), epa=('o_epa_play', 'mean')) if len(m26) else pd.DataFrame()
for key, label, fmt, tol in (('proe', 'Pass rate over expected', 'pp', 1.0), ('sack', 'Sack rate', 'pct', 0.005), ('epa', 'Offensive EPA per play', 'epa', 0.015)):
    series = [[int(w), float(pbp_week.at[w, key])] for w in full_weeks if w in pbp_week.index]
    base = float(STYLE_BASE[key])
    league_weekly[key] = {'label': label, 'base': base, 'series': series, 'fmt': fmt}
    vals = [v for _, v in series]
    for n, tone, word in ((run_len([v > base + tol for v in vals]), 'up', 'above'), (run_len([v < base - tol for v in vals]), 'down', 'below')):
        if n >= 2:
            league_trends.append({'key': key, 'label': f'{label} {word} normal for {n} straight weeks', 'weeks': n, 'tone': tone,
                                  'series': series, 'base': base, 'fmt': fmt, 'kind': 'style'})

p25g = p25.groupby('player_id').agg(g=('week', 'size'), targets=('targets', 'mean'), carries=('carries', 'mean'),
                                     receiving_yards=('receiving_yards', 'mean'), rushing_yards=('rushing_yards', 'mean'),
                                     passing_yards=('passing_yards', 'mean'), target_share=('target_share', 'mean'))
PT = [('targets', 'Targets', ['WR', 'TE', 'RB'], 3, 0.25, 2, 'Targets above his average {n}+ straight'),
      ('target_share', 'Target share', ['WR', 'TE', 'RB'], 0.10, 0.20, 0.04, 'Targets above his average {n}+ straight'),
      ('receiving_yards', 'Receiving yards', ['WR', 'TE'], 30, 0.30, 15, 'Receiving yards above his average {n}+ straight'),
      ('carries', 'Carries', ['RB'], 6, 0.20, 3, 'Carries above his average {n}+ straight'),
      ('rushing_yards', 'Rushing yards', ['RB', 'QB'], 25, 0.30, 15, 'Rushing yards above his average {n}+ straight'),
      ('passing_yards', 'Passing yards', ['QB'], 150, 0.15, 30, 'Passing yards above his average {n}+ straight')]
player_trends = []
if len(p26):
    p26s = p26.sort_values(['player_id', 'week'])
    names = p26s.groupby('player_id').agg(name=('player_display_name', 'last'), pos=('position', 'last'), team=('team', 'last'))
    for pid, d in p26s.groupby('player_id'):
        if len(d) < 2:
            continue
        nm, pos, team = names.at[pid, 'name'], names.at[pid, 'pos'], names.at[pid, 'team']
        ist = inj_status.get(team + '|' + norm(nm))
        for col, label, poss, min_usual, rel, ab, carry_lbl in PT:
            if pos not in poss:
                continue
            vals = d[col].fillna(0).astype(float).tolist(); wks = d.week.tolist()
            prior25 = p25g[col].get(pid, np.nan) if pid in p25g.index and p25g.at[pid, 'g'] >= 4 else np.nan
            up_f, dn_f, usual_l = [], [], []
            for i in range(len(vals)):
                prev = vals[:i]
                usual = (3 * prior25 + sum(prev)) / (3 + len(prev)) if np.isfinite(prior25) else (float(np.mean(prev)) if prev else np.nan)
                usual_l.append(usual)
                if not np.isfinite(usual) or usual < min_usual:
                    up_f.append(False); dn_f.append(False); continue
                up_f.append(vals[i] >= usual * (1 + rel) and vals[i] >= usual + ab)
                dn_f.append(vals[i] <= usual * (1 - rel) and vals[i] <= usual - ab)
            for flags, tone in ((up_f, 'up'), (dn_f, 'down')):
                n = run_len(flags)
                if n >= 2:
                    usual_now = usual_l[-n]; recent = vals[-n:]
                    player_trends.append({'id': pid, 'name': nm, 'pos': pos, 'team': team, 'metric': col, 'label': label, 'tone': tone,
                                          'weeks': n, 'usual': usual_now, 'recent': recent, 'pct': float(np.mean(recent) / usual_now - 1) if usual_now else 0.0,
                                          'series': [[int(w), v] for w, v in zip(wks, vals)],
                                          'carry': carry_note(carry_lbl.format(n=min(n, 3))) if tone == 'up' else None,
                                          'sticky': col in ('targets', 'target_share', 'carries', 'passing_yards'),
                                          'inj': ({'level': ist['level'], 'outlook': ist['outlook']} if ist else None)})
    for pid, s in snap26.groupby('gsis_id'):
        s = s.sort_values('week')
        if len(s) < 3 or pid not in names.index:
            continue
        vals = s.offense_pct.tolist(); wks = s.week.tolist()
        nm, pos, team = names.at[pid, 'name'], names.at[pid, 'pos'], names.at[pid, 'team']
        if pos not in ('RB', 'WR', 'TE'):
            continue
        up_f = [False] + [vals[i] >= np.mean(vals[:i]) + 0.10 for i in range(1, len(vals))]
        dn_f = [False] + [vals[i] <= np.mean(vals[:i]) - 0.10 for i in range(1, len(vals))]
        for flags, tone in ((up_f, 'up'), (dn_f, 'down')):
            n = run_len(flags)
            if n >= 2:
                usual = float(np.mean(vals[:-n])); ist = inj_status.get(team + '|' + norm(nm))
                player_trends.append({'id': pid, 'name': nm, 'pos': pos, 'team': team, 'metric': 'snap', 'label': 'Snap share', 'tone': tone,
                                      'weeks': n, 'usual': usual, 'recent': vals[-n:], 'pct': float(np.mean(vals[-n:]) - usual),
                                      'series': [[int(w), float(v)] for w, v in zip(wks, vals)], 'carry': None, 'sticky': True,
                                      'inj': ({'level': ist['level'], 'outlook': ist['outlook']} if ist else None)})
STICKY_W = {'targets': 1.2, 'target_share': 1.2, 'carries': 1.3, 'snap': 1.2, 'passing_yards': 1.1, 'receiving_yards': 0.9, 'rushing_yards': 0.9}
for p_ in player_trends:
    mag = abs(p_['pct']) * (3 if p_['metric'] == 'snap' else 1)
    p_['score'] = float(mag * p_['weeks'] * STICKY_W.get(p_['metric'], 1))
player_trends.sort(key=lambda x: -x['score'])
team_trends.sort(key=lambda x: (-x['weeks'], x['kind'] != 'form'))

# ------------------------------------------------------------------ high-chance picks
PD = json.load(open(os.path.join(HERE, 'static', 'prop_dist.json')))
HCR = json.load(open(os.path.join(HERE, 'static', 'high_chance_research.json')))
STAT_COL = {'rec_yds': 'receiving_yards', 'receptions': 'receptions', 'rush_yds': 'rushing_yards', 'pass_yds': 'passing_yards'}
STAT_WORD = {'rec_yds': 'receiving yards', 'receptions': 'catches', 'rush_yds': 'rushing yards', 'pass_yds': 'passing yards'}
POS_WORD = {'WR': 'wide receivers', 'TE': 'tight ends', 'RB': 'running backs', 'QB': 'quarterbacks'}
KEYCOL = {'rec_yds': 'recy', 'receptions': 'rec', 'rush_yds': 'rush', 'pass_yds': 'passy'}


def chance(key, proj, t):
    dist = PD['dists'][key]; grid = dist['grid']; bins = dist['bins']; cs = [b['center'] for b in bins]

    def surv(b):
        if t <= grid[0]:
            return b['surv'][0]
        if t >= grid[-1]:
            return b['surv'][-1]
        j = int(np.searchsorted(grid, t)) - 1
        w = (t - grid[j]) / (grid[j + 1] - grid[j])
        return b['surv'][j] * (1 - w) + b['surv'][j + 1] * w
    if proj <= cs[0]:
        return surv(bins[0])
    if proj >= cs[-1]:
        return surv(bins[-1])
    k = int(np.searchsorted(cs, proj)) - 1
    w = (proj - cs[k]) / (cs[k + 1] - cs[k])
    return surv(bins[k]) * (1 - w) + surv(bins[k + 1]) * w


def hc_eligible(r, key):
    if (r.n_prior or 0) < 3:
        return False
    if key == 'pass_yds':
        return r.position == 'QB' and (r.pg_attempts or 0) >= 25
    if key == 'rush_yds':
        return r.position == 'RB' and (r.avg_carry_share or 0) >= 0.45
    if r.position not in (('WR', 'TE') if key == 'rec_yds' else ('WR', 'TE', 'RB')):
        return False
    return (r.avg_target_share or 0) >= 0.18 or (r.pg_targets or 0) >= 6


def best_milestone(r):
    row = r.to_dict(); best = None
    for key in ('rec_yds', 'receptions', 'rush_yds', 'pass_yds'):
        if not hc_eligible(r, key):
            continue
        proj = project(row, key)
        if proj is None:
            continue
        pick = None
        for t in PD['ladders'][key]:
            p = chance(key, proj, t)
            if p >= PD['p_min']:
                pick = (p, key, t, proj)
        if pick and (best is None or (pick[1] != 'receptions', pick[0]) > (best[1] != 'receptions', best[0])):
            best = pick
    return best


def fair_odds(p):
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


dvp = {}
if len(p26):
    _al = p26.groupby(['opponent_team', 'position', 'week']).agg(recy=('receiving_yards', 'sum'), rec=('receptions', 'sum'),
                                                                 rush=('rushing_yards', 'sum'), passy=('passing_yards', 'sum')).reset_index()
    _pg = _al.groupby(['opponent_team', 'position'])[['recy', 'rec', 'rush', 'passy']].mean().reset_index()
    for pos_, col_ in (('WR', 'recy'), ('TE', 'recy'), ('RB', 'recy'), ('WR', 'rec'), ('TE', 'rec'), ('RB', 'rec'), ('RB', 'rush'), ('QB', 'passy')):
        s_ = _pg[_pg.position == pos_].set_index('opponent_team')[col_].rank(ascending=False, method='min')
        for tm_, rk_ in s_.items():
            dvp[(tm_, pos_, col_)] = int(rk_)
trend_by_player = {}
for p_ in player_trends:
    if p_['tone'] == 'up' and p_['sticky'] and p_['id'] not in trend_by_player:
        trend_by_player[p_['id']] = p_


def hc_reason(r, key, t, opp, team):
    parts = [w for w in r.player_display_name.split(' ') if w.rstrip('.') not in ('Jr', 'Sr', 'II', 'III', 'IV', 'V')]
    first = ' '.join(parts[1:]) if len(parts) > 1 else r.player_display_name
    d_ = p26[(p26.player_id == r.player_id)].sort_values('week')
    vals = d_[STAT_COL[key]].fillna(0).tolist()
    hits = sum(1 for v in vals if v >= t)
    avg = float(np.mean(vals)) if vals else None
    l3 = float(np.mean(vals[-3:])) if len(vals) >= 3 else None
    word = STAT_WORD[key]; fmt = (lambda v: f'{v:.1f}') if key == 'receptions' else (lambda v: f'{v:.0f}')
    s1 = f"{first} has reached {t}+ {word} in {hits} of {len(vals)} games, averaging {fmt(avg)}"
    if l3 is not None and avg and abs(l3 - avg) / max(avg, 1) >= 0.08:
        s1 += f" ({fmt(l3)} over his last 3)"
    s1 += '.'
    if key == 'pass_yds':
        s2 = f"He's throwing {r.pg_attempts:.0f} passes a game."
    elif key == 'rush_yds':
        s2 = f"He gets {r.avg_carry_share:.0%} of the team's carries ({r.pg_carries:.1f} a game)."
    else:
        s2 = f"He's seeing {r.pg_targets:.1f} targets a game ({r.avg_target_share:.0%} of the team's)."
    extra = []
    tr = trend_by_player.get(r.player_id)
    if tr:
        lbl = tr['label'].lower()
        extra.append(f"His {lbl} {'has' if lbl.endswith('share') else 'have'} been up {tr['weeks']} straight weeks.")
    rk = dvp.get((opp, r.position, KEYCOL[key]))
    onick = TEAMS[opp][1] if opp in TEAMS else opp
    if rk is not None and rk <= 10:
        extra.append(f"The {onick} allow the {'' if rk == 1 else ordinal(rk) + '-'}most {'receiving yards' if key == 'rec_yds' else word} to {POS_WORD[r.position]}.")
    if r.implied_tt and r.implied_tt >= 25.5:
        extra.append(f"The {TEAMS[team][1]} are projected by the betting line to score {r.implied_tt:.1f} points.")
    if rk is not None and rk >= 24:
        extra.append(f"Tougher matchup: the {onick} allow the {'' if rk == 32 else ordinal(33 - rk) + '-'}fewest.")
    return ' '.join([s1, s2] + extra[:1]), hits, len(vals), avg, l3


hc_picks, hc_hist = [], []
if 'feat' in globals() and len(p26):
    # this week
    for gm in games:
        if gm['final']:
            continue
        for t, o in ((gm['away'], gm['home']), (gm['home'], gm['away'])):
            c = cur[(cur.game_id == gm['id']) & (cur.team == t)]
            for _, r in c.iterrows():
                ist = inj_status.get(t + '|' + norm(r.player_display_name))
                if (ist and ist['level'] in ('out', 'doubt', 'risk', 'ir')) or r.player_id in RESERVE_IDS or r.player_id in GONE_IDS:
                    continue
                bm = best_milestone(r)
                if not bm:
                    continue
                p, key, thr, proj = bm
                reason, hits, n, avg, l3 = hc_reason(r, key, thr, o, t)
                hc_picks.append({'kind': 'player', 'id': r.player_id, 'name': r.player_display_name, 'pos': r.position, 'team': t, 'opp': o,
                                 'game': gm['id'], 'week': WEEK, 'kickoff': gm['kickoff'], 'key': key, 't': thr, 'p': p, 'fair': fair_odds(p),
                                 'proj': proj, 'avg': avg, 'l3': l3, 'hits': [hits, n], 'reason': reason,
                                 'label': f"{r.player_display_name} {thr}+ {STAT_WORD[key]}",
                                 'inj': ({'level': ist['level'], 'outlook': ist['outlook']} if ist else None)})
    hc_picks.sort(key=lambda x: -x['p'])
    per_game, kept = {}, []
    for x in hc_picks:
        if per_game.get(x['game'], 0) >= 3:
            continue
        per_game[x['game']] = per_game.get(x['game'], 0) + 1; kept.append(x)
    hc_picks = kept[:12]
    # past weeks this season, picked the same way from what was known before each game
    fin = feat[feat.game_id.isin(set(done.game_id)) & (feat.n_prior >= 3)]
    hist_p = []
    for _, r in fin.iterrows():
        bm = best_milestone(r)
        if bm:
            p, key, thr, proj = bm
            actual = r[STAT_COL[key]]
            hist_p.append({'kind': 'player', 'week': int(r.week), 'game': r.game_id, 'name': r.player_display_name, 'team': r.team,
                           'label': f"{r.player_display_name} {thr}+ {STAT_WORD[key]}", 'p': p, 'actual': float(actual),
                           'result': 'W' if actual >= thr else 'L'})
    hist_p.sort(key=lambda x: -x['p'])
    wk_count = {}
    for x in hist_p:
        if wk_count.get(x['week'], 0) < 12:
            wk_count[x['week']] = wk_count.get(x['week'], 0) + 1; hc_hist.append(x)
# heavy favorites the model and the market both like, and underdog teaser legs
for gm in games:
    if gm['final']:
        continue
    m_ = gm['model']; mk = m_['mkt_wp_home']
    for t, o, mp, kp, ml in ((gm['home'], gm['away'], m_['wp_home'], mk, gm['ml_home']), (gm['away'], gm['home'], 1 - m_['wp_home'], None if mk is None else 1 - mk, gm['ml_away'])):
        if kp is not None and mp >= 0.75 and kp >= 0.75:
            rt_, ro_ = teams[t]['ranks'].get('pd_g'), teams[o]['ranks'].get('pd_g')
            qb_o = gm['qb_change']['home' if o == gm['home'] else 'away']
            reason = f"The model gives the {teams[t]['nick']} {mp:.0%} and the betting market {kp:.0%}."
            if rt_ and ro_:
                reason += f" They rank {ordinal(rt_)} in point differential; the {teams[o]['nick']} rank {ordinal(ro_)}."
            if qb_o:
                reason += f" The {teams[o]['nick']} start {qb_o['starter']} in place of {qb_o['usual']}."
            hc_picks.append({'kind': 'ml', 'team': t, 'opp': o, 'game': gm['id'], 'week': WEEK, 'kickoff': gm['kickoff'], 'p': kp, 'model_p': mp,
                             'odds': ml, 'fair': fair_odds(kp), 'reason': reason, 'label': f"{teams[t]['city']} {teams[t]['nick']} to win"})
    for x in gm.get('teaser') or []:
        if x['kind'] != 'dog':
            continue
        o = gm['home'] if x['team'] == gm['away'] else gm['away']
        mm_t = m_['margin'] if x['team'] == gm['home'] else -m_['margin']
        view = (f"The model has the {teams[x['team']]['nick']} winning by {mm_t:.1f}." if mm_t > 0 else
                f"The model has the {teams[x['team']]['nick']} losing by {abs(mm_t):.1f}, inside the teased number." if -mm_t < x['to'] else
                f"The model has the {teams[x['team']]['nick']} losing by {abs(mm_t):.1f}.")
        reason = (f"Teasing the {teams[x['team']]['nick']} from {x['from']:+g} to {x['to']:+g} covers a loss by a field goal or a touchdown. "
                  f"Since 2018, +1.5 to +2.5 underdogs teased six points won {x['rate']:.0%} of legs"
                  f"{' when the total was 49 or less' if (gm['total'] or 99) <= 49 else ''}. {view}")
        hc_picks.append({'kind': 'teaser', 'team': x['team'], 'opp': o, 'game': gm['id'], 'week': WEEK, 'kickoff': gm['kickoff'],
                         'p': x['rate'], 'from': x['from'], 'to': x['to'], 'fair': fair_odds(x['rate']), 'reason': reason,
                         'label': f"{teams[x['team']]['nick']} {x['to']:+g} in a teaser (from {x['from']:+g})"})
for _, g in done.iterrows():
    if g.game_id not in PRE_MM or pd.isna(g.spread_line):
        continue
    ih, ia = am_prob(g.home_moneyline), am_prob(g.away_moneyline)
    if ih and ia:
        wp_h = ncdf(PRE_MM[g.game_id] / RESID); nv = ih / (ih + ia)
        for t, mp, kp, won in ((g.home_team, wp_h, nv, g.home_score > g.away_score), (g.away_team, 1 - wp_h, 1 - nv, g.away_score > g.home_score)):
            if mp >= 0.75 and kp >= 0.75:
                hc_hist.append({'kind': 'ml', 'week': int(g.week), 'game': g.game_id, 'team': t, 'label': f"{teams[t]['nick']} to win",
                                'p': kp, 'result': 'W' if won else 'L'})
    for t, ln in ((g.home_team, -g.spread_line), (g.away_team, g.spread_line)):
        if 1.5 <= ln <= 2.5:
            mg = (g.home_score - g.away_score) * (1 if t == g.home_team else -1)
            hc_hist.append({'kind': 'teaser', 'week': int(g.week), 'game': g.game_id, 'team': t, 'label': f"{teams[t]['nick']} {ln + 6:+g} (teased)",
                            'p': SR['teaser']['dog_leg'], 'result': 'W' if mg + ln + 6 > 0 else 'L'})
hc_hist.sort(key=lambda x: (-x['week'], x['kind'], -x['p']))
high_chance = {'picks': hc_picks, 'history': hc_hist, 'research': HCR, 'p_min': PD['p_min']}
print('high-chance picks:', len(hc_picks), 'history:', len(hc_hist))

# ------------------------------------------------------------------ long shots: touchdowns and big games at plus money
LSM = json.load(open(os.path.join(HERE, 'static', 'longshot_model.json')))
LSR = json.load(open(os.path.join(HERE, 'static', 'longshot_research.json')))
LS_RULES, LS_CAL, GTD = LSM['rules'], LSM['calibration'], LSM['game_td']
LS_GROUP = {'atd': 'atd', 'ftd': 'ftd', 'td2': 'td2', 'rec100': 'yds100', 'rush100': 'yds100', 'pass300': 'pass300'}
LS_PICK = {'atd': ('any_td', None), 'ftd': ('first_td', None), 'td2': ('td2', None), 'rec100': ('rec_yds', 99.5),
           'rush100': ('rush_yds', 99.5), 'pass300': ('pass_yds', 299.5)}
LS_WORD = {'atd': 'anytime TD', 'ftd': 'first TD', 'td2': '2+ TDs', 'rec100': '100+ receiving yards', 'rush100': '100+ rushing yards',
           'pass300': '300+ passing yards'}
_ftd = pbp_agg.first_tds(f'{RAW}/pbp_{SEASON}.csv.gz') if have_pbp.get(SEASON) else pd.DataFrame(columns=['game_id', 'first_td', 'first_td_name', 'first_td_team'])
_ftd = _ftd[_ftd.game_id.isin(set(done.game_id))]          # only games that are over
FIRST_TD = {r.game_id: (r.first_td, (FULLNAME.get(r.first_td) or r.first_td_name) if r.first_td else '', r.first_td_team) for r in _ftd.itertuples()}


def nz(v):
    return 0.0 if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v)


def ls_cal(key, p):
    """Rescaling chosen in research because it made held-out seasons more accurate ('none', 'linear' or 'curved')."""
    c = LS_CAL.get(key)
    if p is None or not c or c['kind'] == 'none':
        return p
    p_ = min(max(p, 1e-4), 1 - 1e-4); L = math.log(p_ / (1 - p_)); k = c['coef']
    if c['kind'] == 'linear':
        z = k[0] + k[1] * L
    else:
        if k[2] < 0:
            L = min(L, -k[1] / (2 * k[2]))
        z = k[0] + k[1] * L + k[2] * L * L
    return 1 / (1 + math.exp(-z))


def ls_td_eligible(r):
    if nz(r.n_prior) < 3 or r.position not in ('QB', 'RB', 'WR', 'TE'):
        return False
    if r.position == 'QB':
        return nz(r.pg_attempts) >= 20
    return nz(r.pg_carries) >= 3 or nz(r.pg_targets) >= 2.5


def atd_chance(r):
    m = LSM['atd']; z = []
    for f in m['feats']:
        if f.startswith('is_'):
            v = 1.0 if r.position == f[3:].upper() else 0.0
        elif f in ('avg_carry_share', 'avg_target_share'):
            v = nz(r[f])
        else:
            v = r[f]
            if v is None or not np.isfinite(v):
                return None
        z.append((v - m['mu'][f]) / m['sd'][f])
    return 1 / (1 + math.exp(-(float(np.dot(z, m['coef'])) + m['intercept'])))


def game_tds(total):
    return max(2.0, GTD['slope'] * (total if total else 44.0) + GTD['intercept'])


def ls_probs(r, total):
    """Chances for one player in one game: anytime TD, 2+ TDs, first TD scorer, and 100/300-yard games where he qualifies."""
    out = {}
    if ls_td_eligible(r):
        p1 = ls_cal('atd', atd_chance(r))
        if p1 is not None:
            lam = -math.log(1 - min(p1, 0.97)); lg = game_tds(total)
            out['atd'] = p1
            out['td2'] = ls_cal('td2', 1 - math.exp(-lam) * (1 + lam))
            out['ftd'] = ls_cal('ftd', lam / lg * (1 - math.exp(-lg)))
    row = r.to_dict()
    for key, mk, t, ck in (('rec_yds', 'rec100', 100, 'rec_yds_100'), ('rush_yds', 'rush100', 100, 'rush_yds_100'), ('pass_yds', 'pass300', 300, 'pass_yds_300')):
        if hc_eligible(r, key):
            pj = project(row, key)
            if pj is not None:
                out[mk] = ls_cal(ck, chance(key, pj, t)); out['proj_' + mk] = pj
    return out


def ls_select(cands):
    """Each week: per market, the likeliest plays inside the long-shot window, capped per game."""
    out = []
    for grp, rule in LS_RULES.items():
        pool = sorted([c for c in cands if LS_GROUP[c['market']] == grp and rule['lo'] <= c['p'] < rule['hi']], key=lambda c: -c['p'])
        n_game, n_week = {}, {}
        for c in pool:
            kg, kw = (c['week'], c['game']), c['week']
            if n_game.get(kg, 0) >= rule['per_game'] or n_week.get(kw, 0) >= rule['top']:
                continue
            n_game[kg] = n_game.get(kg, 0) + 1; n_week[kw] = n_week.get(kw, 0) + 1
            out.append(c)
    return out


# season-to-date facts used in the write-ups
_p26s = p26.sort_values('week').assign(td=lambda x: x.rushing_tds.fillna(0) + x.receiving_tds.fillna(0)) if len(p26) else pd.DataFrame(columns=['player_id', 'team', 'week', 'td'])
LOGS = {pid: d_ for pid, d_ in _p26s.groupby('player_id')} if len(p26) else {}
TEAM_TDS = _p26s.groupby('team').td.sum().to_dict() if len(p26) else {}
dvp_td = {}
if len(p26):
    _tpg = _p26s.groupby(['opponent_team', 'position', 'week']).td.sum().reset_index().groupby(['opponent_team', 'position']).td.mean().reset_index()
    for pos_ in ('QB', 'RB', 'WR', 'TE'):
        s_ = _tpg[_tpg.position == pos_].set_index('opponent_team').td
        rk_ = s_.rank(ascending=False, method='min')
        for tm_ in s_.index:
            dvp_td[(tm_, pos_)] = (int(rk_[tm_]), float(s_[tm_]), int((rk_ == rk_[tm_]).sum()))
_gteams = S.set_index('game_id')[['home_team', 'away_team']].to_dict('index')
first_by_team, games_by_team, first_by_player = {}, {}, {}
for gid_, (fid_, _, fteam_) in FIRST_TD.items():
    for tm_ in (_gteams.get(gid_) or {}).values():
        games_by_team[tm_] = games_by_team.get(tm_, 0) + 1
        first_by_team[tm_] = first_by_team.get(tm_, 0) + (1 if fteam_ == tm_ else 0)
    if fid_:
        first_by_player[fid_] = first_by_player.get(fid_, 0) + 1
TD_POS = {'QB': 'quarterbacks', 'RB': 'running backs', 'WR': 'wide receivers', 'TE': 'tight ends'}
TD_MIN = {'QB': 0.35, 'RB': 0.9, 'WR': 0.9, 'TE': 0.5}


def surname(name):
    parts = [w for w in str(name).split(' ') if w.rstrip('.') not in ('Jr', 'Sr', 'II', 'III', 'IV', 'V')]
    return ' '.join(parts[1:]) if len(parts) > 1 else str(name)


def ls_usage(r, nick):
    if r.position == 'QB':
        return f"He runs {nz(r.pg_carries):.1f} times a game, {nz(r.pg_rz_carries):.1f} of them inside the 10."
    if r.position == 'RB':
        return (f"He gets {nz(r.avg_carry_share):.0%} of the {nick}' carries and {nz(r.pg_rz_carries) + nz(r.pg_rz_targets):.1f} touches a game inside the 10."
                if nick.endswith('s') else f"He gets {nz(r.avg_carry_share):.0%} of the team's carries and {nz(r.pg_rz_carries) + nz(r.pg_rz_targets):.1f} touches a game inside the 10.")
    rz_t = nz(r.pg_rz_targets)
    return f"He's seeing {nz(r.avg_target_share):.0%} of the team's targets ({nz(r.pg_targets):.1f} a game)" + (f", {rz_t:.1f} of them inside the 10." if rz_t >= 0.3 else '.')


def ls_writeup(c, game_rank):
    r, mk, t, o = c['_r'], c['market'], c['team'], c['opp']
    sur, nick, onick = surname(r.player_display_name), TEAMS[t][1], TEAMS[o][1] if o in TEAMS else o
    lg = LOGS.get(r.player_id)
    tds = lg.td.astype(int).tolist() if lg is not None else []
    n, k, tot = len(tds), sum(1 for x in tds if x > 0), int(sum(tds))
    chips, extra = [], []
    itt = r.implied_tt if r.implied_tt is not None and np.isfinite(r.implied_tt) else None
    dv = dvp_td.get((o, r.position))
    dv_txt = None
    if dv and dv[0] <= 6 and dv[1] >= TD_MIN.get(r.position, 9):
        dv_txt = (f"The {onick} have allowed {dv[1]:.1f} touchdowns a game to {TD_POS[r.position]}, "
                  f"{'tied for ' if dv[2] > 1 else ''}{'the ' if dv[0] == 1 else 'the ' + ordinal(dv[0]) + '-'}most in the league.")
    if mk in ('atd', 'td2', 'ftd'):
        chips.append(f"TD in {k} of {n}")
        rz = nz(r.pg_rz_carries) + nz(r.pg_rz_targets)
        chips.append(f"{rz:.1f} touches inside the 10 per game")
        chips.append(f"Carry share {nz(r.avg_carry_share):.0%}" if r.position == 'RB' else (f"{nz(r.pg_carries):.1f} runs per game" if r.position == 'QB' else f"Target share {nz(r.avg_target_share):.0%}"))
        if itt:
            chips.append(f"Team total {itt:.1f}")
        if mk == 'atd':
            s1 = (f"{sur} has scored in {k} of {n} games this season ({tot} total)." if k else
                  f"{sur} is still looking for his first touchdown after {n} games.")
            if c['p'] - k / max(n, 1) >= 0.10:
                extra.append("His usage points to more touchdowns than he's scored so far.")
        elif mk == 'td2':
            m2 = sum(1 for x in tds if x >= 2)
            chips.insert(1, f"Multi-TD games {m2}")
            s1 = (f"{sur} has {m2} multi-touchdown game{'s' if m2 != 1 else ''} and has scored in {k} of {n}." if m2 else
                  f"{sur} has scored in {k} of {n} games this season ({tot} total).")
        else:
            team_td = int(TEAM_TDS.get(t, 0)); f1 = first_by_player.get(r.player_id, 0)
            s1 = (f"{sur} has scored {tot} of the {nick}' {team_td} offensive touchdowns." if nick.endswith('s') else
                  f"{sur} has scored {tot} of the team's {team_td} offensive touchdowns.") if team_td else f"{sur} has scored in {k} of {n} games."
            lgt = game_tds(c['total'])
            s1 += (f" The {c['total']:g}-point total points to about {lgt:.0f} touchdowns in this game" if c['total'] else f" Expect about {lgt:.0f} touchdowns in this game") + \
                  (", and the model rates him the likeliest to score first." if game_rank == 1 else '.')
            if f1:
                chips.insert(1, f"First TDs this season {f1}")
                extra.append(f"He's scored the game's first touchdown {f1} time{'s' if f1 != 1 else ''} this season.")
            gb = games_by_team.get(t, 0)
            if gb >= 3:
                extra.append(f"The {nick} have scored first in {first_by_team.get(t, 0)} of {gb} games.")
        s2 = ls_usage(r, nick)
        if itt and itt >= 24.5:
            extra.append(f"The betting line projects the {nick} for {itt:.1f} points.")
        if dv_txt:
            extra.append(dv_txt)
        tr = trend_by_player.get(r.player_id)
        if tr and tr['metric'] in ('targets', 'target_share', 'carries', 'snap'):
            extra.append(f"His {tr['label'].lower()} {'has' if tr['label'].lower().endswith('share') else 'have'} been up {tr['weeks']} straight weeks.")
        return ' '.join([s1, s2] + extra[:1 if mk == 'ftd' else 2]), chips
    # yardage milestones
    key = {'rec100': 'rec_yds', 'rush100': 'rush_yds', 'pass300': 'pass_yds'}[mk]
    thr = 300 if mk == 'pass300' else 100
    vals = lg[STAT_COL[key]].fillna(0).tolist() if lg is not None else []
    hits = sum(1 for v in vals if v >= thr); avg = float(np.mean(vals)) if vals else 0.0
    l3 = float(np.mean(vals[-3:])) if len(vals) >= 3 else None
    word = STAT_WORD[key]
    if hits:
        s1 = (f"{sur} has thrown for {thr}+ in {hits} of {len(vals)} games, averaging {avg:.0f}" if key == 'pass_yds' else
              f"{sur} has topped {thr} {word} in {hits} of {len(vals)} games, averaging {avg:.0f}")
    else:
        s1 = (f"{sur} hasn't thrown for {thr} yet in {len(vals)} games but is averaging {avg:.0f}" if key == 'pass_yds' else
              f"{sur} hasn't reached {thr} {word} yet in {len(vals)} games but is averaging {avg:.0f}")
    if l3 is not None and avg and abs(l3 - avg) / max(avg, 1) >= 0.08:
        s1 += f" ({l3:.0f} over his last 3)"
    s1 += '.'
    if key == 'pass_yds':
        s2 = f"He's throwing {nz(r.pg_attempts):.0f} passes a game."
        sp_ = r.team_spread if r.team_spread is not None and np.isfinite(r.team_spread) else None
        if sp_ is not None and sp_ <= -3:
            extra.append(f"The {nick} are {abs(sp_):g}-point underdogs, and teams that trail throw more.")
    elif key == 'rush_yds':
        s2 = f"He gets {nz(r.avg_carry_share):.0%} of the team's carries ({nz(r.pg_carries):.1f} a game)."
    else:
        s2 = f"He's seeing {nz(r.pg_targets):.1f} targets a game ({nz(r.avg_target_share):.0%} of the team's)."
    rk = dvp.get((o, r.position, KEYCOL[key]))
    if rk is not None and rk <= 10:
        extra.append(f"The {onick} allow the {'' if rk == 1 else ordinal(rk) + '-'}most {word} to {POS_WORD[r.position]}.")
    if itt and itt >= 25.5:
        extra.append(f"The betting line projects the {nick} for {itt:.1f} points.")
    chips = [f"Projection {c['proj']:.0f}", f"Avg {avg:.0f}"] + ([f"Last 3 {l3:.0f}"] if l3 is not None else []) + [f"{thr}+ in {hits} of {len(vals)}"]
    return ' '.join([s1, s2] + extra[:1]), chips


ls_picks, ls_hist = [], []
if 'feat' in globals() and len(p26):
    cands = []
    for gm in games:
        if gm['final'] or gm.get('live'):
            continue
        for t, o in ((gm['away'], gm['home']), (gm['home'], gm['away'])):
            for _, r in cur[(cur.game_id == gm['id']) & (cur.team == t)].iterrows():
                ist = inj_status.get(t + '|' + norm(r.player_display_name))
                if (ist and ist['level'] in ('out', 'doubt', 'risk', 'ir')) or r.player_id in RESERVE_IDS or r.player_id in GONE_IDS:
                    continue
                pr = ls_probs(r, gm['total'])
                for mk in LS_GROUP:
                    if pr.get(mk) is None or not np.isfinite(pr[mk]):
                        continue
                    cands.append({'market': mk, 'p': float(pr[mk]), 'week': WEEK, 'game': gm['id'], 'team': t, 'opp': o, 'total': gm['total'],
                                  'kickoff': gm['kickoff'], 'proj': pr.get('proj_' + mk), '_r': r,
                                  'inj': ({'level': ist['level'], 'outlook': ist['outlook']} if ist else None)})
    ftd_sum = {}
    for c in cands:
        if c['market'] == 'ftd':
            ftd_sum[c['game']] = ftd_sum.get(c['game'], 0) + c['p']
    if ftd_sum:
        print('first-TD chances summed per game (players modeled): %.2f-%.2f' % (min(ftd_sum.values()), max(ftd_sum.values())))
    ftd_rank = {}
    for gid_ in {c['game'] for c in cands}:
        for i_, c in enumerate(sorted([c for c in cands if c['game'] == gid_ and c['market'] == 'ftd'], key=lambda c: -c['p'])):
            ftd_rank[(gid_, c['_r'].player_id)] = i_ + 1
    for c in ls_select(cands):
        r = c['_r']
        reason, chips = ls_writeup(c, ftd_rank.get((c['game'], r.player_id)))
        ptype, line = LS_PICK[c['market']]
        ls_picks.append({'market': c['market'], 'group': LS_GROUP[c['market']], 'id': r.player_id, 'name': r.player_display_name, 'pos': r.position,
                         'team': c['team'], 'opp': c['opp'], 'game': c['game'], 'week': WEEK, 'kickoff': c['kickoff'], 'p': c['p'],
                         'fair': fair_odds(c['p']), 'label': f"{r.player_display_name} {LS_WORD[c['market']]}", 'reason': reason, 'chips': chips,
                         'type': ptype, 'line': line, 'inj': c['inj']})
    # past weeks this season, chosen the same way from what was known before each game
    tot_by_game = dict(zip(S.game_id, S.total_line))
    hc_ = []
    for _, r in feat[feat.game_id.isin(set(done.game_id)) & (feat.n_prior >= 3)].iterrows():
        tl = tot_by_game.get(r.game_id)
        pr = ls_probs(r, None if tl is None or pd.isna(tl) else float(tl))
        tdn = int(nz(r.rushing_tds) + nz(r.receiving_tds))
        for mk in LS_GROUP:
            if pr.get(mk) is None or not np.isfinite(pr[mk]):
                continue
            if mk == 'ftd':
                if r.game_id not in FIRST_TD:
                    continue
                fid_, fname_, _ = FIRST_TD[r.game_id]
                res_, act = ('W' if fid_ == r.player_id else 'L'), (f'first TD: {fname_}' if fid_ else 'no touchdown in the game')
            elif mk in ('atd', 'td2'):
                res_ = 'W' if tdn >= (1 if mk == 'atd' else 2) else 'L'
                act = f"{tdn} TD{'s' if tdn != 1 else ''}" if tdn else 'no TD'
            else:
                col_ = {'rec100': 'receiving_yards', 'rush100': 'rushing_yards', 'pass300': 'passing_yards'}[mk]
                v_ = nz(r[col_]); res_ = 'W' if v_ >= (300 if mk == 'pass300' else 100) else 'L'; act = f"{v_:.0f} yards"
            hc_.append({'market': mk, 'p': float(pr[mk]), 'week': int(r.week), 'game': r.game_id, 'name': r.player_display_name, 'team': r.team,
                        'label': f"{r.player_display_name} {LS_WORD[mk]}", 'result': res_, 'actual': act})
    ls_hist = sorted(ls_select(hc_), key=lambda x: (-x['week'], list(LS_GROUP).index(x['market']), -x['p']))
    for h in ls_hist:
        h['group'] = LS_GROUP[h['market']]
LSB = LSR['backtest']
long_shots = {'picks': ls_picks, 'history': ls_hist, 'rules': LS_RULES,
              'research': {'backtest': LSB, 'seasons': LSR['test_seasons'], 'predictors': LSR['atd_predictors'][:6],
                           'calibration': {k: {'kind': v['kind'], 'final': v['final']} for k, v in LSR['calibration'].items()},
                           'atd_by_position': LSR.get('atd_by_position')}}
print('long shots:', len(ls_picks), {g_: sum(1 for x in ls_picks if x['group'] == g_) for g_ in LS_RULES}, 'history:', len(ls_hist))

# ------------------------------------------------------------------ grading data
grade_players = {}
for pid, d in p26.groupby('player_id'):
    last = d.sort_values('week').iloc[-1]
    if last.position not in ('QB', 'RB', 'WR', 'TE', 'FB'):
        continue
    grade_players[pid] = {'n': last.player_display_name, 'p': last.position, 't': last.team,
                          'w': {int(r.week): [int(r.completions or 0), int(r.attempts or 0), int(r.passing_yards or 0), int(r.passing_tds or 0),
                                              int(r.passing_interceptions or 0), int(r.carries or 0), int(r.rushing_yards or 0),
                                              int(r.rushing_tds or 0), int(r.receptions or 0), int(r.targets or 0),
                                              int(r.receiving_yards or 0), int(r.receiving_tds or 0)] for _, r in d.iterrows()}}
results = {g.game_id: {'wk': int(g.week), 'a': g.away_team, 'h': g.home_team,
                       'as': None if pd.isna(g.away_score) else int(g.away_score), 'hs': None if pd.isna(g.home_score) else int(g.home_score),
                       'sp': None if pd.isna(g.spread_line) else float(g.spread_line), 'tl': None if pd.isna(g.total_line) else float(g.total_line),
                       'mlh': None if pd.isna(g.home_moneyline) else int(g.home_moneyline), 'mla': None if pd.isna(g.away_moneyline) else int(g.away_moneyline),
                       'k': kickoff_iso(g)} for _, g in S.iterrows()}
for gid_, (fid_, fname_, _) in FIRST_TD.items():
    if gid_ in results:
        results[gid_]['ftd'] = fid_; results[gid_]['ftdn'] = fname_
last_stats_date = (str(S[S.game_id.isin(p26.game_id)].gameday.max()) if len(p26) else None)

research = {'team': R['research'], 'market_r': R['market_r'], 'market_su_acc': R['market_su_acc'], 'n_games': R['n_games'],
            'margin_coef': R['margin_coef'], 'ats_backtest': R['ats_backtest'], 'ou_backtest': R['ou_backtest'], 'ml_backtest': R['ml_backtest'],
            'player': {k: {'predictors': v['predictors'], 'mae_model': v['mae_model'], 'mae_season_avg': v['mae_season_avg'],
                           'r_model': v['r_model'], 'r_season_avg': v['r_season_avg'], 'n_test': v['n_test']} for k, v in PR['props'].items()},
            'trend_carry': {'team': TR['team'], 'player': TR['player']},
            'spread': SR, 'model_v2': {'walk_forward': M2['walk_forward'], 'favorites_su': M2['favorites_su']}}
STAT_LABEL = {'pd_g': 'Point diff / game', 'off_epa': 'EPA per play', 'def_epa': 'EPA per play allowed'}

data = {'meta': {'season': SEASON, 'week': WEEK, 'asof': NOW.isoformat(timespec='seconds'),
                 'stats_through': last_stats_date, 'espn_injuries': bool(esp), 'espn_scoreboard': bool(board),
                 'sources': ['nflverse play-by-play, player stats, schedules and lines', 'NFL Next Gen Stats (via nflverse)',
                             'Pro Football Reference snap counts (via nflverse)', 'NFL official injury report (via nflverse)',
                             'ESPN injury status and expected return dates', 'ESPN scoreboard for live and final scores'],
                 'resid_sd': RESID, 'qb_mean': QB_MEAN},
        'teams': teams, 'games': games, 'injuries': injuries, 'stat_labels': STAT_LABEL,
        'trends': {'league': league_trends, 'league_weekly': league_weekly, 'team': team_trends, 'player': player_trends[:80]},
        'model_picks': model_picks, 'prop_bins': BINS, 'prop_dist': PD['dists'], 'research': research, 'high_chance': high_chance,
        'long_shots': long_shots,
        'grade': {'players': grade_players, 'games': results}}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
tmp = OUT + '.tmp'
with open(tmp, 'w') as f:
    json.dump(clean(data), f, separators=(',', ':'))
os.replace(tmp, OUT)
print('wrote', OUT, round(os.path.getsize(OUT) / 1024), 'KB')
