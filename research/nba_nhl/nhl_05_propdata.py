"""NHL prop lines (ESPN odds records) matched to NHL box scores, with sides."""
import pandas as pd, numpy as np, unicodedata, re
WORK = 'work'; RAW = 'raw'
d = pd.read_csv(f'{RAW}/props/nhl_props.csv.gz', dtype={'side': str, 'athlete': str}); d['side'] = d.side.fillna('')
ath = pd.read_csv(f'{RAW}/props/nhl_athletes.csv', dtype={'athlete': str})
ev = pd.read_csv(f'{RAW}/odds/nhl_events.csv')
ESPN = {'NJ': 'NJD', 'SJ': 'SJS', 'TB': 'TBL', 'LA': 'LAK', 'UTAH': 'UTA'}
ev['home'] = ev.home.replace(ESPN); ev['away'] = ev.away.replace(ESPN)
ev['day'] = pd.to_datetime(ev.date, utc=True).dt.tz_convert('America/New_York').dt.date.astype(str)
G = pd.read_pickle(f'{WORK}/nhl_games_plus.pkl')
emap = ev.merge(G[['gid', 'day', 'home', 'away']], on=['day', 'home', 'away'])[['event', 'gid']]
d = d.merge(emap, on='event', how='inner')
def am(x):
    x = str(x).strip()
    if x.lower() == 'even': return 100.0
    try: return float(x.replace('+', ''))
    except ValueError: return np.nan
d['o'] = d.odds.map(am)
def key(n):
    n = unicodedata.normalize('NFKD', str(n)).encode('ascii', 'ignore').decode().lower()
    n = re.sub(r'[^a-z ]', ' ', n).split()
    return (n[0][:1] + ' ' + n[-1]) if len(n) >= 2 else ''
ath['nk'] = ath.name.map(key)
d = d.merge(ath[['athlete', 'nk', 'name', 'pos']], on='athlete', how='left')
sk = pd.read_pickle(f'{WORK}/nhl_proj.pkl')
sk['nk'] = sk.player_name.map(key)
gl = pd.read_pickle(f'{WORK}/nhl_goalie_starts.pkl'); gl['nk'] = gl.player_name.map(key)
# skater lines
OU = {'Total Points': 'points', 'Total Assists': 'assists', 'Total Shots on Goal': 'shots_on_goal', 'Total Blocked Shots': 'blocked_shots'}
o = d[d.type.isin(OU)].sort_values(['event', 'book', 'i']).copy()
o['n'] = o.groupby(['event', 'book', 'type', 'athlete', 'line']).cumcount()
um = o.side == ''
o.loc[um & (o.book == 100), 'side'] = np.where(o.loc[um & (o.book == 100), 'n'] == 0, 'over', 'under')
o = o[o.side.isin(['over', 'under'])]
K = ['event', 'gid', 'book', 'type', 'athlete', 'nk', 'line']
ov = o[o.side == 'over'].drop_duplicates(K).set_index(K); un = o[o.side == 'under'].drop_duplicates(K).set_index(K)
pr = ov[['o']].join(un[['o']].rename(columns={'o': 'o2'}), how='inner').reset_index()
pr['stat'] = pr.type.map(OU)
imp = lambda x: np.where(x < 0, -x / (-x + 100), 100 / (x + 100))
pr['p1'] = imp(pr.o) / (imp(pr.o) + imp(pr.o2))
pr['main'] = (pr.p1 - .5).abs().groupby([pr.event, pr.book, pr.type, pr.athlete]).rank(method='first') == 1
cols = ['game_id', 'nk', 'player_id', 'yr', 'goals', 'assists', 'points', 'shots_on_goal', 'blocked_shots', 'sog_p', 'g_p', 'a_p', 'p_p', 'blk_p', 'toi_p']
pr = pr.merge(sk[cols].rename(columns={'game_id': 'gid'}), on=['gid', 'nk'], how='left')
pr['actual'] = [getattr(r, r.stat) if r.player_id == r.player_id else np.nan for r in pr.itertuples()]
print('skater pairs', len(pr), 'matched', pr.player_id.notna().mean().round(3))
pr.to_pickle(f'{WORK}/nhl_prop_lines.pkl')
# one-sided yes markets: anytime goal, 2+ goals, first goal
Y = d[d.type.isin(['Anytime Goalscorer', 'To Score 2+ Goals', 'First Goalscorer'])].drop_duplicates(['event', 'type', 'athlete'])
Y = Y.merge(sk[cols].rename(columns={'game_id': 'gid'}), on=['gid', 'nk'], how='left')
print('yes-market rows', len(Y), 'matched', Y.player_id.notna().mean().round(3), Y.type.value_counts().to_dict())
Y.to_pickle(f'{WORK}/nhl_prop_yes.pkl')
# goalie saves
S = d[d.type == 'Total Saves'].sort_values(['event', 'book', 'i']).copy()
S['n'] = S.groupby(['event', 'book', 'athlete', 'line']).cumcount(); um = S.side == ''
S.loc[um & (S.book == 100), 'side'] = np.where(S.loc[um & (S.book == 100), 'n'] == 0, 'over', 'under')
K2 = ['event', 'gid', 'book', 'athlete', 'nk', 'line']
sv = S[S.side == 'over'].drop_duplicates(K2).set_index(K2)[['o']].join(S[S.side == 'under'].drop_duplicates(K2).set_index(K2)[['o']].rename(columns={'o': 'o2'}), how='inner').reset_index()
sv = sv.merge(gl[['game_id', 'nk', 'player_id', 'sv', 'sa', 'sv_pct', 'team_abbrev']].rename(columns={'game_id': 'gid'}), on=['gid', 'nk'], how='left')
print('saves pairs', len(sv), 'matched starters', sv.player_id.notna().mean().round(3))
sv.to_pickle(f'{WORK}/nhl_prop_saves.pkl')
