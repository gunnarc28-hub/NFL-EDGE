"""Tail calibration for the NBA long shots, and a check of the high-chance legs as the site picks them.

Long shots (25+ points, double-doubles and so on) come out of the outcome tables a little off at the tails, so each
market gets a map from the raw chance to how often it happened: fit on 2015-16 to 2022-23 and checked on 2023-24 to
2025-26, then refit on every season for the live site. The high-chance check replays the site's rule (the biggest round
number a player reaches 80-97% of the time, in a big enough role) on 2023-24 to 2025-26 and compares the chances it
gave with how often the legs hit."""
import os, json, itertools
import pandas as pd, numpy as np
WORK = 'work'
d = pd.read_pickle(f'{WORK}/nba_proj.pkl'); M = json.load(open(f'{WORK}/nba_prop_model.json'))
dist = M['dist']; QS = np.linspace(0, 1, 201)
TRAIN = (d.season >= 2016) & (d.season <= 2023); TEST = d.season >= 2024


def p_atleast(k, proj, t):
    """P(stat >= t) for whole-number t, from the outcome-ratio table of the projection's bin (the build's p_over at t - 0.5)."""
    proj = np.asarray(proj, float); t = np.broadcast_to(np.asarray(t, float), proj.shape)
    bins = dist[k]; his = np.array([b['hi'] for b in bins])
    idx = np.minimum(np.searchsorted(his, proj, side='left'), len(bins) - 1)
    out = np.zeros(len(proj))
    for i in np.unique(idx):
        m = idx == i; q = np.array(bins[i]['q'])
        out[m] = 1 - np.interp((t[m] - 0.5) / np.maximum(proj[m], 1e-6), q, QS, left=0, right=1)
    out[proj <= 0.05] = 0.0
    return out


def iso(x, y, w):
    """Pool adjacent violators: make the observed rates rise with the raw chance."""
    blocks = [[x_, y_, w_] for x_, y_, w_ in zip(x, y, w)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][1] > blocks[i + 1][1]:
            a, b = blocks[i], blocks[i + 1]; W = a[2] + b[2]
            blocks[i] = [(a[0] * a[2] + b[0] * b[2]) / W, (a[1] * a[2] + b[1] * b[2]) / W, W]; del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    return [[round(float(a), 4), round(float(b), 4)] for a, b, _ in blocks]


EDGES = [0.002, 0.005, 0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.13, 0.16, 0.20, 0.25, 0.30, 0.40, 0.55, 0.70, 0.85, 0.98]


def fit_map(p, y, min_n=150):
    """Mean raw chance against how often it happened, in fixed bins from 0.2% to 98%, made monotone."""
    m = (p >= EDGES[0]) & (p <= EDGES[-1]); p, y = p[m], y[m]
    k = np.clip(np.searchsorted(EDGES, p, side='right') - 1, 0, len(EDGES) - 2)
    df = pd.DataFrame({'k': k, 'p': p, 'y': y}).groupby('k').agg(p=('p', 'mean'), y=('y', 'mean'), n=('y', 'size'))
    df = df[df.n >= min_n]
    return iso(df.p.values, df.y.values, df.n.values)


def apply_map(pts, p):
    xs = [0.0] + [a for a, b in pts] + [1.0]; ys = [0.0] + [b for a, b in pts] + [1.0]
    return np.interp(p, xs, ys)


def table(p, y, cuts):
    rows = []
    for lo, hi in cuts:
        m = (p >= lo) & (p < hi)
        if m.sum() >= 30:
            rows.append([lo, hi, int(m.sum()), round(float(p[m].mean()), 3), round(float(y[m].mean()), 3)])
    return rows


# ---------------- long shots: big nights, in the tail the site uses (at least 1.25x the projection)
TS = {'pts': [20, 25, 30, 35, 40, 45, 50], 'reb': [8, 10, 12, 15, 18], 'ast': [6, 8, 10, 12, 15], 'fg3m': [3, 4, 5, 6, 7], 'pra': [30, 35, 40, 45, 50, 55]}
LS_CUTS = [(0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.25), (0.25, 0.34)]
maps_train, maps, check = {}, {}, {}
tail = {}
for k, ts in TS.items():
    P, Y, S, T_ = [], [], [], []
    for t in ts:
        x = d[d[k + '_proj'] * 1.25 <= t]
        P.append(p_atleast(k, x[k + '_proj'].values, t)); Y.append((x[k] >= t).values.astype(float)); S.append(x.season.values)
    p, y, s = np.concatenate(P), np.concatenate(Y), np.concatenate(S)
    tail[k] = (p, y, s)
    tr = (s >= 2016) & (s <= 2023); te = s >= 2024
    maps_train[k + '_hi'] = fit_map(p[tr], y[tr])
    maps[k + '_hi'] = fit_map(p[s >= 2016], y[s >= 2016])
    pc = apply_map(maps_train[k + '_hi'], p[te])
    check[k] = {'raw': table(p[te], y[te], LS_CUTS), 'calibrated': table(pc, y[te], LS_CUTS)}
    print(k, 'raw', check[k]['raw']); print(k, 'cal', check[k]['calibrated'])

