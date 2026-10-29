"""NFL player props for the 1st quarter and 1st half: passing, rushing and receiving yards, catches, and a touchdown.

The site's full-game projection (player_research.json models on work/player_hist_features.pkl) times a share for that
part of the game, share = s0 + s1 * team's expected margin / 10 + s2 * ln(projection / median projection): teams ahead
run more late and teams behind throw more, and starters (the big projections) get more of their work early while backups
fill in late. QB passing keeps s2 = 0 (it didn't help out of sample). Fit on 2018-2022 and checked on 2023-2025. Outcomes around those projections are lumpy (a 1st quarter often has zero
catches for a player), so like the full-game props each one uses the real distribution of results among players with
similar projections: survival curves on a grid of lines, thirteen bins by projection (narrower at the top, where the
players books post lines for sit; eight for QBs, who are fewer), blended between bins. Each line's chance is kept from
falling as the projection rises (pooled across neighboring bins where the sample says otherwise). Past the top bin the curve stretches with the projection
(a player projected for 22 yards gets the top bin's shape scaled from its 18), so stars aren't pulled back to the bin.
A touchdown in a part: 1 - (1 - p)^share_td with p the full-game anytime chance (the any_td model).
-> work/nfl_player_periods.json (copied to pipeline/static/)"""
import json, numpy as np, pandas as pd
WORK = '/home/claude/nfl/work'
d = pd.read_pickle(f'{WORK}/player_hist_features.pkl')
d = d[(d.season_type == 'REG') & (d.n_prior >= 3)].copy()
PQ = pd.read_pickle(f'{WORK}/nfl_pq.pkl')
d = d.merge(PQ, on=['game_id', 'player_id'], how='left')
d = d[d.game_id.isin(set(PQ.game_id))]
for c in PQ.columns:
    if c not in ('game_id', 'player_id'):
        d[c] = d[c].fillna(0)
MODELS = json.load(open('/home/claude/nfl/repo/pipeline/static/player_research.json'))['models']
proj = lambda z, key: z[MODELS[key]['feats']].astype(float).values @ np.array(MODELS[key]['beta'][:-1]) + MODELS[key]['beta'][-1]
d['tm'] = np.where(d.team == d.home_team, d.spread_line, -d.spread_line)          # the team's expected margin
STAT = {'pass_yds': ('passing_yards', ['QB'], 100), 'rush_yds': ('rushing_yards', ['RB', 'QB'], 10), 'rec_yds': ('receiving_yards', ['WR', 'TE', 'RB'], 10),
        'receptions': ('receptions', ['WR', 'TE', 'RB'], 1)}
GRID = {'pass_yds': list(range(0, 11)) + list(range(15, 351, 5)), 'rush_yds': list(range(0, 11)) + list(range(15, 151, 5)),     # every yard at the low end:
        'rec_yds': list(range(0, 11)) + list(range(15, 151, 5)), 'receptions': list(range(0, 13))}                                 # 1+ is a real line in a quarter
TR, TE = d.season <= 2022, (d.season >= 2023) & (d.season <= 2025)
QS = [0, .1, .2, .3, .4, .5, .6, .7, .8, .875, .925, .96, .985, 1]          # bin edges by projection quantile
QS_QB = [0, .125, .25, .375, .5, .625, .75, .875, 1]


