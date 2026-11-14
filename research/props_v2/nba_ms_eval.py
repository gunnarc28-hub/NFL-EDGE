"""NBA milestone (X+) prices vs three fair chances: the raw model, and the model's distribution re-centred so it agrees with
the book's own main line (market-anchored). Calibration and ROI at the real prices, by season."""
import pandas as pd, numpy as np, json
WORK = '/home/claude/research_work/work'
S = json.load(open('/home/claude/nfl/repo/pipeline/static/nba_model.json'))['props']
E = pd.read_pickle(f'{WORK}/nba_eval.pkl')                    # main lines with projections (proj_new) and p1
MS = pd.read_pickle(f'{WORK}/nba_ms.pkl')
QS = np.linspace(0, 1, 201)
DIST = {k: [(b['hi'], np.array(b['q'])) for b in S['dist'][k]] for k in S['dist']}


def p_over(k, proj, line):
    if proj <= 0.05:
        return 0.0
    q = next((q for hi, q in DIST[k] if proj <= hi), DIST[k][-1][1])
    t = (line if line % 1 else line - 0.5) / proj
    return float(1 - np.interp(t, q, QS, left=0, right=1))


def anchor(k, line, pb, lo=0.05, hi=80):
    """the projection at which the model's distribution gives the book's chance of going over its main line"""
    for _ in range(40):
        mid = (lo + hi) / 2
        if p_over(k, mid, line) < pb: lo = mid
        else: hi = mid
    return (lo + hi) / 2


main = E[['event', 'athlete', 'k', 'line', 'p1', 'proj_new', 'season']].rename(columns={'line': 'mline'})
x = MS[MS.actual.notna()].merge(main, on=['event', 'athlete', 'k'], how='inner', suffixes=('', '_m'))
x = x[x.k.isin(DIST)].copy()
imp = lambda o: np.where(o < 0, -o / (-o + 100), 100 / (o + 100))
dec = lambda o: np.where(o > 0, 1 + o / 100, 1 + 100 / np.abs(o))
x['p_imp'] = imp(x.o)
x['mu_anchor'] = [anchor(k, l, p) for k, l, p in zip(x.k, x.mline, x.p1)]
x['p_raw'] = [p_over(k, mu, t - 0.5) for k, mu, t in zip(x.k, x.proj_new, x.line)]
x['p_anc'] = [p_over(k, mu, t - 0.5) for k, mu, t in zip(x.k, x.mu_anchor, x.line)]
x['y'] = (x.actual >= x.line).astype(int)
x['season'] = x.season.fillna(x.season_m) if 'season_m' in x else x.season
x.to_pickle(f'{WORK}/nba_ms_eval.pkl')
clip = lambda p: np.clip(p, 0.005, 0.995)
ll = lambda p, y: float(-np.mean(y * np.log(clip(p)) + (1 - y) * np.log(1 - clip(p))))
print('milestones with a main line and a result:', len(x), x.groupby('season').size().to_dict())
for nm, z in (('all', x), ('2025-26 + now', x[x.season >= 2026])):
    print(f'\n{nm}: n {len(z)}  hit {z.y.mean():.3f}  book implied {z.p_imp.mean():.3f}  raw model {z.p_raw.mean():.3f}  anchored {z.p_anc.mean():.3f}')
    print('  log loss: book implied', round(ll(z.p_imp, z.y), 4), 'raw', round(ll(z.p_raw, z.y), 4), 'anchored', round(ll(z.p_anc, z.y), 4))
    z = z.assign(b=pd.cut(z.p_imp, [0, .1, .2, .35, .5, .65, .8, .9, 1]))
    print(z.groupby('b', observed=True).agg(n=('y', 'size'), hit=('y', 'mean'), implied=('p_imp', 'mean'), anchored=('p_anc', 'mean'), raw=('p_raw', 'mean')).round(3).to_string())
    for col in ('p_anc', 'p_raw'):
        for thr in (0.0, 0.03, 0.06):
            b = z[z[col] - z.p_imp >= thr]; r = b.y * dec(b.o) - 1
            print(f'  bet when {col} beats the price by {thr}:', len(b), round(float(r.mean()), 4) if len(b) else None)
