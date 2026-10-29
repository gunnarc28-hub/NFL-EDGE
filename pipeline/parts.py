"""Quarters, halves and periods: each part of a game as a distribution the page can price any line against.

Every part becomes a small "model" the page reads with the same rules (site/assets/parts.js):
  NBA  {'k': 'n', 'm': mean home margin, 'sm': its spread, 't': mean total, 'st': its spread}   (rounded normals)
  NFL  {'k': 'e', 'm0': lowest margin, 'mp': [P(margin = m0), ...], 't0': lowest total, 'tp': [...]}   (real score shapes;
        chances in 1/10,000ths, tails under 1 in 5,000 left off)
  NHL  {'k': 'p', 'lh', 'la': expected goals, 'ph', 'pt': P(home wins), P(tie), 'po': {line: P(over)}, 'pb': P(home by 2+),
        'pa2': P(away by 2+)}   (Poissons with the research's calibration)
plus the fair numbers shown on the page. Fits: pipeline/static/{nba_parts,nfl_parts,nhl_periods}.json."""
import math, numpy as np
from scipy.stats import poisson

NBA_ORDER, NFL_ORDER, NHL_ORDER = ['q1', 'q2', 'q3', 'q4', 'h1', 'h2'], ['q1', 'q2', 'q3', 'q4', 'h1', 'h2'], ['p1', 'p2', 'p3']
LABEL = {'q1': '1st quarter', 'q2': '2nd quarter', 'q3': '3rd quarter', 'q4': '4th quarter', 'h1': '1st half', 'h2': '2nd half',
         'p1': '1st period', 'p2': '2nd period', 'p3': '3rd period'}
ncdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
lgt = lambda p: math.log(min(max(p, 1e-6), 1 - 1e-6) / (1 - min(max(p, 1e-6), 1 - 1e-6)))
sgm = lambda x: 1 / (1 + math.exp(-x))
half = lambda x: math.floor(x) + 0.5          # the half-point line just above x


def _summary(p_gt, p_eq, m_mean, t_mean, t_over):
    """Fair numbers for the page: the half-point spread nearest a coin flip, the total likewise, and the moneyline."""
    best = min((half(m_mean) + k for k in range(-6, 7)), key=lambda L: abs(p_gt(L) - 0.5))
    tl = min((half(t_mean) + k for k in range(-8, 9)), key=lambda L: abs(t_over(L) - 0.5))
    ph, pt = p_gt(0), p_eq(0)
    return {'fl': -best, 'ft': tl, 'ph': round(ph, 4), 'pt': round(pt, 4)}           # fl: the home team's spread (negative = favored)


def nba(margin, total, P):
    out = {}
    for s in NBA_ORDER:
        c = P[s]
        m = c['margin'][0] + c['margin'][1] * margin; t = c['total'][0] + c['total'][1] * total
        sm, st = c['k_margin'] * math.sqrt(max(t, 1)), c['k_total'] * math.sqrt(max(t, 1))
        p_gt = lambda L: 1 - ncdf((L + 0.5 - m) / sm) if float(L).is_integer() else 1 - ncdf((L - m) / sm)
        p_eq = lambda L: ncdf((L + 0.5 - m) / sm) - ncdf((L - 0.5 - m) / sm) if float(L).is_integer() else 0.0
        t_over = lambda L: 1 - ncdf((L - t) / st)
        out[s] = {'k': 'n', 'm': round(m, 2), 'sm': round(sm, 3), 't': round(t, 2), 'st': round(st, 3), **_summary(p_gt, p_eq, m, t, t_over)}
    return out


def _team_pmf(c, e):
    cs = [b['center'] for b in c['bins']]
    if e <= cs[0]:
        return np.array(c['bins'][0]['pmf'])
    if e >= cs[-1]:
        return np.array(c['bins'][-1]['pmf'])
    k = int(np.searchsorted(cs, e)) - 1; w = (e - cs[k]) / (cs[k + 1] - cs[k])
    return (1 - w) * np.array(c['bins'][k]['pmf']) + w * np.array(c['bins'][k + 1]['pmf'])


