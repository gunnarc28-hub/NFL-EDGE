"""Do streaks carry over? Players who beat their projection several games running, and teams covering or going over in a row."""
import pandas as pd, numpy as np, json
WORK = 'work'
out = {}
d = pd.read_pickle(f'{WORK}/nba_proj.pkl')[['pid', 't', 'season', 'pts', 'pts_proj', 'reb', 'reb_proj', 'ast', 'ast_proj', 'fg3m', 'fg3m_proj']]
d = d.sort_values(['pid', 't'])
for k in ('pts', 'reb', 'ast', 'fg3m'):
    d['beat'] = (d[k] > d[k + '_proj']).astype(int)
    g = d.groupby('pid').beat
    d['run'] = g.transform(lambda s: s.groupby((s != s.shift()).cumsum()).cumcount() + 1) * d.beat   # current run length of beats
    d['run_prev'] = d.groupby('pid').run.shift()
    res = {}
    for n in (3, 4, 5):
        x = d[(d.run_prev >= n) & (d.season >= 2018)]
        res[n] = {'n': int(len(x)), 'next_beat_rate': round(float(x.beat.mean()), 3), 'next_resid': round(float((x[k] - x[k + '_proj']).mean()), 2)}
    base = d[d.season >= 2018]
    res['all'] = {'next_beat_rate': round(float(base.beat.mean()), 3), 'next_resid': round(float((base[k] - base[k + '_proj']).mean()), 2)}
    out['nba_' + k] = res
s = pd.read_pickle(f'{WORK}/nhl_proj.pkl')[['player_id', 't', 'yr', 'shots_on_goal', 'sog_p', 'points', 'p_p', 'goals', 'g_p']].sort_values(['player_id', 't'])
for k, pj in (('shots_on_goal', 'sog_p'), ('points', 'p_p')):
    s['beat'] = (s[k] > s[pj]).astype(int)
    s['run'] = s.groupby('player_id').beat.transform(lambda z: z.groupby((z != z.shift()).cumsum()).cumcount() + 1) * s.beat
    s['run_prev'] = s.groupby('player_id').run.shift()
    res = {}
    for n in (3, 4, 5):
        x = s[(s.run_prev >= n) & (s.yr >= 2018)]
        res[n] = {'n': int(len(x)), 'next_beat_rate': round(float(x.beat.mean()), 3), 'next_resid': round(float((x[k] - x[pj]).mean()), 3)}
    base = s[s.yr >= 2018]; res['all'] = {'next_beat_rate': round(float(base.beat.mean()), 3), 'next_resid': round(float((base[k] - base[pj]).mean()), 3)}
    out['nhl_' + k] = res
# goal-scoring streaks: scored in 3+ straight -> next game goal rate vs projection
s['scored'] = (s.goals > 0).astype(int)
s['grun'] = s.groupby('player_id').scored.transform(lambda z: z.groupby((z != z.shift()).cumsum()).cumcount() + 1) * s.scored
s['grun_prev'] = s.groupby('player_id').grun.shift()
x = s[(s.grun_prev >= 3) & (s.yr >= 2018)]
out['nhl_goal_streak3'] = {'n': int(len(x)), 'next_goal_rate': round(float(x.scored.mean()), 3), 'projected': round(float((1 - np.exp(-x.g_p)).mean()), 3)}
# teams: covering streaks (NBA) -> next cover rate
g = pd.read_pickle(f'{WORK}/nba_games.pkl'); g = g[g.line.notna() & g.hs.notna()].sort_values('t')
rows = []
for side in ('home', 'away'):
    x = g[['gid', 't', 'season', side, 'margin', 'line', 'hs', 'as_', 'total']].rename(columns={side: 'team'})
    sg = 1 if side == 'home' else -1
    x['cov'] = np.sign(sg * x.margin + (x.line if side == 'home' else -x.line))
    x['ovr'] = np.sign(x.hs + x.as_ - x.total)
    rows.append(x[['gid', 't', 'season', 'team', 'cov', 'ovr']])
tm = pd.concat(rows).sort_values(['team', 't'])
for col, nm in (('cov', 'ats'), ('ovr', 'over')):
    tm['w'] = (tm[col] > 0).astype(int)
    tm['run'] = tm.groupby('team').w.transform(lambda z: z.groupby((z != z.shift()).cumsum()).cumcount() + 1) * tm.w
    tm['run_prev'] = tm.groupby('team').run.shift()
    res = {}
    for n in (3, 4, 5):
        x = tm[(tm.run_prev >= n) & (tm[col] != 0)]
        res[n] = {'n': int(len(x)), 'next_rate': round(float((x[col] > 0).mean()), 3)}
    out['nba_team_' + nm] = res
print(json.dumps(out, indent=1)); json.dump(out, open(f'{WORK}/trend_carry.json', 'w'))
