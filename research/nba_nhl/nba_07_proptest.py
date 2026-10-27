"""Projections -> over/under chances, tested against 270k real book lines (2023-24 to now)."""
import pandas as pd, numpy as np, json
WORK = 'work'
pl = pd.read_pickle(f'{WORK}/nba_proj_base.pkl')
lines = pd.read_pickle(f'{WORK}/nba_prop_lines.pkl')
STATS = ['pts', 'reb', 'ast', 'fg3m', 'stl', 'blk', 'tov']
COMBO = {'pra': ['pts', 'reb', 'ast'], 'pr': ['pts', 'reb'], 'pa': ['pts', 'ast'], 'ra': ['reb', 'ast']}
d = pl[(pl.n_prev >= 3) & pl.min_ew.notna()].copy()
d['absl'] = d.team_line.abs().fillna(6)
d['b2b'] = (d.rest <= 1).astype(float)
# ---------------- minutes: fit on 2016-2022, applied everywhere
tr = d[(d.season >= 2016) & (d.season <= 2022)]
Xm = lambda x: np.column_stack([np.ones(len(x)), x.min_ew, x.min_l10.fillna(x.min_ew), x.started_prev.fillna(0), x.min_ew * x.absl / 10, x.b2b])
bm = np.linalg.lstsq(Xm(tr), tr['min'], rcond=None)[0]
d['min_proj'] = np.clip(Xm(d) @ bm, 0, 44)
print('minutes coef', np.round(bm, 3), 'MAE', np.abs(d['min'] - d.min_proj).mean().round(2), 'vs ew', np.abs(d['min'] - d.min_ew).mean().round(2))
# ---------------- stat projections with opponent and pace adjustment strength fit on 2016-2022
best = {}
for k in STATS:
    opp_f = (d[k + '_allow'] / d[k + '_lg']).fillna(1).clip(0.6, 1.6)
    base = d.min_proj * d[k + '_rate']
    res = []
    for a in (0, 0.5, 1.0):
        for b in (0, 0.5, 1.0):
            pj = base * opp_f ** a * d.pace_f ** b
            m = (d.season >= 2016) & (d.season <= 2022)
            res.append((np.abs(d[k][m] - pj[m]).mean(), a, b))
    res.sort(); _, a, b = res[0]; best[k] = (a, b)
    d[k + '_proj'] = base * opp_f ** a * d.pace_f ** b
    print(k, 'opp^', a, 'pace^', b, 'MAE', round(res[0][0], 3), 'vs rate-only', round(np.abs(d[k] - base)[(d.season >= 2016) & (d.season <= 2022)].mean(), 3))
for c, parts in COMBO.items():
    d[c] = d[parts].sum(axis=1); d[c + '_proj'] = d[[p + '_proj' for p in parts]].sum(axis=1)
ALL = STATS + list(COMBO)
# ---------------- distribution of outcomes around the projection: empirical ratios by projection bin, fit on 2016-2022
QS = np.linspace(0, 1, 201)
dist = {}
for k in ALL:
    m = (d.season >= 2016) & (d.season <= 2022) & (d[k + '_proj'] > 0.05)
    x = d.loc[m, [k, k + '_proj']]
    edges = np.unique(np.quantile(x[k + '_proj'], np.linspace(0, 1, 13)))
    bins = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        y = x[(x[k + '_proj'] >= lo) & (x[k + '_proj'] <= hi)]
        bins.append({'lo': float(lo), 'hi': float(hi), 'n': len(y), 'q': np.quantile(y[k] / y[k + '_proj'], QS).tolist()})
    dist[k] = bins
def p_over(k, proj, L):
    """P(actual > L): share of past outcomes in this projection bin whose ratio beats L/proj (with a discrete-count correction)."""
    if not proj or proj <= 0: return None
    bins = dist[k]; b = next((x for x in bins if proj <= x['hi']), bins[-1])
    q = np.array(b['q']); t = L / proj
    return float(1 - np.interp(t, q, QS, left=0, right=1))
# ---------------- against the book lines
L = lines.merge(d[['game_id', 'pid', 'season'] + [k + '_proj' for k in ALL]], left_on=['event', 'athlete'], right_on=['game_id', 'pid'], how='inner')
L = L[L.actual.notna() & (L.actual != L.line)].copy()
L['proj'] = [getattr(r, r.k + '_proj') for r in L.itertuples()]
L['p_model'] = [p_over(r.k, r.proj, r.line) for r in L.itertuples()]
L['over'] = (L.actual > L.line).astype(int)
L = L[L.p_model.notna()]
L['p_model'] = L.p_model.clip(0.01, 0.99)
ll = lambda p, y: float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
dec = lambda o: np.where(o > 0, 1 + o / 100, 1 + 100 / np.abs(o))
print('\nlines', len(L), 'log loss model', round(ll(L.p_model, L.over), 4), 'book (no vig)', round(ll(L.p1, L.over), 4), '| over rate', L.over.mean().round(3), 'model mean', L.p_model.mean().round(3))
out = {}
for k, x in L.groupby('k'):
    o = {'n': len(x), 'll_model': round(ll(x.p_model, x.over), 4), 'll_book': round(ll(x.p1, x.over), 4)}
    # blend: does the model add anything to the book? logistic-ish check via average of logits
    for thr in (0.03, 0.06, 0.10):
        ov = x[x.p_model - x.p1 >= thr]; un = x[x.p1 - x.p_model >= thr]
        r = np.concatenate([ov.over * dec(ov.o) - 1, (1 - un.over) * dec(un.o2) - 1])
        o[f'roi{int(thr * 100)}'] = [len(r), round(float(r.mean()), 4) if len(r) else None]
    out[k] = o; print(k, o)
L.to_pickle(f'{WORK}/nba_prop_eval.pkl')
d.to_pickle(f'{WORK}/nba_proj.pkl')
json.dump({'dist': dist, 'best': best, 'min_coef': bm.tolist()}, open(f'{WORK}/nba_prop_model.json', 'w'))
