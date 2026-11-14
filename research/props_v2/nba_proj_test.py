"""How far off the site's NBA projections are from what players actually did, and whether faster form, a better prior, or a
better minutes model closes the gap. Walk-forward: every number uses only games before the one being projected.
Fit on 2023-24 and 2024-25, tested on 2025-26 and this season."""
import pandas as pd, numpy as np, json, sys
WORK = '/home/claude/research_work/work'
S = json.load(open('/home/claude/nfl/repo/pipeline/static/nba_model.json'))['props']
d = pd.read_pickle(f'{WORK}/nba_feat.pkl')
STATS = ['pts', 'reb', 'ast', 'fg3m', 'stl', 'blk', 'tov']
d = d[(d.n_prev >= 3) & d.min_ew.notna()].copy()
FIT = d.season.isin([2024, 2025]); TEST = d.season.isin([2026, 2027])
c = S['min_coef']
d['min_live'] = np.clip(c[0] + c[1] * d.min_ew + c[2] * d.min_l10 + c[3] * d.started.fillna(0) + c[4] * d.min_ew * 6 / 10 + c[5] * d.b2b, 0, 44)


def rates(hl, prior, prior_kind='pos', season_w=0.0):
    out = {}
    w = d[f'minr_{hl}'] * np.minimum(d.n_prev, 30)
    for k in STATS:
        r = d[f'{k}_ew{hl}'] / d[f'minr_{hl}'].clip(lower=1)
        if prior_kind == 'pos':
            pr = d[k + '_lgpos']
        r = (r * w + pr * prior) / (w + prior)
        if season_w:
            cs = d[k + '_cs'] / d.min_cs.clip(lower=1)
            ws = (d.min_cs.fillna(0) / (d.min_cs.fillna(0) + season_w)).where(d.n_season >= 1, 0)
            r = np.where(d.n_season >= 1, ws * cs.fillna(r) + (1 - ws) * r, r)
        out[k] = r
    return out


def proj(rt, mins, a_opp=None):
    out = {}
    for k in STATS:
        a, b = S['adj'][k] if a_opp is None else a_opp
        opp_f = (d[k + '_allow'] / d[k + '_lg']).fillna(1).clip(0.6, 1.6)
        out[k] = mins * rt[k] * opp_f ** a * d.pace_f ** b
    return out


def mae(pj, m=TEST):
    return {k: round(float(np.abs(d.loc[m, k] - pj[k][m]).mean()), 3) for k in STATS}


base = proj(rates(18, 150), d.min_live)
res = {'live': mae(base)}
print('live model MAE (2025-26 + now):', res['live'], '| minutes MAE', round(float(np.abs(d['min'] - d.min_live)[TEST].mean()), 2))
for hl in (6, 10, 18):
    for prior in (50, 150, 400):
        r = mae(proj(rates(hl, prior), d.min_live)); res[f'hl{hl}_p{prior}'] = r
        print(f'rate half-life {hl:2d} prior {prior:3d}:', r)
for sw in (300, 800):
    r = mae(proj(rates(10, 150, season_w=sw), d.min_live)); res[f'hl10_season{sw}'] = r; print('hl10 + this-season rate, weight', sw, r)
# minutes: refit OLS on 2023-25 with extra inputs
X = lambda x: np.column_stack([np.ones(len(x)), x.min_ew, x.min_l10, x.started.fillna(0), x.b2b, x.min_last.fillna(x.min_ew), x.started_last.fillna(0),
                               (x.n_season == 0).astype(float), x[f'minr_18']])
fm = FIT & d.min_last.notna()
b = np.linalg.lstsq(X(d[fm]), d.loc[fm, 'min'], rcond=None)[0]
d['min_new'] = np.clip(X(d) @ b, 0, 44)
print('minutes MAE: live', round(float(np.abs(d['min'] - d.min_live)[TEST].mean()), 3), '| refit with last game, season start', round(float(np.abs(d['min'] - d.min_new)[TEST].mean()), 3), np.round(b, 3))
json.dump({'res': res, 'min_coef_new': b.tolist()}, open(f'{WORK}/nba_proj_test.json', 'w'))
d[['game_id', 'athlete_id', 'min_live', 'min_new']].to_pickle(f'{WORK}/nba_min.pkl')
