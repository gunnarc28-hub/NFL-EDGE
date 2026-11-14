"""1) The best projection: model, the book's line-implied mean, or a mix (MAE on 2025-26 + now).
2) High-chance (80%+) and long-shot (5-33%) thresholds: raw model vs market-anchored chances, against what happened."""
import pandas as pd, numpy as np, json
S = json.load(open('/home/claude/nfl/repo/pipeline/static/nba_model.json'))['props']
m = pd.read_pickle('work/nba_eval.pkl')
QS = np.linspace(0, 1, 201); DIST = {k: [(b['hi'], np.array(b['q'])) for b in S['dist'][k]] for k in S['dist']}
def qf(k, proj): return next((q for hi, q in DIST[k] if proj <= hi), DIST[k][-1][1])
def p_ge(k, proj, t):                                     # P(stat >= t), t whole
    if proj <= 0.05: return 0.0
    return float(1 - np.interp((t - 0.5) / proj, qf(k, proj), QS, left=0, right=1))
def mean_of(k, proj):                                     # mean of the distribution at this projection
    return float(np.trapezoid(qf(k, proj), QS) * proj)
def anchor(k, line, pb):
    lo, hi = 0.05, 90
    for _ in range(40):
        mid = (lo + hi) / 2
        if 1 - np.interp((line if line % 1 else line - 0.5) / mid, qf(k, mid), QS, left=0, right=1) < pb: lo = mid
        else: hi = mid
    return (lo + hi) / 2
x = m[m.season >= 2025].copy()
x = x.sample(min(len(x), 60000), random_state=1)
x['mu_anc'] = [anchor(k, l, p) for k, l, p in zip(x.k, x.line, x.p1)]
x['mean_anc'] = [mean_of(k, mu) for k, mu in zip(x.k, x.mu_anc)]
x.to_pickle('work/nba_anchor.pkl')
T = x.season >= 2026; F = ~T
out = {}
for k, z in x.groupby('k'):
    f, t = z[F.loc[z.index]], z[T.loc[z.index]]
    best = min(((np.abs(f.actual - (a * f.mean_anc + (1 - a) * f.proj_new)).mean(), a) for a in np.linspace(0, 1, 21)))[1]
    out[k] = {'w_line': round(float(best), 2), 'mae_model': round(float(np.abs(t.actual - t.proj_new).mean()), 3), 'mae_line_mean': round(float(np.abs(t.actual - t.mean_anc).mean()), 3),
              'mae_mix': round(float(np.abs(t.actual - (best * t.mean_anc + (1 - best) * t.proj_new)).mean()), 3), 'n': len(t)}
    print(k, out[k])
json.dump(out, open('work/nba_mix.json', 'w'))
# tails: for each main line, the high-chance threshold (biggest t with chance >= .8) and a long-shot one (~1.4x the projection)
rows = []
for r in x.itertuples():
    for nm, mu in (('raw', r.proj_new), ('anc', r.mu_anc)):
        best = None
        for t in range(1, 70):
            p = p_ge(r.k, mu, t)
            if p < 0.8: break
            best = (t, p)
        if best and best[0] >= 2:
            pr = p_ge(r.k, r.mu_anc if nm == 'raw' else r.proj_new, best[0])
            rows.append(['hc', nm, r.k, r.season, best[1], int(r.actual >= best[0])])
        t = int(np.ceil(max(r.proj_new, r.mu_anc) * 1.4))
        p = p_ge(r.k, mu, t)
        if 0.05 <= p <= 0.33:
            rows.append(['ls', nm, r.k, r.season, p, int(r.actual >= t)])
R = pd.DataFrame(rows, columns=['kind', 'src', 'k', 'season', 'p', 'y'])
print(R.groupby(['kind', 'src']).agg(n=('y', 'size'), expected=('p', 'mean'), hit=('y', 'mean')).round(3))
R['b'] = pd.cut(R.p, [0, .1, .2, .33, .8, .85, .9, 1])
print(R.groupby(['kind', 'src', 'b'], observed=True).agg(n=('y', 'size'), expected=('p', 'mean'), hit=('y', 'mean')).round(3))
