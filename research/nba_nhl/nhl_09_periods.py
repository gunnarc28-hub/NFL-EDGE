"""NHL period lines and a goal in the first 10 minutes.

Goals by period and the time of the first goal come from fastRhockey's play-by-play (raw/pbp/nhl, 2021-22 on; shootout
"goals" left out). Each game's expected goals come from its closing lines (work/nhl_games.pkl): the total and the
over/under prices give the expected total E (Poisson), the moneyline splits it between the teams. Then:
  goals by a team in period p ~ Poisson(share_p * its expected goals), the two teams independent,
  P(a goal in the first 10 minutes) = 1 - exp(-share_10 * E).
Independent Poissons put too many ties and goalless stretches in the 3rd period (trailing teams pull the goalie), so
each period's tie and over/under chances get a Platt curve on top. Shares and curves fit on 2021-22 to 2023-24,
checked on 2024-25 and 2025-26 (3-way period result, period totals, the first-10 chance by expected-total bins), then
refit on 2022-23 to 2025-26 for the site. -> work/nhl_periods.json"""
import json, math, numpy as np, pandas as pd
from scipy.stats import poisson
from scipy.optimize import brentq
RAW, WORK = '/home/claude/sports/raw/pbp/nhl', '/home/claude/sports/work'
rows = []
for yr in range(2022, 2028):
    d = pd.read_csv(f'{RAW}/play_by_play_{yr}.csv', usecols=['event_type', 'period', 'period_type', 'period_seconds', 'event_team_type', 'game_id', 'season_type'],
                    low_memory=False)
    games = d.game_id.dropna().astype('int64').unique()
    g = d[(d.event_type == 'GOAL') & (d.period_type != 'SHOOTOUT')].copy()
    g['game_id'] = g.game_id.astype('int64')
    for gid in games:
        rows.append({'game_id': int(gid)})
    G = g.assign(t=(g.period - 1) * 1200 + g.period_seconds)
    rows_g = G.groupby('game_id')
    print(yr, 'games', len(games), 'goals', len(g), flush=True)
    for gid, x in rows_g:
        r = {'game_id': int(gid), 'first_t': float(x.t.min())}
        for p in (1, 2, 3):
            r[f'p{p}h'] = int(((x.period == p) & (x.event_team_type == 'home')).sum()); r[f'p{p}a'] = int(((x.period == p) & (x.event_team_type == 'away')).sum())
        r['ot_h'] = int(((x.period > 3) & (x.event_team_type == 'home')).sum()); r['ot_a'] = int(((x.period > 3) & (x.event_team_type == 'away')).sum())
        rows.append(r)
P = pd.DataFrame(rows).groupby('game_id').max().reset_index()
for c in ('p1h', 'p1a', 'p2h', 'p2a', 'p3h', 'p3a', 'ot_h', 'ot_a'):
    P[c] = P[c].fillna(0)
P['first_t'] = P.first_t.fillna(1e9)                         # no goal at all
G = pd.read_pickle(f'{WORK}/nhl_games.pkl')
G['gid'] = pd.to_numeric(G.gid, errors='coerce')
d = G.merge(P, left_on='gid', right_on='game_id')
d = d[d.game_type.astype(str).isin(['R', '2', 'P', '3'])].dropna(subset=['total', 'over_odds', 'under_odds', 'ml_home', 'ml_away', 'hs'])
d = d[(d.p1h + d.p2h + d.p3h + d.ot_h == d.hs - (d.so & (d.hs > d.as_))) & (d.p1a + d.p2a + d.p3a + d.ot_a == d.as_ - (d.so & (d.as_ > d.hs)))]   # adds up
imp = lambda o: 100 / (o + 100) if o > 0 else -o / (-o + 100)


