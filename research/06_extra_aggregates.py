"""Extra per team-game aggregates for the spread experiments:
- garbage-time-filtered efficiency (plays with win probability between 10% and 90%)
- quarterback dropback EPA by game (to build QB-specific ratings)
Writes work/gt.pkl and work/qb_games.pkl"""
import numpy as np, pandas as pd

USE = ['game_id', 'season', 'week', 'season_type', 'posteam', 'play_type', 'pass', 'rush', 'epa', 'success', 'wp', 'down',
       'two_point_attempt', 'qb_dropback', 'passer_player_id', 'rusher_player_id', 'passer_player_name', 'rusher_player_name', 'qb_scramble']
gts, qbs = [], []
for y in range(2017, 2027):
    p = pd.read_csv(f'raw/pbp_{y}.csv.gz', usecols=USE, low_memory=False)
    p = p[(p.season_type == 'REG') & p.play_type.isin(['pass', 'run']) & (p.two_point_attempt != 1) & p.epa.notna() & p.posteam.notna()].copy()
    p['is_pass'] = (p['pass'] == 1).astype(int)
    p['is_rush'] = ((p['rush'] == 1) & (p['pass'] != 1)).astype(int)
    g = p[p.wp.between(0.10, 0.90)]
    k = ['game_id', 'posteam']
    a = g.groupby(k).agg(plays_gt=('epa', 'size'), epa_gt=('epa', 'sum'), succ_gt=('success', 'sum'))
    a['pass_epa_gt'] = g[g.is_pass == 1].groupby(k).epa.sum(); a['db_gt'] = g[g.is_pass == 1].groupby(k).size()
    a['rush_epa_gt'] = g[g.is_rush == 1].groupby(k).epa.sum(); a['ru_gt'] = g[g.is_rush == 1].groupby(k).size()
    a = a.fillna(0).reset_index().rename(columns={'posteam': 'team'})
    a['season'] = y
    gts.append(a)
    d = p[p.qb_dropback == 1].copy()
    d['qb'] = d.passer_player_id.fillna(d.rusher_player_id)
    d['qb_name'] = d.passer_player_name.fillna(d.rusher_player_name)
    q = d.groupby(['game_id', 'posteam', 'qb']).agg(db=('epa', 'size'), qb_epa=('epa', 'sum'), name=('qb_name', 'first'), week=('week', 'first')).reset_index()
    q['season'] = y
    qbs.append(q)
    print(y, len(a), len(q), flush=True)
pd.concat(gts).to_pickle('work/gt.pkl')
pd.concat(qbs).to_pickle('work/qb_games.pkl')
