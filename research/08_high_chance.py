"""High-chance player milestones: how likely is a player to reach a sportsbook-style milestone (50+ yards, 4+ catches...)?
Builds outcome distributions conditional on the projection (2018-2023), tests the 80%+ picks on 2024-2025,
then writes production distributions from 2018-2025.
Writes repo/pipeline/static/prop_dist.json and repo/pipeline/static/high_chance_research.json"""
import json, numpy as np, pandas as pd

d = pd.read_pickle('work/player_hist_features.pkl')
PR = json.load(open('work/player_research.json'))
MODELS = PR['models']
SPEC = {
    'rec_yds': {'pos': ['WR', 'TE'], 'y': 'receiving_yards', 'ladder': [30, 40, 50, 60, 70, 80, 90, 100], 'grid': list(range(0, 205, 5))},
    'receptions': {'pos': ['WR', 'TE', 'RB'], 'y': 'receptions', 'ladder': [3, 4, 5, 6, 7, 8], 'grid': list(range(0, 16))},
    'rush_yds': {'pos': ['RB'], 'y': 'rushing_yards', 'ladder': [40, 50, 60, 70, 80, 90, 100], 'grid': list(range(0, 205, 5))},
    'pass_yds': {'pos': ['QB'], 'y': 'passing_yards', 'ladder': [175, 200, 225, 250, 275, 300], 'grid': list(range(0, 460, 10))},
}
P_MIN = 0.80


def eligible(df, key):
    base = df.n_prior >= 3
    if key == 'pass_yds':
        return base & (df.position == 'QB') & (df.pg_attempts >= 25)
    if key == 'rush_yds':
        return base & (df.position == 'RB') & (df.avg_carry_share >= 0.45)
    return base & df.position.isin(SPEC[key]['pos']) & ((df.avg_target_share >= 0.18) | (df.pg_targets >= 6))


def predict(df, key):
    m = MODELS[key]
    X = df[m['feats']]
    ok = X.notna().all(axis=1)
    out = pd.Series(np.nan, index=df.index)
    out[ok] = np.c_[X[ok].values, np.ones(ok.sum())] @ np.array(m['beta'])
    return out


def build_dist(df, key, nbins=20):
    y = df[SPEC[key]['y']].values; p = df['pred'].values
    edges = np.quantile(p, np.linspace(0, 1, nbins + 1))
    bins = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mk = (p >= lo) & (p <= hi)
        yy = y[mk]
        bins.append({'lo': float(lo), 'hi': float(hi), 'center': float(np.median(p[mk])), 'n': int(mk.sum()),
                     'surv': [float((yy >= t).mean()) for t in SPEC[key]['grid']]})
    return {'grid': SPEC[key]['grid'], 'bins': bins}


def chance(dist, proj, t):
    """P(stat >= t) for a player projected at proj, interpolating across neighbouring projection bins and the grid."""
    grid = dist['grid']; bins = dist['bins']
    cs = [b['center'] for b in bins]

    def surv(b):
        if t <= grid[0]:
            return b['surv'][0]
        if t >= grid[-1]:
            return b['surv'][-1]
        j = np.searchsorted(grid, t) - 1
        w = (t - grid[j]) / (grid[j + 1] - grid[j])
        return b['surv'][j] * (1 - w) + b['surv'][j + 1] * w
    if proj <= cs[0]:
        return surv(bins[0])
    if proj >= cs[-1]:
        return surv(bins[-1])
    k = np.searchsorted(cs, proj) - 1
    w = (proj - cs[k]) / (cs[k + 1] - cs[k])
    return surv(bins[k]) * (1 - w) + surv(bins[k + 1]) * w


rows = {}
for key in SPEC:
    e = d[eligible(d, key)].copy()
    e['pred'] = predict(e, key)
    e = e.dropna(subset=['pred', SPEC[key]['y']])
    rows[key] = e

# ---------------- out-of-sample test: distributions from 2018-2023, picks on 2024-2025 ----------------
picks = []
for key, e in rows.items():
    dist = build_dist(e[e.season <= 2023], key)
    te = e[e.season >= 2024]
    for idx, r in te.iterrows():
        best = None
        for t in SPEC[key]['ladder']:
            pch = chance(dist, r.pred, t)
            if pch >= P_MIN:
                best = (t, pch)
        if best:
            picks.append({'season': int(r.season), 'week': int(r.week), 'player': r.player_id, 'key': key, 't': best[0], 'p': best[1],
                          'hit': int(r[SPEC[key]['y']] >= best[0]), 'game_id': r.game_id})
pk = pd.DataFrame(picks)
# one pick per player-game: the most likely; yards before catches on ties
pk['ord'] = pk.key.map({'rec_yds': 0, 'rush_yds': 0, 'pass_yds': 0, 'receptions': 1})
pk = pk.sort_values(['p', 'ord'], ascending=[False, True]).drop_duplicates(['season', 'week', 'player'])
summary = {'all': {'n': int(len(pk)), 'expected': float(pk.p.mean()), 'hit': float(pk.hit.mean())}}
for lo, hi in ((0.80, 0.85), (0.85, 0.90), (0.90, 1.01)):
    s = pk[(pk.p >= lo) & (pk.p < hi)]
    summary[f'{int(lo*100)}-{int(min(hi,1)*100)}'] = {'n': int(len(s)), 'expected': float(s.p.mean()), 'hit': float(s.hit.mean())}
top = pk.sort_values('p', ascending=False).groupby(['season', 'week']).head(12)
summary['top12_per_week'] = {'n': int(len(top)), 'expected': float(top.p.mean()), 'hit': float(top.hit.mean())}
by_key = {k: {'n': int(len(s)), 'expected': float(s.p.mean()), 'hit': float(s.hit.mean())} for k, s in pk.groupby('key')}
summary['by_type'] = by_key
# three-leg parlays of top picks from different games, same week: how often do all three hit?
par = []
for (s, w), g in top.groupby(['season', 'week']):
    g = g.drop_duplicates('game_id').head(3)
    if len(g) == 3:
        par.append({'exp': float(np.prod(g.p)), 'hit': int(g.hit.all())})
par = pd.DataFrame(par)
summary['parlay3'] = {'n': int(len(par)), 'expected': float(par.exp.mean()), 'hit': float(par.hit.mean())}
print(json.dumps(summary, indent=1))

# ---------------- production distributions: all of 2018-2025 ----------------
prod = {key: build_dist(e, key) for key, e in rows.items()}
json.dump({'p_min': P_MIN, 'ladders': {k: v['ladder'] for k, v in SPEC.items()}, 'dists': prod},
          open('repo/pipeline/static/prop_dist.json', 'w'))
json.dump(summary, open('repo/pipeline/static/high_chance_research.json', 'w'), indent=1)
