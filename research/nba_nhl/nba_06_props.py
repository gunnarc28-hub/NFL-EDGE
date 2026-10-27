"""NBA player projections (walk-forward) and how their over/under chances do against real book lines (2023-24 on)."""
import pandas as pd, numpy as np, json, sys
WORK = 'work'
P = pd.read_pickle(f'{WORK}/nba_player_box.pkl')
G = pd.read_pickle(f'{WORK}/nba_games.pkl')[['gid', 'line', 'total', 'home', 'away', 'season']]
tb = pd.read_pickle(f'{WORK}/nba_team_box.pkl')
STATS = {'pts': 'points', 'reb': 'rebounds', 'ast': 'assists', 'fg3m': 'three_point_field_goals_made', 'stl': 'steals', 'blk': 'blocks', 'tov': 'turnovers'}
P = P.sort_values(['t', 'game_id']).reset_index(drop=True)
P['pid'] = P.athlete_id
for k, c in STATS.items(): P[k] = P[c].fillna(0)
pl = P[P.played].copy()
# ---------------- player form: minutes and per-minute rates from games before this one
HL_MIN, HL_RATE = 5, 18
grp = pl.groupby('pid', sort=False)
pl['n_prev'] = grp.cumcount()
pl['min_ew'] = grp['min'].transform(lambda s: s.ewm(halflife=HL_MIN, min_periods=1).mean().shift())
pl['min_l10'] = grp['min'].transform(lambda s: s.rolling(10, min_periods=1).mean().shift())
pl['min_ewr'] = grp['min'].transform(lambda s: s.ewm(halflife=HL_RATE, min_periods=1).mean().shift())
for k in STATS:
    pl[k + '_ewr'] = grp[k].transform(lambda s: s.ewm(halflife=HL_RATE, min_periods=1).mean().shift())
    pl[k + '_rate'] = pl[k + '_ewr'] / pl.min_ewr.clip(lower=1)
pl['started_prev'] = grp['starter'].transform(lambda s: s.astype(float).ewm(halflife=3, min_periods=1).mean().shift())
# league per-minute priors by position (shrink rookies and short samples)
pos = pl.athlete_position_abbreviation.fillna('F').str[0].replace({'P': 'G', 'S': 'G'})
pl['pos1'] = pos
for k in STATS:
    lg = (pl.groupby(['season', 'pos1'])[k].transform('sum') / pl.groupby(['season', 'pos1'])['min'].transform('sum'))
    w = (pl.min_ewr.fillna(0) * np.minimum(pl.n_prev, 30)).clip(0, None)       # minutes of evidence (approx.)
    pl[k + '_rate'] = (pl[k + '_rate'].fillna(lg) * w + lg * 150) / (w + 150)
# ---------------- opponent and pace factors (team level, from games before this one)
team_g = pl.groupby(['game_id', 'team_abbreviation', 'opponent_team_abbreviation', 't'])[list(STATS) + ['min']].sum().reset_index()
team_g = team_g.sort_values('t')
allowed = team_g.rename(columns={'team_abbreviation': 'off', 'opponent_team_abbreviation': 'def'})
for k in STATS:
    allowed[k + '_pm'] = allowed[k] / allowed['min'].clip(lower=200) * 240
ag = allowed.groupby('def', sort=False)
for k in STATS:
    allowed[k + '_allow'] = ag[k + '_pm'].transform(lambda s: s.ewm(halflife=15, min_periods=1).mean().shift())
    allowed[k + '_lg'] = allowed[k + '_pm'].ewm(halflife=400, min_periods=1).mean().shift()
opp = allowed[['game_id', 'def'] + [k + '_allow' for k in STATS] + [k + '_lg' for k in STATS]].rename(columns={'def': 'opponent_team_abbreviation'})
pl = pl.merge(opp, on=['game_id', 'opponent_team_abbreviation'], how='left')
tb2 = tb.merge(pl[['game_id', 't']].drop_duplicates('game_id'), on='game_id').sort_values('t')
tb2['pace_ew'] = tb2.groupby('team_abbreviation').poss.transform(lambda s: s.ewm(halflife=15, min_periods=1).mean().shift())
tb2['pace_lg'] = tb2.poss.ewm(halflife=400, min_periods=1).mean().shift()
pace = tb2[['game_id', 'team_abbreviation', 'pace_ew', 'pace_lg']]
pl = pl.merge(pace, on=['game_id', 'team_abbreviation'], how='left').merge(pace.rename(columns={'team_abbreviation': 'opponent_team_abbreviation', 'pace_ew': 'opp_pace', 'pace_lg': 'x'}).drop(columns='x'),
                                                                          on=['game_id', 'opponent_team_abbreviation'], how='left')
pl['pace_f'] = ((pl.pace_ew + pl.opp_pace) / 2 / pl.pace_lg).fillna(1)
# game context: spread (blowout risk), rest
pl = pl.merge(G[['gid', 'line', 'home', 'away']].rename(columns={'gid': 'game_id'}), on='game_id', how='left')
pl['team_line'] = np.where(pl.team_abbreviation == pl.home, pl.line, -pl.line)
pl['day_et'] = pl.t.dt.tz_convert('America/New_York').dt.tz_localize(None).dt.normalize()     # calendar days: back-to-back = played yesterday
pl['last_day'] = pl.groupby('pid').day_et.shift()
pl['rest'] = (pl.day_et - pl.last_day).dt.days.clip(0, 5)
pl.to_pickle(f'{WORK}/nba_proj_base.pkl')
print('rows', len(pl))
