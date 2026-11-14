"""Final NBA prop parameters for the build, fit on every season with lines (2023-24 to now):
fair chance per market = logistic(a + b*logit(book no-vig) + c*(logit(model) - logit(book))), the line weight in the shown
projection, and the minutes and form settings tested in nba_proj_test.py. Writes work/nba_props_v2.json."""
import pandas as pd, numpy as np, json
m = pd.read_pickle('work/nba_eval.pkl'); mix = json.load(open('work/nba_mix.json')); pt = json.load(open('work/nba_proj_test.json'))
clip = lambda p: np.clip(p, 0.02, 0.98); lg = lambda p: np.log(clip(p) / (1 - clip(p)))
def fitlog(X, y, l2=1.0, it=60):
    X = np.column_stack([np.ones(len(X)), X]); w = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ w)); g = X.T @ (p - y) + l2 * np.r_[0, w[1:]]
        H = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.diag(np.r_[0, np.ones(len(w) - 1)]); w -= np.linalg.solve(H, g)
    return w
ll = lambda p, y: float(-np.mean(y * np.log(clip(p)) + (1 - y) * np.log(1 - clip(p))))
fair, check = {}, {}
for k, x in m.groupby('k'):
    w = fitlog(np.column_stack([lg(x.p1), lg(x.pm_new) - lg(x.p1)]), x.y.values)
    # the model's say can't be negative or larger than the old blend allowed
    w[2] = float(np.clip(w[2], 0, 0.45))
    fair[k] = [round(float(v), 4) for v in w]
    p = 1 / (1 + np.exp(-(w[0] + w[1] * lg(x.p1) + w[2] * (lg(x.pm_new) - lg(x.p1)))))
    check[k] = {'n': len(x), 'over_rate': round(float(x.y.mean()), 3), 'book_mean': round(float(x.p1.mean()), 3), 'fair_mean': round(float(p.mean()), 3),
                'll_book': round(ll(x.p1, x.y), 4), 'll_fair': round(ll(p, x.y), 4)}
    print(k, fair[k], check[k])
mixw = {k: v['w_line'] for k, v in mix.items()}
mixw['tov'] = 0.65
out = {'fair': fair, 'fair_check': check, 'mix_line': mixw, 'min_coef_v2': pt['min_coef_new'], 'half_life_rate': 10, 'prior_minutes': 50,
       'seasons': sorted(int(s) for s in m.season.dropna().unique()), 'lines': int(len(m))}
json.dump(out, open('work/nba_props_v2.json', 'w'), indent=1)