def nfl(spread_home, total, P):
    """spread_home: the home team's expected margin (positive = favored); total: expected points."""
    out = {}
    Eh, Ea = (total + spread_home) / 2, (total - spread_home) / 2
    for s in NFL_ORDER:
        c, w = P['parts'][s], P['ties'][s]
        ph_, pa_ = _team_pmf(c, (c['a'] + c['b'] * spread_home / 10) * Eh), _team_pmf(c, (c['a'] - c['b'] * spread_home / 10) * Ea)
        K = len(ph_) - 1
        J = np.outer(ph_, pa_)
        mp = np.array([float(np.trace(J, offset=-d)) for d in range(-K, K + 1)])          # margin -K..K
        t0 = mp[K]; t1 = sgm(w[0] + w[1] * lgt(max(t0, 1e-6)))                            # fewer ties than independence gives
        mp = mp * (1 - t1) / max(1 - t0, 1e-9); mp[K] = t1
        tp = np.convolve(ph_, pa_)
        def central(v):                                   # drop tails worth less than 1 in 5,000 on each side
            c = np.cumsum(v); return int(np.searchsorted(c, 2e-4)), int(np.searchsorted(c, c[-1] - 2e-4))
        lo, hi = central(mp); tlo, thi = central(tp)
        mpr = [int(round(float(x) * 1e4)) for x in mp[lo:hi + 1]]; tpr = [int(round(float(x) * 1e4)) for x in tp[tlo:thi + 1]]   # in 1/10,000ths
        m0 = int(lo - K)
        marg = dict(zip(range(m0, m0 + len(mpr)), [x / 1e4 for x in mpr])); tot = dict(zip(range(int(tlo), int(tlo) + len(tpr)), [x / 1e4 for x in tpr]))
        p_gt = lambda L: sum(v for k, v in marg.items() if k > L); p_eq = lambda L: marg.get(int(L), 0.0) if float(L).is_integer() else 0.0
        t_over = lambda L: sum(v for k, v in tot.items() if k > L)
        mm = sum(k * v for k, v in marg.items()); tm = sum(k * v for k, v in tot.items())
        out[s] = {'k': 'e', 'm0': m0, 'mp': mpr, 't0': int(tlo), 'tp': tpr, 'm': round(mm, 2), 't': round(tm, 2), **_summary(p_gt, p_eq, mm, tm, t_over)}
    return out


def nhl(lam_h, lam_a, P):
    out = {}
    for s in NHL_ORDER:
        sh, C = P['share'][s], P['calibration'][s]
        lh, la = lam_h * sh, lam_a * sh
        k = np.arange(13)
        M = np.outer(poisson.pmf(k, lh), poisson.pmf(k, la))
        win, tie = float(np.tril(M, -1).sum()), float(np.trace(M))
        t2 = sgm(C['tie'][0] + C['tie'][1] * lgt(tie))
        ph = (1 - t2) * win / max(1 - tie, 1e-9)
        by2h, by2a = float(np.tril(M, -2).sum()), float(np.triu(M, 2).sum())
        sc = (1 - t2) / max(1 - tie, 1e-9)
        po = {}
        for L in (0.5, 1.5, 2.5, 3.5):
            p0 = 1 - float(poisson.cdf(int(L), lh + la))
            po[str(L)] = round(sgm(C[f'over_{L}'][0] + C[f'over_{L}'][1] * lgt(p0)), 4)
        tl = min((0.5, 1.5, 2.5, 3.5), key=lambda L: abs(po[str(L)] - 0.5))
        out[s] = {'k': 'p', 'lh': round(lh, 3), 'la': round(la, 3), 'ph': round(ph, 4), 'pt': round(t2, 4), 'po': po,
                  'pb': round(by2h * sc, 4), 'pa2': round(by2a * sc, 4), 'ft': tl, 'fl': -0.5 if ph > 1 - ph - t2 else 0.5}
    return out


