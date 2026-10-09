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
have_pbp = {y: fetch(f'{BASE}/pbp/play_by_play_{y}.csv.gz', f'{RAW}/pbp_{y}.csv.gz', required=(y < SEASON)) for y in (SEASON - 1, SEASON)}
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
params = R['params']

# ------------------------------------------------------------------ team games and metrics
tgs, rzs = [], []
for y in (SEASON - 1, SEASON):
    if have_pbp[y]:
        tg_y, rz_y = pbp_agg.season_frames(y, f'{RAW}/pbp_{y}.csv.gz')
        tgs.append(tg_y); rzs.append(rz_y)
tg_all = pd.concat(tgs, ignore_index=True)
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


def model_margin(h, a, neutral=False, src=None):
    src = src or POST
    z = np.array([((src[f][h] - src[f][a]) - MU[f]) / SD[f] for f in FEATS])
    return float(z @ coef + (0 if neutral else const))


def model_total(h, a, roof, src=None):
    src = src or POST
    ppd_sum = src['o_ppd'][h] + src['d_ppd'][a] + src['o_ppd'][a] + src['d_ppd'][h]
    pace = (src['o_plays'][h] + src['o_plays'][a] + src['d_plays'][h] + src['d_plays'][a]) / 2
    dome = 1.0 if roof in ('dome', 'closed') else 0.0
    return float(np.array([ppd_sum, pace, dome, 1.0]) @ TBETA)


for t in TEAMS:
    z = np.array([POST[f][t] / SD[f] for f in FEATS])
    teams[t]['power'] = float(z @ coef)

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
    srcg = (pregame_src(g.game_id, h, a) if g.final else None) or POST
    mm = model_margin(h, a, neutral, srcg); wp = ncdf(mm / RESID); mt = model_total(h, a, g.roof, srcg)
    ih, ia = am_prob(g.home_moneyline), am_prob(g.away_moneyline)
    nv_h = ih / (ih + ia) if ih and ia else None
    spread = float(g.spread_line) if pd.notna(g.spread_line) else None
    total = float(g.total_line) if pd.notna(g.total_line) else None
    s_edge = mm - spread if spread is not None else None
    t_edge = mt - total if total is not None else None
    qbc = {'home': qb_change(h, g.home_qb_name if pd.notna(g.home_qb_name) else None),
           'away': qb_change(a, g.away_qb_name if pd.notna(g.away_qb_name) else None)}
    pick_ats = None
    if s_edge is not None and abs(s_edge) >= 2.5 and not (qbc['home'] or qbc['away']):
        pick_ats = h if s_edge > 0 else a
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
        'mismatches': mism, 'qb_change': qbc,
        'rest': {'home': None if pd.isna(g.home_rest) else int(g.home_rest), 'away': None if pd.isna(g.away_rest) else int(g.away_rest)}})

# ------------------------------------------------------------------ model pick record (pre-game info only)
model_picks = []
for _, g in done.sort_values(['week', 'gameday', 'gametime']).iterrows():
    gid, h, a = g.game_id, g.home_team, g.away_team
    src = pregame_src(gid, h, a)
    if src is None:
        if int(g.week) != WEEK:
            continue
        src = POST     # final per the scoreboard but not in play-by-play yet, so current ratings are still pre-game
    mm = model_margin(h, a, bool(g.neutral), src)
    margin = g.home_score - g.away_score
    base = {'week': int(g.week), 'game': gid, 'away': a, 'home': h, 'score': f"{a} {int(g.away_score)} - {h} {int(g.home_score)}"}
    su = h if mm > 0 else a
    model_picks.append({**base, 'type': 'Winner', 'pick': su, 'detail': f"{su} to win (model {abs(mm):.1f})",
                        'result': 'P' if margin == 0 else ('W' if (margin > 0) == (su == h) else 'L')})
    if pd.isna(g.spread_line):
        continue
    edge = mm - g.spread_line
    if abs(edge) >= 2.5 and not (qb_change_at(h, g.home_qb_name, g.week) or qb_change_at(a, g.away_qb_name, g.week)):
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
                       'k': kickoff_iso(g)} for _, g in S.iterrows()}
last_stats_date = (str(S[S.game_id.isin(p26.game_id)].gameday.max()) if len(p26) else None)

research = {'team': R['research'], 'market_r': R['market_r'], 'market_su_acc': R['market_su_acc'], 'n_games': R['n_games'],
            'margin_coef': R['margin_coef'], 'ats_backtest': R['ats_backtest'], 'ou_backtest': R['ou_backtest'], 'ml_backtest': R['ml_backtest'],
            'player': {k: {'predictors': v['predictors'], 'mae_model': v['mae_model'], 'mae_season_avg': v['mae_season_avg'],
                           'r_model': v['r_model'], 'r_season_avg': v['r_season_avg'], 'n_test': v['n_test']} for k, v in PR['props'].items()},
            'trend_carry': {'team': TR['team'], 'player': TR['player']}}
STAT_LABEL = {'pd_g': 'Point diff / game', 'off_epa': 'EPA per play', 'def_epa': 'EPA per play allowed'}

data = {'meta': {'season': SEASON, 'week': WEEK, 'asof': NOW.isoformat(timespec='seconds'),
                 'stats_through': last_stats_date, 'espn_injuries': bool(esp), 'espn_scoreboard': bool(board),
                 'sources': ['nflverse play-by-play, player stats, schedules and lines', 'NFL Next Gen Stats (via nflverse)',
                             'Pro Football Reference snap counts (via nflverse)', 'NFL official injury report (via nflverse)',
                             'ESPN injury status and expected return dates', 'ESPN scoreboard for live and final scores'],
                 'resid_sd': RESID},
        'teams': teams, 'games': games, 'injuries': injuries, 'stat_labels': STAT_LABEL,
        'trends': {'league': league_trends, 'league_weekly': league_weekly, 'team': team_trends, 'player': player_trends[:80]},
        'model_picks': model_picks, 'prop_bins': BINS, 'research': research,
        'grade': {'players': grade_players, 'games': results}}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
tmp = OUT + '.tmp'
with open(tmp, 'w') as f:
    json.dump(clean(data), f, separators=(',', ':'))
os.replace(tmp, OUT)
print('wrote', OUT, round(os.path.getsize(OUT) / 1024), 'KB')
