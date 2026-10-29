"""NFL quarters and halves: points for each team in each part of the game, given the full-game spread and total.

A team's expected points = (total +/- spread) / 2, and in part s of the game
  expected points = E_team * (a_s + b_s * team's expected margin / 10)   (favorites lean on the 2nd half).
Football scores come in 3s and 7s from a handful of drives, which no simple count model gets right (a compound Poisson
put too many teams on zero), so each part uses the real distribution of a team's points among teams expected to score
about as much (ten bins by expected points, blended between the two nearest bins). The two teams are combined as
independent, then the chance of a tied quarter or half gets a Platt curve (independence overstates ties). Margins,
totals and moneylines come from that.
Fit on 2016-2022, checked on 2023-2025 (totals and spreads at lines around the fair number, ties, the favorite's
chance), then refit on 2021-2025 for the site. The 2nd half includes overtime; the 4th quarter does not.
-> work/nfl_segments.json (copied to pipeline/static/)"""
import json, math, numpy as np, pandas as pd
WORK = '/home/claude/nfl/work'
S = pd.read_csv('/home/claude/nfl/repo/pipeline/.cache/games.csv')[['game_id', 'season', 'game_type', 'spread_line', 'total_line', 'home_score', 'away_score']]
Q = pd.read_pickle(f'{WORK}/nfl_qscores.pkl')
d = S.merge(Q.drop(columns=['season']), on='game_id').dropna(subset=['spread_line', 'total_line', 'q4h', 'home_score'])
d = d[(d.q1h + d.q2h + d.q3h + d.q4h + d.ot_h == d.home_score) & (d.q1a + d.q2a + d.q3a + d.q4a + d.ot_a == d.away_score)]
SEG = {'q1': (['q1'], False), 'q2': (['q2'], False), 'q3': (['q3'], False), 'q4': (['q4'], False), 'h1': (['q1', 'q2'], False), 'h2': (['q3', 'q4'], True)}
rows = []
for side, sgn in (('h', 1), ('a', -1)):
    z = pd.DataFrame({'game_id': d.game_id, 'season': d.season, 'side': side, 'E': (d.total_line + sgn * d.spread_line) / 2, 'm': sgn * d.spread_line})
    for s, (qs, ot) in SEG.items():
        z[s] = sum(d[f'{q}{side}'] for q in qs) + (d[f'ot_{side}'] if ot else 0)
    rows.append(z)
T = pd.concat(rows, ignore_index=True)
K = 80
NB = 10


def fit(Z):
    par = {}
    for s_ in SEG:
        X = np.column_stack([Z.E, Z.E * Z.m / 10])
        a, b = np.linalg.lstsq(X, Z[s_], rcond=None)[0]
        e = ((a + b * Z.m / 10) * Z.E).values; y = Z[s_].clip(0, K).astype(int).values
        edges = np.quantile(e, np.linspace(0, 1, NB + 1))
        bins = []
        for i in range(NB):
            m_ = (e >= edges[i]) & (e <= edges[i + 1])
            cnt = np.bincount(y[m_], minlength=K + 1)[:K + 1].astype(float)
            cnt[:min(K, int(y[m_].max()) + 7) + 1] += 0.01             # a little smoothing, only over scores that can happen
            bins.append({'center': float(e[m_].mean()), 'pmf': (cnt / cnt.sum()).round(6).tolist()})
        par[s_] = {'a': float(a), 'b': float(b), 'bins': bins}
    return par


def team_pmf(p_, e):
    cs = [b['center'] for b in p_['bins']]
    if e <= cs[0]:
        return np.array(p_['bins'][0]['pmf'])
    if e >= cs[-1]:
        return np.array(p_['bins'][-1]['pmf'])
    k = int(np.searchsorted(cs, e)) - 1; w = (e - cs[k]) / (cs[k + 1] - cs[k])
    return (1 - w) * np.array(p_['bins'][k]['pmf']) + w * np.array(p_['bins'][k + 1]['pmf'])


def game_probs(p_, eh, ea):
    ph, pa = team_pmf(p_, eh), team_pmf(p_, ea)
    J = np.outer(ph, pa)
    marg = {}
    for dlt in range(-K, K + 1):
        v = float(np.trace(J, offset=-dlt))         # J[h, a] with h - a = dlt
        if v > 1e-12:
            marg[dlt] = v
    return marg, np.convolve(ph, pa)


lgt = lambda p: math.log(min(max(p, 1e-6), 1 - 1e-6) / (1 - min(max(p, 1e-6), 1 - 1e-6)))


