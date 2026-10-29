"""NBA player props for the 1st quarter and 1st half: points, rebounds and assists.

A player's 1st-quarter (1st-half) line = his full-game projection (nba_proj.pkl, what the site projects) times the share
of the game he plays in that part, which depends mostly on whether he starts: starters open the 1st quarter and close
the half, bench players come in later. share = b0 + b1*start_rate + b2*minutes/36 + b3*start_rate*minutes/36, fit on
2020-21 to 2023-24 and checked on 2024-25 and 2025-26. Then a player's own history: the ratio of what he has done in
that part to what the shares expected, shrunk toward 1 (tau, fit). Counts are negative binomial around that mean,
dispersion fit by maximum likelihood; the check reports how often 1+/2+/... milestones hit against the chance given.
Points come in ones, twos and threes, which a negative binomial gets wrong (it puts too much on exactly 1 point), and
bench players often sit the whole 1st quarter, so each threshold gets its own logistic curve in log(mean):
P(X >= t) = 1 / (1 + exp(-(a + b ln m + c ln^2 m))). The negative binomial fit is kept for comparison.
The player-history ratio barely helps (it is reported, not used), so the site needs only the shares.
-> work/nba_player_periods.json"""
import json, numpy as np, pandas as pd
from scipy.stats import nbinom
from scipy.optimize import minimize_scalar
WORK = '/home/claude/sports/work'
d = pd.read_pickle(f'{WORK}/nba_proj.pkl')
d = d[(d.season >= 2021) & d.played & (d['min'] > 0)][['game_id', 'season', 'athlete_id', 'starter', 'started_prev', 'min', 'min_proj', 'pts', 'reb', 'ast',
                                                     'pts_proj', 'reb_proj', 'ast_proj', 't']].copy()
Q = pd.read_pickle(f'{WORK}/nba_qscores.pkl'); PQ = pd.read_pickle(f'{WORK}/nba_pq.pkl')
d = d[d.game_id.isin(set(pd.to_numeric(Q.game_id)))]
d['athlete_id'] = d.athlete_id.astype(float)
d = d.merge(PQ, on=['game_id', 'athlete_id'], how='left').fillna({c: 0 for c in PQ.columns if c not in ('game_id', 'athlete_id')})
d = d.sort_values(['athlete_id', 't'])
d['S'] = d.started_prev.clip(0, 1); d['M'] = d.min_proj / 36
TR, TE = d.season <= 2024, d.season >= 2025
print('player-games', len(d), 'train', int(TR.sum()), 'test', int(TE.sum()))
STATS, PARTS = ['pts', 'reb', 'ast'], ['q1', 'h1']
THR = {'pts': [2, 4, 6, 8, 10, 12, 15], 'reb': [1, 2, 3, 4, 5, 6], 'ast': [1, 2, 3, 4, 5]}
X = lambda z: np.column_stack([np.ones(len(z)), z.S, z.M, z.S * z.M])


def irls(A, y, it=25):
    w = np.zeros(A.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-(A @ w))); W = np.clip(p * (1 - p), 1e-6, None)
        w = w + np.linalg.solve(A.T @ (A * W[:, None]) + 1e-6 * np.eye(A.shape[1]), A.T @ (y - p))
    return w