# ---------------- double- and triple-doubles: categories at 10+, treated as independent, then mapped
P10 = {k: p_atleast(k, d[k + '_proj'].values, 10) for k in ('pts', 'reb', 'ast', 'stl', 'blk')}
def atleast(n):
    tot = np.zeros(len(d))
    for combo in itertools.product([0, 1], repeat=5):
        if sum(combo) >= n:
            pr = np.ones(len(d))
            for c, k in zip(combo, P10): pr = pr * (P10[k] if c else 1 - P10[k])
            tot += pr
    return tot
cnt = sum((d[k] >= 10).astype(int) for k in P10).values
for n, key in ((2, 'dd'), (3, 'td3')):
    p = atleast(n); y = (cnt >= n).astype(float); s = d.season.values
    tr = (s >= 2016) & (s <= 2023); te = s >= 2024
    maps_train[key] = fit_map(p[tr], y[tr])
    maps[key] = fit_map(p[s >= 2016], y[s >= 2016])
    pc = apply_map(maps_train[key], p[te])
    cuts = [(0.04, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.41)] if key == 'td3' else [(0.12, 0.20), (0.20, 0.30), (0.30, 0.41)]
    check[key] = {'raw': table(p[te], y[te], cuts), 'calibrated': table(pc, y[te], cuts)}
    print(key, 'raw', check[key]['raw']); print(key, 'cal', check[key]['calibrated'])

# ---------------- the long-shot list as the site builds it: one threshold per player and market, 5-33% after the map
sel_p, sel_y = [], []
te_rows = d[TEST & (d.min_proj >= 16)]
for k, ts in (('pts', [25, 30, 35, 40, 45, 50]), ('reb', [10, 12, 15, 18]), ('ast', [8, 10, 12, 15]), ('fg3m', [4, 5, 6, 7]), ('pra', [40, 45, 50, 55])):
    done = np.zeros(len(te_rows), bool)
    for t in ts:
        p = apply_map(maps_train[k + '_hi'], p_atleast(k, te_rows[k + '_proj'].values, t))
        ok = ~done & (p >= 0.05) & (p <= 0.33) & (t >= te_rows[k + '_proj'].values * 1.25)
        sel_p.append(p[ok]); sel_y.append((te_rows[k].values[ok] >= t).astype(float)); done |= ok
ls_check = table(np.concatenate(sel_p), np.concatenate(sel_y), LS_CUTS)
print('long-shot list, 2023-24 to 2025-26:', ls_check)

# ---------------- the high-chance list as the site builds it
MIN_T = {'pts': 10, 'pra': 15, 'pr': 12, 'pa': 12, 'reb': 4, 'ast': 3, 'fg3m': 2}
hp, hy, hk = [], [], []
x = d[TEST & (d.min_proj >= 16)]
for k in ('pts', 'reb', 'ast', 'fg3m', 'pra', 'pr', 'pa'):
    proj = x[k + '_proj'].values; best_t = np.full(len(x), np.nan); best_p = np.full(len(x), np.nan)
    for t in range(1, 80):
        p = p_atleast(k, proj, t)
        ok = (p >= 0.80) & (p <= 0.97)
        best_t = np.where(ok, t, best_t); best_p = np.where(ok, p, best_p)
        if (p >= 0.80).sum() == 0:
            break
    m = ~np.isnan(best_t) & (best_t >= MIN_T[k]) & (best_t >= 0.6 * proj)
    hp.append(best_p[m]); hy.append((x[k].values[m] >= best_t[m]).astype(float)); hk += [k] * int(m.sum())
hp, hy = np.concatenate(hp), np.concatenate(hy)
hc_check = table(hp, hy, [(0.80, 0.85), (0.85, 0.90), (0.90, 0.95), (0.95, 0.971)])
print('high-chance list, 2023-24 to 2025-26:', hc_check)
by_k = pd.DataFrame({'k': hk, 'p': hp, 'y': hy}).groupby('k').agg(n=('y', 'size'), p=('p', 'mean'), hit=('y', 'mean')).round(3)
print(by_k)

json.dump({'maps': maps, 'maps_train': maps_train, 'check': check, 'ls_check': ls_check, 'hc_check': hc_check, 'check_seasons': [2024, 2026]},
          open(f'{WORK}/nba_cal.json', 'w'))
