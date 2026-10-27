"""NHL props against real lines: over/unders (points, assists, shots, blocks, saves) and yes bets (anytime, 2+ goals, first goal)."""
import pandas as pd, numpy as np
from scipy.stats import poisson
WORK = 'work'
dec = lambda o: np.where(o > 0, 1 + o / 100, 1 + 100 / np.abs(o))
imp = lambda x: np.where(x < 0, -x / (-x + 100), 100 / (x + 100))
ll = lambda p, y: float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
lg = lambda p: np.log(p / (1 - p)); sg = lambda x: 1 / (1 + np.exp(-x))
pr = pd.read_pickle(f'{WORK}/nhl_prop_lines.pkl')
pr = pr[pr.actual.notna() & (pr.actual != pr.line) & pr.main].copy()
PROJ = {'points': 'p_p', 'assists': 'a_p', 'shots_on_goal': 'sog_p', 'blocked_shots': 'blk_p'}
pr['lam'] = [getattr(r, PROJ[r.stat]) for r in pr.itertuples()]
pr['p_model'] = (1 - poisson.cdf(np.floor(pr.line), pr.lam)).clip(0.02, 0.98)
pr['over'] = (pr.actual > pr.line).astype(int)
for (k, b), x in pr.groupby(['stat', 'book']):
    if len(x) < 300: continue
    o = {'n': len(x), 'over_rate': round(x.over.mean(), 3), 'll_model': round(ll(x.p_model, x.over), 4), 'll_book': round(ll(x.p1, x.over), 4)}
    for thr in (0.04, 0.08):
        ov = x[x.p_model - x.p1 >= thr]; un = x[x.p1 - x.p_model >= thr]
        r = np.concatenate([ov.over * dec(ov.o) - 1, (1 - un.over) * dec(un.o2) - 1]); o[f'roi{int(thr*100)}'] = [len(r), round(float(r.mean()), 3) if len(r) else None]
    tr = x[x.yr <= 2025]; te = x[x.yr >= 2026]
    if len(tr) > 200 and len(te) > 200:
        w = min(((ll(sg((1 - w) * lg(tr.p1) + w * lg(tr.p_model)), tr.over), w) for w in np.linspace(0, .6, 13)))[1]
        pb = sg((1 - w) * lg(te.p1) + w * lg(te.p_model)); ov = te[pb - te.p1 >= .03]; un = te[te.p1 - pb >= .03]
        r = np.concatenate([ov.over * dec(ov.o) - 1, (1 - un.over) * dec(un.o2) - 1])
        o['blend_w'] = round(float(w), 2); o['blend_test'] = [len(r), round(float(r.mean()), 3) if len(r) else None, round(ll(te.p1, te.over), 4), round(ll(pb, te.over), 4)]
    print(k, b, o)
# ---- yes markets
Y = pd.read_pickle(f'{WORK}/nhl_prop_yes.pkl'); Y = Y[Y.player_id.notna() & Y.o.notna()].copy()
sk = pd.read_pickle(f'{WORK}/nhl_proj.pkl')
lam_game = sk.groupby('game_id').g_p.sum()
Y['lam_tot'] = Y.gid.map(lam_game)
Y['p_imp'] = imp(Y.o)
for t, x in Y.groupby('type'):
    if t == 'Anytime Goalscorer': p = 1 - np.exp(-x.g_p); y = (x.goals >= 1)
    elif t == 'To Score 2+ Goals': p = 1 - poisson.cdf(1, x.g_p); y = (x.goals >= 2)
    else:
        p = x.g_p / x.lam_tot * (1 - np.exp(-x.lam_tot)); y = None
    if y is None:
        continue
    x = x.assign(p=p.values, y=y.astype(int).values)
    print(t, 'n', len(x), 'hit', x.y.mean().round(3), 'model mean', x.p.mean().round(3), 'book implied mean', x.p_imp.mean().round(3),
          'll model', round(ll(x.p.clip(.005, .995), x.y), 4), 'll book', round(ll(x.p_imp.clip(.005, .995), x.y), 4))
    for thr in (0.0, 0.03, 0.06):
        b = x[x.p - x.p_imp >= thr]; r = b.y * dec(b.o) - 1
        print('   bet when model beats the price by', thr, len(b), round(float(r.mean()), 3) if len(b) else None)
# first goal: need who scored first; skip unless available
S = pd.read_pickle(f'{WORK}/nhl_prop_saves.pkl'); S = S[S.player_id.notna() & S.sv.notna()]
print('saves lines', len(S), 'over rate', (S.sv > S.line).mean().round(3))