def tie_curve(par, games):
    """Platt curve for P(tied part): independence overstates ties (scores trade back and forth less than chance)."""
    out_ = {}
    for s_ in SEG:
        p_ = par[s_]; X, y = [], []
        for g in games.itertuples():
            Eh, Ea = (g.total_line + g.spread_line) / 2, (g.total_line - g.spread_line) / 2
            eh = (p_['a'] + p_['b'] * g.spread_line / 10) * Eh; ea = (p_['a'] - p_['b'] * g.spread_line / 10) * Ea
            marg, _ = game_probs(p_, eh, ea)
            qs, ot = SEG[s_]
            H = sum(getattr(g, f'{q}h') for q in qs) + (g.ot_h if ot else 0); A = sum(getattr(g, f'{q}a') for q in qs) + (g.ot_a if ot else 0)
            X.append(lgt(marg.get(0, 1e-6))); y.append(float(H == A))
        X = np.column_stack([np.ones(len(X)), X]); y = np.array(y); w = np.array([0.0, 1.0])
        for _ in range(30):
            q = 1 / (1 + np.exp(-(X @ w))); W = np.clip(q * (1 - q), 1e-6, None)
            w = w + np.linalg.solve(X.T @ (X * W[:, None]) + 1e-8 * np.eye(2), X.T @ (y - q))
        out_[s_] = [round(float(w[0]), 4), round(float(w[1]), 4)]
    return out_


def adjust_ties(marg, w):
    t0 = marg.get(0, 0.0); t1 = 1 / (1 + math.exp(-(w[0] + w[1] * lgt(max(t0, 1e-6)))))
    k = (1 - t1) / max(1 - t0, 1e-9)
    return {m: (t1 if m == 0 else v * k) for m, v in marg.items()}


TR, TE = d.season <= 2022, d.season >= 2023
par = fit(T[T.season <= 2022])
TIE = tie_curve(par, d[TR])
print('tie curves', TIE)
print('fit', {k: (round(x['a'], 4), round(x['b'], 4)) for k, x in par.items()})
out = {'fit_seasons': [2016, 2022], 'check_seasons': [2023, 2025], 'fit': {k: {kk: v for kk, v in x.items() if kk != 'bins'} for k, x in par.items()}, 'fit_ties': TIE, 'check': {}}
te = d[TE & (d.season <= 2025)]
for s in SEG:
    p_ = par[s]
    rows = []
    for g in te.itertuples():
        Eh, Ea = (g.total_line + g.spread_line) / 2, (g.total_line - g.spread_line) / 2
        eh = (p_['a'] + p_['b'] * g.spread_line / 10) * Eh; ea = (p_['a'] - p_['b'] * g.spread_line / 10) * Ea
        marg, tot = game_probs(p_, eh, ea)
        marg = adjust_ties(marg, TIE[s])
        ks = np.array(sorted(marg)); pm = np.array([marg[k] for k in ks])
        mu, tmu = float((ks * pm).sum()), float((np.arange(len(tot)) * tot).sum())
        qs, ot = SEG[s]
        H = sum(getattr(g, f'{q}h') for q in qs) + (g.ot_h if ot else 0); A = sum(getattr(g, f'{q}a') for q in qs) + (g.ot_a if ot else 0)
        r = {'p_tie': float(pm[ks == 0].sum()), 'p_home': float(pm[ks > 0].sum()), 'tie': float(H == A), 'home': float(H > A), 'mu': mu, 'tmu': tmu,
             'm': H - A, 't': H + A}
        # lines around the fair numbers, as books would hang them (half points)
        for off in (-3, -1, 0, 1, 3):
            L = math.floor(tmu) + 0.5 + off
            r[f'pt{off}'] = float(tot[int(L + 0.5):].sum()); r[f'yt{off}'] = float(H + A > L)
            Lm = math.floor(mu) + 0.5 + off
            r[f'pm{off}'] = float(pm[ks > Lm].sum()); r[f'ym{off}'] = float(H - A > Lm)
        rows.append(r)
    R = pd.DataFrame(rows)
    def cal(pcols, ycols):
        p = pd.concat([R[c] for c in pcols], ignore_index=True); y = pd.concat([R[c] for c in ycols], ignore_index=True)
        b = pd.cut(p, [0, .2, .3, .4, .45, .5, .55, .6, .7, .8, 1])
        return [[str(i), int(len(v)), round(float(v.mean()), 3), round(float(y[v.index].mean()), 3)] for i, v in p.groupby(b, observed=True) if len(v) >= 50]
    c = {'n': len(R), 'mean_margin': [round(R.mu.mean(), 2), round(R.m.mean(), 2)], 'mean_total': [round(R.tmu.mean(), 2), round(R.t.mean(), 2)],
         'ties': [round(R.p_tie.mean(), 4), round(R.tie.mean(), 4)], 'home_wins': [round(R.p_home.mean(), 4), round(R.home.mean(), 4)],
         'totals': cal([f'pt{o}' for o in (-3, -1, 0, 1, 3)], [f'yt{o}' for o in (-3, -1, 0, 1, 3)]),
         'spreads': cal([f'pm{o}' for o in (-3, -1, 0, 1, 3)], [f'ym{o}' for o in (-3, -1, 0, 1, 3)])}
    out['check'][s] = c
    print(s, {k: v for k, v in c.items() if k not in ('totals', 'spreads')})
    print('    totals ', c['totals']); print('    spreads', c['spreads'])
out['site_fit_seasons'] = [2021, 2025]
out['site'] = fit(T[(T.season >= 2021) & (T.season <= 2025)])
out['site_ties'] = tie_curve(out['site'], d[(d.season >= 2021) & (d.season <= 2025)])
print('site', {k: (round(x['a'], 4), round(x['b'], 4)) for k, x in out['site'].items()})
json.dump(out, open(f'{WORK}/nfl_segments.json', 'w'), indent=1)