def expected_total(line, oo, uo):
    po = imp(oo) / (imp(oo) + imp(uo))
    k = math.floor(line) + 1 if line % 1 else line + 1                        # 6.5 -> 7+; a whole-number line: over is line + 1 or more
    f = lambda E: (1 - poisson.cdf(k - 1, E)) / ((1 - poisson.pmf(line, E)) if line % 1 == 0 else 1) - po
    return brentq(f, 0.5, 15)


def split(E, p_home):
    def f(r):
        h, a = poisson.pmf(np.arange(15), E * r), poisson.pmf(np.arange(15), E * (1 - r))
        m = np.outer(h, a)
        return float(np.tril(m, -1).sum() + 0.5 * np.trace(m)) - p_home
    return brentq(f, 0.02, 0.98)


d['E'] = [expected_total(l, o, u) for l, o, u in zip(d.total, d.over_odds, d.under_odds)]
d['p_home'] = [imp(h) / (imp(h) + imp(a)) for h, a in zip(d.ml_home, d.ml_away)]
d['r'] = [split(E, p) for E, p in zip(d.E, d.p_home)]
d['lh'], d['la'] = d.E * d.r, d.E * (1 - d.r)
TR, TE = d.season <= 2024, d.season >= 2025
print('games', len(d), 'train', int(TR.sum()), 'test', int(TE.sum()), '| mean E', round(d.E.mean(), 3), 'actual goals incl. OT', round((d.hs + d.as_).mean(), 3))


def fit(z):
    s = {f'p{p}': float((z[f'p{p}h'] + z[f'p{p}a']).sum() / z.E.sum()) for p in (1, 2, 3)}
    # first 10 minutes: maximum likelihood for 1 - exp(-s10 * E)
    y = (z.first_t < 600).astype(float).values; E = z.E.values
    nll = lambda s10: -float(np.sum(y * np.log(1 - np.exp(-s10 * E)) - (1 - y) * s10 * E))
    s['first10'] = float(min(np.linspace(0.05, 0.3, 501), key=nll))
    return s


LINES = (0.5, 1.5, 2.5, 3.5)


def raw(z, S, p):
    """Independent Poissons: P(home wins the period), P(tie), P(total over L)."""
    lh, la = (z.lh * S[f'p{p}']).values, (z.la * S[f'p{p}']).values
    k = np.arange(12)
    M = poisson.pmf(k[None, :], lh[:, None])[:, :, None] * poisson.pmf(k[None, :], la[:, None])[:, None, :]
    return np.tril(M, -1).sum((1, 2)), np.trace(M, axis1=1, axis2=2), {L: 1 - poisson.cdf(int(L), lh + la) for L in LINES}


lgt = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))


def platt(p, y, it=30):
    A = np.column_stack([np.ones(len(p)), lgt(p)]); w = np.array([0.0, 1.0])
    for _ in range(it):
        q = 1 / (1 + np.exp(-(A @ w))); W = np.clip(q * (1 - q), 1e-6, None)
        w = w + np.linalg.solve(A.T @ (A * W[:, None]) + 1e-8 * np.eye(2), A.T @ (y - q))
    return w


cal_ = lambda w, p: 1 / (1 + np.exp(-(w[0] + w[1] * lgt(p))))


def calibrate(z, S):
    """The 3rd period has fewer ties and more goals than independent Poissons give (teams chasing the game pull the
    goalie), and every period has a few more goalless... so each period's tie and over/under chances get a Platt curve."""
    C = {}
    for p in (1, 2, 3):
        win, tie, tot = raw(z, S, p)
        hg, ag = z[f'p{p}h'].values, z[f'p{p}a'].values
        C[f'p{p}'] = {'tie': platt(tie, (hg == ag).astype(float)), **{f'over_{L}': platt(tot[L], ((hg + ag) > L).astype(float)) for L in LINES}}
    return C


def probs(z, S, C, p):
    win, tie, tot = raw(z, S, p)
    t2 = cal_(C[f'p{p}']['tie'], tie)
    w2 = (1 - t2) * win / np.clip(1 - tie, 1e-9, None)
    return w2, t2, {L: cal_(C[f'p{p}'][f'over_{L}'], tot[L]) for L in LINES}