out = {'fit_seasons': [2021, 2024], 'check_seasons': [2025, 2026], 'model': {}}
for part in PARTS:
    for k in STATS:
        y = d[f'{part}_{k}']; base = d[f'{k}_proj']
        tr = d[TR]
        beta = np.linalg.lstsq(X(tr) * tr[f'{k}_proj'].values[:, None], tr[f'{part}_{k}'], rcond=None)[0]
        d['e0'] = (X(d) @ beta).clip(0.02, 1) * base
        # his own history in this part: observed over expected before this game, shrunk toward 1 by tau (in expected units)
        g = d.groupby('athlete_id')
        d['O'] = g[f'{part}_{k}'].transform(lambda s: s.shift().fillna(0).cumsum()); d['E'] = g['e0'].transform(lambda s: s.shift().fillna(0).cumsum())
        def dev(tau, z):
            mu = (z.e0 * (z.O + tau) / (z.E + tau)).clip(0.01)
            yy = z[f'{part}_{k}']
            return float((2 * (np.where(yy > 0, yy * np.log(np.maximum(yy, 1e-9) / mu), 0) - (yy - mu))).mean())   # Poisson deviance
        taus = [1, 3, 10, 30, 100, 300, 1e9]
        dv = {t: dev(t, d[TR]) for t in taus}
        tau = min(dv, key=dv.get)
        d['e1'] = (d.e0 * (d.O + tau) / (d.E + tau)).clip(0.01)
        # negative binomial dispersion r (var = mu + mu^2 / r) by maximum likelihood on the fit seasons, around the shares alone
        z = d[TR]
        nll = lambda lr: -float(nbinom.logpmf(z[f'{part}_{k}'].round().astype(int), np.exp(lr), np.exp(lr) / (np.exp(lr) + z.e0)).sum())
        r = float(np.exp(minimize_scalar(nll, bounds=(-3, 6), method='bounded').x))
        logit = {}
        TOP = {('q1', 'pts'): 20, ('h1', 'pts'): 35, ('q1', 'reb'): 8, ('h1', 'reb'): 12, ('q1', 'ast'): 8, ('h1', 'ast'): 10}[(part, k)]
        if True:                                         # one logistic curve per threshold (also fixes bench players who miss the quarter)
            for t in range(1, TOP + 1):
                logit[t] = irls(np.column_stack([np.ones(len(z)), np.log(z.e0), np.log(z.e0) ** 2]), (z[f'{part}_{k}'] >= t).astype(float).values)
        te = d[TE]
        def p_at_least(t, mu):
            ps = [1 / (1 + np.exp(-(np.column_stack([np.ones(len(mu)), np.log(mu), np.log(mu) ** 2]) @ logit[u]))) for u in range(1, t + 1)]
            return np.minimum.reduce(ps)                 # never more likely to reach t than any lower number
        cal = []
        for t in THR[k] if part == 'h1' or k != 'pts' else THR[k][:5]:
            p = p_at_least(t, te.e0.values)
            for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
                m = (p >= lo) & (p < hi)
                if m.sum() >= 200:
                    cal.append([f'{t}+', f'{lo:.1f}-{min(hi, 1):.1f}', int(m.sum()), round(float(p[m].mean()), 3), round(float((te[f'{part}_{k}'][m] >= t).mean()), 3)])
        out['model'][f'{part}_{k}'] = {'share': [round(float(b), 4) for b in beta], 'tau_best': tau if tau < 1e8 else None, 'nb_r': round(r, 3),
                                       'logit': {str(t): [round(float(v), 5) for v in c] for t, c in logit.items()} or None,
                                       'check': {'mae_share_only': round(float((te[f'{part}_{k}'] - te.e0).abs().mean()), 3),
                                                 'mae_with_history': round(float((te[f'{part}_{k}'] - te.e1).abs().mean()), 3),
                                                 'mean_actual': round(float(te[f'{part}_{k}'].mean()), 3), 'mean_model': round(float(te.e0.mean()), 3),
                                                 'deviance_by_tau': {str(t): round(v, 4) for t, v in dv.items()}, 'milestones': cal}}
        print(part, k, 'share', out['model'][f'{part}_{k}']['share'], 'tau', tau, 'r', round(r, 2), {kk: v for kk, v in out['model'][f'{part}_{k}']['check'].items() if kk not in ('milestones', 'deviance_by_tau')})
        for c in cal:
            print('     ', c)
# typical shares for a 34-minute starter and a 20-minute bench player, for the notes
for part in PARTS:
    for k in STATS:
        b = out['model'][f'{part}_{k}']['share']
        out['model'][f'{part}_{k}']['typical'] = {'starter_34': round(b[0] + b[1] + b[2] * 34 / 36 + b[3] * 34 / 36, 3), 'bench_20': round(b[0] + b[2] * 20 / 36, 3)}
# the site's numbers: shares and curves refit on the latest four seasons
out['site_fit_seasons'] = [2023, 2026]; out['site'] = {}
L4 = d.season >= 2023
for part in PARTS:
    for k in STATS:
        z = d[L4]
        beta = np.linalg.lstsq(X(z) * z[f'{k}_proj'].values[:, None], z[f'{part}_{k}'], rcond=None)[0]
        e0 = (X(z) @ beta).clip(0.02, 1) * z[f'{k}_proj']
        TOP = {('q1', 'pts'): 20, ('h1', 'pts'): 35, ('q1', 'reb'): 8, ('h1', 'reb'): 12, ('q1', 'ast'): 8, ('h1', 'ast'): 10}[(part, k)]
        A = np.column_stack([np.ones(len(z)), np.log(e0), np.log(e0) ** 2])
        out['site'][f'{part}_{k}'] = {'share': [round(float(v), 4) for v in beta],
                                      'logit': {str(t): [round(float(v), 5) for v in irls(A, (z[f'{part}_{k}'] >= t).astype(float).values)] for t in range(1, TOP + 1)}}
        print('site', part, k, out['site'][f'{part}_{k}']['share'])
json.dump(out, open(f'{WORK}/nba_player_periods.json', 'w'), indent=1)