def pav(y, w):
    """weighted isotonic (non-decreasing) fit by pooling adjacent violators"""
    blocks = []                                                            # [mean, weight, count]
    for v, wt in zip(y, w):
        blocks.append([v, wt, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            m2, w2, c2 = blocks.pop(); m1, w1, c1 = blocks.pop()
            blocks.append([(m1 * w1 + m2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
    return [m for m, _, c in blocks for _ in range(c)]
out = {'fit_seasons': [2018, 2022], 'check_seasons': [2023, 2025], 'parts': {}}


def pp_of(z, f):
    """the part projection: full-game projection times the share"""
    s0, s1, s2, med = f['share']
    return (s0 + s1 * z.tm / 10 + s2 * np.log(np.maximum(z.p0, 0.1) / med)).clip(lower=0.02) * z.p0


def fit_part(z, key, part):
    col, pos, min_proj = STAT[key]
    z = z[z.position.isin(pos)].copy(); z['p0'] = proj(z, key)
    z = z[z.p0 >= min_proj]
    med = float(z.p0.median())
    if key == 'pass_yds':
        X = np.column_stack([z.p0, z.p0 * z.tm / 10]); s0, s1 = np.linalg.lstsq(X, z[f'{part}_{key}'], rcond=None)[0]; s2 = 0.0
    else:
        X = np.column_stack([z.p0, z.p0 * z.tm / 10, z.p0 * np.log(z.p0 / med)]); s0, s1, s2 = np.linalg.lstsq(X, z[f'{part}_{key}'], rcond=None)[0]
    f = {'share': [round(float(s0), 4), round(float(s1), 4), round(float(s2), 4), round(med, 2)]}
    z['pp'] = pp_of(z, f)
    qs = QS_QB if key == 'pass_yds' else QS
    edges = np.quantile(z.pp, qs); g = np.array(GRID[key]); bins = []
    for i in range(len(qs) - 1):
        m = (z.pp >= edges[i]) & (z.pp <= edges[i + 1]); y = z.loc[m, f'{part}_{key}'].values
        bins.append({'center': float(z.pp[m].mean()), 'n': int(m.sum()), 'surv': [float((y >= t).mean()) for t in g]})
    S = np.array([b['surv'] for b in bins]); W = [b['n'] for b in bins]
    for j in range(S.shape[1]):                                            # a bigger projection never lowers a line's chance
        S[:, j] = pav(S[:, j], W)
    S = np.minimum.accumulate(S, axis=1)                                   # and a higher line is never likelier
    for b, row in zip(bins, S):
        b['surv'] = [round(float(v), 4) for v in row]
    return {'share': f['share'], 'grid': GRID[key], 'bins': bins}


def chance(dist, pp, t):
    """P(result >= t) for a player projected pp: blend the two nearest bins; past the top bin, stretch its curve."""
    g = dist['grid']; cs = [b['center'] for b in dist['bins']]
    def surv(b, t):
        if t <= g[0]: return b['surv'][0]
        if t >= g[-1]: return b['surv'][-1]
        j = int(np.searchsorted(g, t, side='right')) - 1; w = (t - g[j]) / (g[j + 1] - g[j]); return b['surv'][j] * (1 - w) + b['surv'][j + 1] * w
    if pp <= cs[0]: return surv(dist['bins'][0], t)
    if pp >= cs[-1]: return surv(dist['bins'][-1], t * cs[-1] / pp)
    k = int(np.searchsorted(cs, pp, side='right')) - 1; w = (pp - cs[k]) / (cs[k + 1] - cs[k])
    return surv(dist['bins'][k], t) * (1 - w) + surv(dist['bins'][k + 1], t) * w


def f_pp_train(z, key, f):
    col, pos, min_proj = STAT[key]
    z = z[z.position.isin(pos)].copy(); z['p0'] = proj(z, key); z = z[z.p0 >= min_proj]
    return pp_of(z, f)


for part in ('q1', 'h1'):
    for key in STAT:
        f = fit_part(d[TR], key, part)
        col, pos, min_proj = STAT[key]
        z = d[TE & d.position.isin(pos)].copy(); z['p0'] = proj(z, key); z = z[z.p0 >= min_proj]
        z['pp'] = pp_of(z, f)
        rows = []
        for off in (-2, -1, 0, 1, 2):                          # lines near the projection, as books would hang them
            step = 1 if key == 'receptions' else 5
            for pp, y in zip(z.pp, z[f'{part}_{key}']):
                L = max(0.5, np.floor(pp / step) * step + 0.5 + off * step) if key != 'receptions' else max(0.5, np.floor(pp) + 0.5 + off)
                rows.append((chance(f, pp, np.ceil(L)), float(y > L), pp))
        R = pd.DataFrame(rows, columns=['p', 'y', 'pp']); b = pd.cut(R.p, [0, .2, .3, .4, .5, .6, .7, .8, 1])
        cal = [[str(i), int(len(v)), round(float(v.p.mean()), 3), round(float(v.y.mean()), 3)] for i, v in R.groupby(b, observed=True) if len(v) >= 100]
        top_cut = float(np.quantile(f_pp_train(d[TR], key, f), 0.9)); RT = R[R.pp >= top_cut]; bt = pd.cut(RT.p, [0, .3, .4, .5, .6, .7, 1])
        top = [[str(i), int(len(v)), round(float(v.p.mean()), 3), round(float(v.y.mean()), 3)] for i, v in RT.groupby(bt, observed=True) if len(v) >= 50]
        f['check'] = {'n_players': int(len(z)), 'mean_proj': round(float(z.pp.mean()), 2), 'mean_actual': round(float(z[f'{part}_{key}'].mean()), 2), 'calibration': cal,
                      'top_decile_from': round(top_cut, 1), 'top_decile': top}
        print(part, key, f['share'], {k: v for k, v in f['check'].items() if k not in ('calibration', 'top_decile')}); print('     ', cal); print('  top', top)
        out['parts'][f'{part}_{key}'] = f
# ---- touchdowns: 1 - (1 - p)^share, share by likelihood
z = d[TR].copy(); z['p'] = np.clip(proj(z, 'any_td'), 0.02, 0.85); z = z[z.position.isin(['RB', 'WR', 'TE'])]
zt = d[TE & d.position.isin(['RB', 'WR', 'TE'])].copy(); zt['p'] = np.clip(proj(zt, 'any_td'), 0.02, 0.85)
for part in ('q1', 'h1'):
    y = (z[f'{part}_td'] > 0).astype(float)
    ll = lambda s: float(np.sum(y * np.log(1 - (1 - z.p) ** s) + (1 - y) * s * np.log(1 - z.p)))
    s_best = float(max(np.linspace(0.1, 0.8, 141), key=ll))
    pt = 1 - (1 - zt.p) ** s_best; yt = (zt[f'{part}_td'] > 0).astype(float)
    b = pd.cut(pt, [0, .05, .1, .15, .2, .25, .3, .4, 1])
    cal = [[str(i), int(len(v)), round(float(v.mean()), 3), round(float(yt[v.index].mean()), 3)] for i, v in pt.groupby(b, observed=True) if len(v) >= 100]
    out['parts'][f'{part}_td'] = {'share': round(s_best, 4), 'check': {'model': round(float(pt.mean()), 4), 'actual': round(float(yt.mean()), 4), 'calibration': cal}}
    print(part, 'td share', round(s_best, 3), out['parts'][f'{part}_td']['check'])
# ---- the site's numbers: refit on 2021-2025
out['site_fit_seasons'] = [2021, 2025]; out['site'] = {}
L5 = (d.season >= 2021) & (d.season <= 2025)
for part in ('q1', 'h1'):
    for key in STAT:
        out['site'][f'{part}_{key}'] = fit_part(d[L5], key, part)
    z = d[L5 & d.position.isin(['RB', 'WR', 'TE'])].copy(); z['p'] = np.clip(proj(z, 'any_td'), 0.02, 0.85); y = (z[f'{part}_td'] > 0).astype(float)
    ll = lambda s: float(np.sum(y * np.log(1 - (1 - z.p) ** s) + (1 - y) * s * np.log(1 - z.p)))
    out['site'][f'{part}_td'] = {'share': round(float(max(np.linspace(0.1, 0.8, 141), key=ll)), 4)}
print('site', {k: v['share'] for k, v in out['site'].items()})
json.dump(out, open(f'{WORK}/nfl_player_periods.json', 'w'), indent=1)
static = {'about': 'NFL 1st-quarter and 1st-half player props (research/16_player_periods.py): share of the full-game projection '
                   '(s0 + s1 * team margin / 10); results by projection bins, stretched past the top bin; touchdowns 1 - (1 - p)^share.',
          'fit_seasons': out['site_fit_seasons'], 'check_seasons': out['check_seasons'], 'parts': out['site'],
          'check': {k: {kk: vv for kk, vv in v['check'].items() if kk != 'calibration'} for k, v in out['parts'].items()},
          'share_note': 'share = [s0, s1, s2, median]: s0 + s1 * team margin / 10 + s2 * ln(projection / median), at least 0.02'}
json.dump(static, open('/home/claude/nfl/repo/pipeline/static/nfl_player_parts.json', 'w'), separators=(',', ':'))