def first10(lam_h, lam_a, P):
    return round(1 - math.exp(-P['share']['first10'] * (lam_h + lam_a)), 4)


def p_part(m, kind, side, line):
    """The model's chance and push chance for one side of a part line, the same rules the page uses.
    kind 'spread' (side 'h' or 'a', line from that team's view), 'total' (side 'O'/'U'), 'ml' (side 'h'/'a'/'draw')."""
    if m['k'] == 'p':
        ph, pt = m['ph'], m['pt']; pa = 1 - ph - pt
        if kind == 'ml':
            return {'h': ph, 'a': pa, 'draw': pt}[side], 0.0
        if kind == 'total':
            p = m['po'].get(str(float(line)))
            return (None, 0.0) if p is None else ((p if side == 'O' else 1 - p), 0.0)
        L = line if side == 'h' else line                                         # +0.5 / -0.5 / +1.5 / -1.5 from that team's view
        win, by2 = (ph, m['pb']) if side == 'h' else (pa, m['pa2'])
        lose = 1 - win - pt
        if L == -0.5: return win, 0.0
        if L == 0.5: return win + pt, 0.0
        if L == -1.5: return by2, 0.0
        if L == 1.5: return 1 - ((m['pa2'] if side == 'h' else m['pb'])), 0.0
        return None, 0.0
    if m['k'] == 'n':
        gt = lambda x, mu, sd: (1 - ncdf((x + 0.5 - mu) / sd)) if float(x).is_integer() else (1 - ncdf((x - mu) / sd))
        eq = lambda x, mu, sd: (ncdf((x + 0.5 - mu) / sd) - ncdf((x - 0.5 - mu) / sd)) if float(x).is_integer() else 0.0
        if kind == 'total':
            o, pu = gt(line, m['t'], m['st']), eq(line, m['t'], m['st'])
            return (o if side == 'O' else 1 - o - pu), pu
        mu = m['m'] if side == 'h' else -m['m']
        if kind == 'ml':
            w, t = gt(0, mu, m['sm']), eq(0, mu, m['sm'])
            return w, t
        x = -line                                                                  # covers when margin + line > 0
        return gt(x, mu, m['sm']), eq(x, mu, m['sm'])
    # empirical
    marg = {m['m0'] + i: v / 1e4 for i, v in enumerate(m['mp'])}; tot = {m['t0'] + i: v / 1e4 for i, v in enumerate(m['tp'])}
    if kind == 'total':
        o = sum(v for k, v in tot.items() if k > line); pu = tot.get(int(line), 0.0) if float(line).is_integer() else 0.0
        return (o if side == 'O' else 1 - o - pu), pu
    sg = 1 if side == 'h' else -1
    if kind == 'ml':
        return sum(v for k, v in marg.items() if sg * k > 0), marg.get(0, 0.0)
    x = -line
    w = sum(v for k, v in marg.items() if sg * k > x); pu = sum(v for k, v in marg.items() if sg * k == x)
    return w, pu


def book_side(b, home, away):
    """The book's lines for one part, seen from the home team: {'sp': [home line, home odds, away line, away odds],
    'tot': [line, over odds, under odds], 'ml': [home odds, away odds, draw odds]}."""
    out = {}
    sp = b.get('spread') or {}
    if home in sp or away in sp:
        h, a = sp.get(home) or [None, None], sp.get(away) or [None, None]
        hl = h[0] if h[0] is not None else (-a[0] if a[0] is not None else None)
        out['sp'] = [hl, h[1], -hl if hl is not None else None, a[1]]
    if b.get('total'):
        out['tot'] = list(b['total'])
    ml = b.get('ml') or {}
    if ml:
        out['ml'] = [ml.get(home), ml.get(away), ml.get('draw')]
    return out
