"""NHL player form (walk-forward): ice time, per-60 rates, shooting, opponent shot suppression and goalies."""
import pandas as pd, numpy as np
WORK = 'work'
sk = pd.read_pickle(f'{WORK}/nhl_skater_box.pkl'); gb = pd.read_pickle(f'{WORK}/nhl_goalie_box.pkl')
G = pd.read_pickle(f'{WORK}/nhl_games_plus.pkl')
G = G[['gid', 'season', 't', 'home', 'away', 'hs', 'as_', 'ml_home', 'ml_away', 'total', 'game_type', 'gk_h', 'gk_a']]
def toi(x):
    try: m, s = str(x).split(':'); return int(m) + int(s) / 60
    except Exception: return np.nan
sk = sk.merge(G[['gid', 't', 'season', 'home', 'away', 'game_type']].rename(columns={'gid': 'game_id', 'season': 'yr'}), on='game_id', how='inner')
sk['toi_m'] = sk.toi.map(toi)
sk = sk[sk.toi_m > 0].copy()
sk['opp'] = np.where(sk.team_abbrev == sk.home, sk.away, sk.home)
sk['is_home'] = (sk.team_abbrev == sk.home).astype(int)
sk['pos1'] = np.where(sk.position.astype(str).str.upper().str[0] == 'D', 'D', 'F')
for c in ['goals', 'assists', 'points', 'shots_on_goal', 'hits', 'blocked_shots', 'power_play_goals']:
    sk[c] = pd.to_numeric(sk[c], errors='coerce').fillna(0)
sk = sk.sort_values(['t', 'game_id']).reset_index(drop=True)
g = sk.groupby('player_id', sort=False)
sk['n_prev'] = g.cumcount()
sk['toi_ew'] = g.toi_m.transform(lambda s: s.ewm(halflife=5, min_periods=1).mean().shift())
sk['toi_ewr'] = g.toi_m.transform(lambda s: s.ewm(halflife=20, min_periods=1).mean().shift())
RATE = {'g': 'goals', 'a': 'assists', 'p': 'points', 'sog': 'shots_on_goal', 'hit': 'hits', 'blk': 'blocked_shots'}
for k, c in RATE.items():
    ew = g[c].transform(lambda s: s.ewm(halflife=20, min_periods=1).mean().shift())
    sk[k + '_rate'] = ew / sk.toi_ewr.clip(lower=3)              # per minute
    lg = sk.groupby(['yr', 'pos1'])[c].transform('sum') / sk.groupby(['yr', 'pos1']).toi_m.transform('sum')
    w = (sk.toi_ewr.fillna(0) * np.minimum(sk.n_prev, 40))
    sk[k + '_rate'] = (sk[k + '_rate'].fillna(lg) * w + lg * 300) / (w + 300)
# shooting %: long memory, strong shrink to position average
gs = g.goals.transform(lambda s: s.ewm(halflife=60, min_periods=1).sum().shift()) if False else g.goals.transform(lambda s: s.shift().ewm(halflife=60, min_periods=1).mean())
ss = g.shots_on_goal.transform(lambda s: s.shift().ewm(halflife=60, min_periods=1).mean())
lgsh = sk.groupby(['yr', 'pos1']).goals.transform('sum') / sk.groupby(['yr', 'pos1']).shots_on_goal.transform('sum')
nsh = ss.fillna(0) * np.minimum(sk.n_prev, 80)
sk['sh_pct'] = ((gs / ss.clip(lower=0.1)).fillna(lgsh) * nsh + lgsh * 60) / (nsh + 60)
# opponent shot suppression per team-game (shots allowed), and the opponent's starting goalie
tg = sk.groupby(['game_id', 'team_abbrev', 'opp', 't']).agg(sog=('shots_on_goal', 'sum'), blk=('blocked_shots', 'sum'), hit=('hits', 'sum')).reset_index().sort_values('t')
tg['sog_allow'] = tg.groupby('opp').sog.transform(lambda s: s.ewm(halflife=15, min_periods=1).mean().shift())
tg['sog_lg'] = tg.sog.ewm(halflife=600, min_periods=1).mean().shift()
tg['sog_for'] = tg.groupby('team_abbrev').sog.transform(lambda s: s.ewm(halflife=15, min_periods=1).mean().shift())
sk = sk.merge(tg[['game_id', 'opp', 'sog_allow', 'sog_lg']].rename(columns={'opp': 'opp_x'}), left_on=['game_id', 'opp'], right_on=['game_id', 'opp_x'], how='left').drop(columns='opp_x')
# goalies: starter's save% before the game, regressed
gb2 = gb.merge(G[['gid', 't']].rename(columns={'gid': 'game_id'}), on='game_id').sort_values('t')
gb2['sv'] = pd.to_numeric(gb2.saves, errors='coerce'); gb2['sa'] = pd.to_numeric(gb2.shots_against, errors='coerce')
gg = gb2.groupby('player_id', sort=False)
gb2['sv_ew'] = gg.sv.transform(lambda s: s.shift().ewm(halflife=40, min_periods=1).mean()); gb2['sa_ew'] = gg.sa.transform(lambda s: s.shift().ewm(halflife=40, min_periods=1).mean())
gb2['n_prev'] = gg.cumcount()
lgsv = 0.905
w = gb2.sa_ew.fillna(0) * np.minimum(gb2.n_prev, 60)
gb2['sv_pct'] = ((gb2.sv_ew / gb2.sa_ew.clip(lower=1)).fillna(lgsv) * w + lgsv * 900) / (w + 900)
gst = gb2[gb2.starter.astype(str).isin(['True', 'true', '1'])].drop_duplicates(['game_id', 'team_abbrev'])
gst[['game_id', 'team_abbrev', 'player_id', 'player_name', 'sv_pct', 'sv', 'sa', 'toi', 'n_prev', 't']].to_pickle(f'{WORK}/nhl_goalie_starts.pkl')
sk = sk.merge(gst[['game_id', 'team_abbrev', 'sv_pct']].rename(columns={'team_abbrev': 'opp', 'sv_pct': 'opp_sv'}), on=['game_id', 'opp'], how='left')
sk.to_pickle(f'{WORK}/nhl_proj_base.pkl')
print('skater rows', len(sk), sk[['toi_ew', 'sog_rate', 'sh_pct', 'sog_allow', 'opp_sv']].describe().round(3))