S = fit(d[TR]); C = calibrate(d[TR], S)
print('shares', {k: round(v, 4) for k, v in S.items()})
te = d[TE].reset_index(drop=True)
out = {'fit_seasons': [2022, 2024], 'check_seasons': [2025, 2026], 'fit': {k: round(v, 5) for k, v in S.items()},
       'fit_calibration': {p: {k: [round(float(x), 4) for x in w] for k, w in c.items()} for p, c in C.items()}, 'check': {}}
# ---- period checks on later seasons, before (independent Poissons) and after the calibration
for p in (1, 2, 3):
    hg, ag = te[f'p{p}h'].values, te[f'p{p}a'].values
    w0, t0, o0 = raw(te, S, p); w1, t1, o1 = probs(te, S, C, p)
    c = {'home_win': [round(float(w0.mean()), 4), round(float(w1.mean()), 4), round(float((hg > ag).mean()), 4)],
         'tie': [round(float(t0.mean()), 4), round(float(t1.mean()), 4), round(float((hg == ag).mean()), 4)],
         'var_over_mean_total': round(float((hg + ag).var() / (hg + ag).mean()), 3), 'corr_home_away': round(float(np.corrcoef(hg, ag)[0, 1]), 3)}
    for L in LINES:
        y = ((hg + ag) > L)
        c[f'over_{L}'] = [round(float(o0[L].mean()), 4), round(float(o1[L].mean()), 4), round(float(y.mean()), 4)]
        bins = pd.cut(o1[L], [0, .2, .3, .4, .5, .6, .7, .8, .9, 1])
        c[f'over_{L}_bins'] = [[str(i), int(m.sum()), round(float(o1[L][m].mean()), 3), round(float(y[m].mean()), 3)]
                               for i in bins.categories for m in [np.asarray(bins == i)] if m.sum() >= 100]
    bins = pd.cut(w1, [0, .25, .3, .35, .4, .45, .5, 1])
    c['home_win_bins'] = [[str(i), int(m.sum()), round(float(w1[m].mean()), 3), round(float((hg > ag)[m].mean()), 3)] for i in bins.categories for m in [np.asarray(bins == i)] if m.sum() >= 100]
    out['check'][f'p{p}'] = c
    print(f'P{p} [poisson, calibrated, actual]', {k: v for k, v in c.items() if 'bins' not in k})
    for k_ in ('over_1.5_bins', 'home_win_bins'):
        print('    ', k_, c[k_])
# ---- first 10 minutes by expected-total bins
pf = 1 - np.exp(-S['first10'] * te.E)
yf = (te.first_t < 600).astype(float)
b = pd.cut(pf, [0, .5, .55, .6, .65, .7, 1])
out['check']['first10'] = {'model': round(float(pf.mean()), 4), 'actual': round(float(yf.mean()), 4),
                           'bins': [[str(i), int(len(v)), round(float(pf[v.index].mean()), 4), round(float(yf[v.index].mean()), 4)] for i, v in pf.groupby(b, observed=True)]}
print('first 10', out['check']['first10'])
# ---- the site's numbers: refit on the latest four seasons
out['site_fit_seasons'] = [2023, 2026]
S4 = fit(d[d.season >= 2023]); C4 = calibrate(d[d.season >= 2023], S4)
out['site'] = {k: round(v, 5) for k, v in S4.items()}
out['site_calibration'] = {p: {k: [round(float(x), 4) for x in w] for k, w in c.items()} for p, c in C4.items()}
print('site', out['site'])
json.dump(out, open(f'{WORK}/nhl_periods.json', 'w'), indent=1)
d[['gid', 'season', 'E', 'lh', 'la', 'p1h', 'p1a', 'p2h', 'p2a', 'p3h', 'p3a', 'ot_h', 'ot_a', 'first_t']].to_pickle(f'{WORK}/nhl_periods.pkl')
