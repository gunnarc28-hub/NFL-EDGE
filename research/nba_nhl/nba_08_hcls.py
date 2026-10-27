"""Calibration at the tails: high-chance thresholds (80%+) and long shots, from projections + outcome distributions."""
import pandas as pd, numpy as np, json
WORK = 'work'
d = pd.read_pickle(f'{WORK}/nba_proj.pkl'); M = json.load(open(f'{WORK}/nba_prop_model.json'))
dist = M['dist']; QS = np.linspace(0, 1, 201)
def p_atleast(k, proj, t):
    """P(stat >= t) from the ratio table (t an integer threshold: >= t means > t - 0.5)."""
    bins = dist[k]; b = next((x for x in bins if proj <= x['hi']), bins[-1]); q = np.array(b['q'])
    return 1 - np.interp((t - 0.5) / max(proj, 1e-6), q, QS, left=0, right=1)
te = d[(d.season >= 2024)].copy()
out = {}
for k, ts in (('pts', [10, 15, 20, 25, 30, 35, 40]), ('reb', [4, 6, 8, 10, 12, 15]), ('ast', [3, 4, 6, 8, 10, 12]), ('fg3m', [1, 2, 3, 4, 5, 6]),
              ('stl', [1, 2, 3]), ('blk', [1, 2, 3, 4]), ('pra', [15, 20, 25, 30, 40, 50])):
    rows = []
    for t in ts:
        p = p_atleast(k, te[k + '_proj'].values, t) if False else np.array([p_atleast(k, pj, t) for pj in te[k + '_proj'].values])
        y = (te[k] >= t).values
        for lo, hi in ((0.80, 0.85), (0.85, 0.90), (0.90, 0.95), (0.95, 1.0), (0.02, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.35)):
            m = (p >= lo) & (p < hi)
            if m.sum() >= 30: rows.append((t, f'{lo:.2f}-{hi:.2f}', int(m.sum()), round(float(p[m].mean()), 3), round(float(y[m].mean()), 3)))
    out[k] = rows
    print(k); [print('   ', r) for r in rows]
# double-double / triple-double: count of 10+ categories, independent-ish product check
def p10(k, pj): return np.array([p_atleast(k, x, 10) for x in pj])
P = {k: p10(k, te[k + '_proj'].values) for k in ('pts', 'reb', 'ast', 'stl', 'blk')}
# probability of at least 2 / 3 categories >= 10 assuming independence
import itertools
def atleast(n):
    ks = list(P); tot = np.zeros(len(te))
    for combo in itertools.product([0, 1], repeat=len(ks)):
        if sum(combo) >= n:
            pr = np.ones(len(te))
            for c, k in zip(combo, ks): pr *= P[k] if c else (1 - P[k])
            tot += pr
    return tot
cnt = sum((te[k] >= 10).astype(int) for k in P)
for n, nm in ((2, 'double-double'), (3, 'triple-double')):
    p = atleast(n); y = (cnt >= n).values
    for lo, hi in ((0.02, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 0.35), (0.35, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1)):
        m = (p >= lo) & (p < hi)
        if m.sum() >= 30: print(nm, f'{lo}-{hi}', int(m.sum()), round(float(p[m].mean()), 3), round(float(y[m].mean()), 3))
