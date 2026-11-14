"""Out-of-sample: fit the market-anchored fair chance on 2023-24..2024-25, then bet only when the fair chance says the
book's price pays at least X% more than fair. ROI on 2025-26 and this season, by market, side, and book."""
import pandas as pd, numpy as np, json
m = pd.read_pickle('work/nba_eval.pkl')
clip = lambda p: np.clip(p, 0.02, 0.98); lg = lambda p: np.log(clip(p) / (1 - clip(p)))
dec = lambda o: np.where(o > 0, 1 + o / 100, 1 + 100 / np.abs(o))
def fitlog(X, y, l2=1.0, it=60):
    X = np.column_stack([np.ones(len(X)), X]); w = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ w)); g = X.T @ (p - y) + l2 * np.r_[0, w[1:]]
        H = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.diag(np.r_[0, np.ones(len(w) - 1)]); w -= np.linalg.solve(H, g)
    return w
feats = lambda z: np.column_stack([lg(z.p1), lg(z.pm_new) - lg(z.p1)])
rows = []
for split in (('fit 24-25, test 26-27', [2024, 2025], [2026, 2027]), ('fit 24, 26-27 ; test 25', [2024, 2026, 2027], [2025])):
    nm, fs, ts = split
    for k, x in m.groupby('k'):
        f, t = x[x.season.isin(fs)], x[x.season.isin(ts)]
        w = fitlog(feats(f), f.y.values)
        pf = 1 / (1 + np.exp(-(np.column_stack([np.ones(len(t)), feats(t)]) @ w)))
        evo = pf * dec(t.o) - 1; evu = (1 - pf) * dec(t.o2) - 1
        for thr in (0.0, 0.02, 0.04, 0.06):
            ro = (t.y * dec(t.o) - 1)[evo >= thr]; ru = ((1 - t.y) * dec(t.o2) - 1)[evu >= thr]
            r = pd.concat([ro, ru]); rows.append([nm, k, thr, len(r), round(r.mean(), 4) if len(r) else None, len(ro), round(ro.mean(), 3) if len(ro) else None, len(ru), round(ru.mean(), 3) if len(ru) else None, np.round(w, 3).tolist()])
R = pd.DataFrame(rows, columns=['split', 'k', 'ev_min', 'n', 'roi', 'n_over', 'roi_over', 'n_under', 'roi_under', 'w'])
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 200)
print(R[R.n > 0].drop(columns='w').to_string(index=False))
