"""Does knowing who sits close the gap to the closing line?"""
import os, pandas as pd, numpy as np, json, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location('m2', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nba_02_model.py')); m2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(m2)
WORK = 'work'
M = pd.read_pickle(f'{WORK}/nba_missing.pkl')
f = m2.run(H=20, carry=0.6)
d = m2.g[['gid', 'season', 'margin', 'line', 'total', 'hs', 'as_', 'home', 'away', 't', 'ml_home', 'ml_away']].merge(f.drop(columns=['season']), on='gid')
d = d.merge(M.rename(columns={'team': 'home', 'miss_v': 'miss_h', 'miss_m': 'missm_h', 'avail_v': 'av_h', 'n_miss': 'nm_h'}), on=['gid', 'home'], how='left')
d = d.merge(M.rename(columns={'team': 'away', 'miss_v': 'miss_a', 'miss_m': 'missm_a', 'avail_v': 'av_a', 'n_miss': 'nm_a'}), on=['gid', 'away'], how='left')
for c in ['miss_h', 'miss_a', 'av_h', 'av_a']: d[c] = d[c].fillna(d[c].median())
d['tot'] = d.hs + d.as_
d['b2b_h'] = (d.rest_h <= 1).astype(int); d['b2b_a'] = (d.rest_a <= 1).astype(int); d['hfa'] = (~d.neutral).astype(int)
d['miss_d'] = d.miss_a - d.miss_h; d['av_d'] = d.av_h - d.av_a
def wf(feats, label):
    res = []
    for test in range(2016, 2027):
        tr = d[(d.season < test) & (d.season >= test - 4) & (d.n_h >= 5) & (d.n_a >= 5)]
        te = d[d.season == test].copy()
        X = lambda x: np.column_stack([np.ones(len(x))] + [x[c] for c in feats])
        b = np.linalg.lstsq(X(tr), tr.margin, rcond=None)[0]
        te['pm'] = X(te) @ b; res.append(te)
    r = pd.concat(res); r = r[r.line.notna()]; r['mkt'] = -r.line
    o = {'rmse': round(float(np.sqrt(((r.margin - r.pm) ** 2).mean())), 3), 'rmse_line': round(float(np.sqrt(((r.margin - r.mkt) ** 2).mean())), 3),
         'rmse_vs_line': round(float(np.sqrt(((r.pm - r.mkt) ** 2).mean())), 3)}
    Z = np.column_stack([np.ones(len(r)), r.mkt, r.pm - r.mkt]); o['beta_gap'] = round(float(np.linalg.lstsq(Z, r.margin, rcond=None)[0][2]), 3)
    for thr in (3, 5, 7):
        e = r[abs(r.pm - r.mkt) >= thr]; c_ = np.sign(e.margin + e.line); p_ = np.sign(e.pm - e.mkt)
        w = int((c_ * p_ > 0).sum()); l = int((c_ * p_ < 0).sum()); o[f'ats{thr}'] = f'{w}-{l} {w / max(1, w + l):.3f}'
    print(label, o, 'coef', np.round(b, 3).tolist())
    return r
wf(['rate_m', 'hfa', 'b2b_h', 'b2b_a'], 'base        ')
wf(['rate_m', 'hfa', 'b2b_h', 'b2b_a', 'miss_d'], '+missing    ')
r = wf(['rate_m', 'hfa', 'b2b_h', 'b2b_a', 'miss_d', 'av_d'], '+miss+avail ')
# how close does it get to the market, season by season
print(r.groupby('season').apply(lambda x: pd.Series({'rmse_model': np.sqrt(((x.margin - x.pm) ** 2).mean()), 'rmse_line': np.sqrt(((x.margin - x.mkt) ** 2).mean()),
                                                     'gap_sd': (x.pm - x.mkt).std()})).round(2))
