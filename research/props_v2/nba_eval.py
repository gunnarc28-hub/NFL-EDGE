"""NBA props against real DraftKings / ESPN BET main lines.
1) How the site's live chances do (raw model, the shipped blend) vs the book's no-vig chance, by market.
2) A market-anchored fair chance: logistic on logit(book) and the model's disagreement (+ line movement), fit 2023-24..2024-25,
   tested 2025-26 and this season; and the bets it would flag (ROI at the real prices), out of sample.
Writes work/nba_fair_fit.json."""
import pandas as pd, numpy as np, json
WORK = '/home/claude/research_work/work'
S = json.load(open('/home/claude/nfl/repo/pipeline/static/nba_model.json'))['props']
F = pd.read_pickle(f'{WORK}/nba_feat.pkl'); M = pd.read_pickle(f'{WORK}/nba_min.pkl')
L = pd.read_pickle(f'{WORK}/nba_ou.pkl')
STATS = ['pts', 'reb', 'ast', 'fg3m', 'stl', 'blk', 'tov']; COMBO = {'pra': ['pts', 'reb', 'ast'], 'pr': ['pts', 'reb'], 'pa': ['pts', 'ast'], 'ra': ['reb', 'ast']}
ALL = STATS + list(COMBO)
F = F.merge(M, on=['game_id', 'athlete_id'], how='inner')
F = F[F.n_prev >= 3]


def build(mins_col, hl=18, prior=150):
    out = pd.DataFrame({'game_id': F.game_id, 'athlete_id': F.athlete_id})
    w = F[f'minr_{hl}'] * np.minimum(F.n_prev, 30)
    for k in STATS:
        r = F[f'{k}_ew{hl}'] / F[f'minr_{hl}'].clip(lower=1)
        r = (r * w + F[k + '_lgpos'] * prior) / (w + prior)
        a, b = S['adj'][k]
        opp_f = (F[k + '_allow'] / F[k + '_lg']).fillna(1).clip(0.6, 1.6)
        out[k] = F[mins_col] * r * opp_f ** a * F.pace_f ** b
    for c, ps in COMBO.items():
        out[c] = out[ps].sum(axis=1)
    return out.melt(id_vars=['game_id', 'athlete_id'], var_name='k', value_name='proj')


QS = np.linspace(0, 1, 201)
DIST = {k: [(b['hi'], np.array(b['q'])) for b in S['dist'][k]] for k in ALL}


def p_over(k, proj, line):
    if proj is None or proj != proj or proj <= 0.05:
        return np.nan
    q = next((q for hi, q in DIST[k] if proj <= hi), DIST[k][-1][1])
    t = (line if line % 1 else line - 0.5) / proj
    return float(1 - np.interp(t, q, QS, left=0, right=1))


m = L[L.main & L.actual.notna() & (L.actual != L.line) & L.k.isin(ALL)].copy()
for tag, col in (('live', 'min_live'), ('new', 'min_new')):
    pj = build(col, *((18, 150) if tag == 'live' else (10, 50))).rename(columns={'proj': 'proj_' + tag})
    m = m.merge(pj, left_on=['event', 'athlete', 'k'], right_on=['game_id', 'athlete_id', 'k'], how='left', suffixes=('', '_' + tag)).drop(columns=['game_id_' + tag, 'athlete_id_' + tag], errors='ignore')
m = m[m.proj_live.notna()].copy()
m['pm_live'] = [p_over(k, p, l) for k, p, l in zip(m.k, m.proj_live, m.line)]
m['pm_new'] = [p_over(k, p, l) for k, p, l in zip(m.k, m.proj_new, m.line)]
m = m[m.pm_live.notna() & m.pm_new.notna()]
m['y'] = (m.actual > m.line).astype(int)
clip = lambda p: np.clip(p, 0.02, 0.98); lg = lambda p: np.log(clip(p) / (1 - clip(p)))
ll = lambda p, y: float(-np.mean(y * np.log(clip(p)) + (1 - y) * np.log(1 - clip(p))))
dec = lambda o: np.where(o > 0, 1 + o / 100, 1 + 100 / np.abs(o))
m['blend_live'] = 1 / (1 + np.exp(-((1 - m.k.map(S['blend']).fillna(0)) * lg(m.p1) + m.k.map(S['blend']).fillna(0) * lg(m.pm_live))))
m['mv'] = (m.line - m.line_open).fillna(0)
m['gap'] = (m.proj_new - m.line) / m.line.clip(lower=0.5)
FIT = m.season.isin([2024, 2025]); TEST = m.season.isin([2026, 2027])
print('main lines with a result and a projection:', len(m), m.groupby('season').size().to_dict())
print('over rate', round(m.y.mean(), 3), '| book no-vig mean', round(m.p1.mean(), 3), '| mean vig', round(m.vig.mean(), 4))


def roi(x, p, thr):
    ov = x[p - x.p1 >= thr]; un = x[x.p1 - p >= thr]
    r = np.concatenate([ov.y * dec(ov.o) - 1, (1 - un.y) * dec(un.o2) - 1])
    return len(r), (round(float(r.mean()), 4) if len(r) else None)


def fitlog(X, y, l2=1.0, it=60):
    X = np.column_stack([np.ones(len(X)), X]); w = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ w)); g = X.T @ (p - y) + l2 * np.r_[0, w[1:]]
        H = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.diag(np.r_[0, np.ones(len(w) - 1)])
        w -= np.linalg.solve(H, g)
    return w


out = {}
for k, x in m.groupby('k'):
    f, t = x[FIT.loc[x.index]], x[TEST.loc[x.index]]
    if len(f) < 500 or len(t) < 300:
        continue
    feats = lambda z: np.column_stack([lg(z.p1), lg(z.pm_new) - lg(z.p1), z.mv / z.line.clip(lower=0.5)])
    w = fitlog(feats(f), f.y.values)
    pf = 1 / (1 + np.exp(-(np.column_stack([np.ones(len(t)), feats(t)]) @ w)))
    r = {'n_test': len(t), 'over_rate': round(float(t.y.mean()), 3), 'book_mean': round(float(t.p1.mean()), 3),
         'll_book': round(ll(t.p1, t.y), 4), 'll_raw_live': round(ll(t.pm_live, t.y), 4), 'll_raw_new': round(ll(t.pm_new, t.y), 4),
         'll_blend_live': round(ll(t.blend_live, t.y), 4), 'll_fair_new': round(ll(pf, t.y), 4), 'w': np.round(w, 3).tolist(),
         'mae_line': round(float(np.abs(t.actual - t.line).mean()), 3), 'mae_proj_live': round(float(np.abs(t.actual - t.proj_live).mean()), 3),
         'mae_proj_new': round(float(np.abs(t.actual - t.proj_new).mean()), 3)}
    for thr in (0.02, 0.04, 0.06):
        r[f'roi_live_{thr}'] = roi(t, t.blend_live.values, thr); r[f'roi_fair_{thr}'] = roi(t, pf, thr)
    # always the under / always the over at the book's price
    r['roi_all_under'] = round(float(((1 - t.y) * dec(t.o2) - 1).mean()), 4); r['roi_all_over'] = round(float((t.y * dec(t.o) - 1).mean()), 4)
    out[k] = r
    print(k, r)
json.dump(out, open(f'{WORK}/nba_fair_fit.json', 'w'), indent=1)
m.to_pickle(f'{WORK}/nba_eval.pkl')
