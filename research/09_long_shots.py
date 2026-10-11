"""Long shots: anytime TD, 2+ TDs, first TD scorer, 100-yard and 300-yard games.

Everything is tested on 2021-2025, one season at a time, using only what the model could have known:
- Touchdown markets: the logistic touchdown model is fit on the seasons before each test season (walk-forward).
- Yardage milestones: outcome distributions conditional on the projection. Production distributions use every season,
  so each test season is scored by distributions built without it (leave-one-season-out).
A logistic rescaling of a market's chances is kept only if it made held-out seasons more accurate (Brier score),
with each season rescaled by a fit on the other four. Then the weekly long-shot selection is replayed on 2021-2025.

Writes repo/pipeline/static/longshot_model.json and repo/pipeline/static/longshot_research.json"""
import json, numpy as np, pandas as pd, warnings
from sklearn.linear_model import LogisticRegression
warnings.filterwarnings('ignore')

d = pd.read_pickle('work/player_hist_features.pkl')
PR = json.load(open('work/player_research.json'))
TEST = list(range(2021, 2026))

# which plays count as long shots each week: chance window, how many to show, and at most how many per game
RULES = {
    'atd': {'lo': 0.20, 'hi': 0.48, 'top': 10, 'per_game': 2},
    'ftd': {'lo': 0.06, 'hi': 1.00, 'top': 6, 'per_game': 1},
    'td2': {'lo': 0.08, 'hi': 1.00, 'top': 4, 'per_game': 1},
    'yds100': {'lo': 0.15, 'hi': 0.48, 'top': 6, 'per_game': 2},
    'pass300': {'lo': 0.15, 'hi': 0.48, 'top': 3, 'per_game': 1},
}


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def cal_fit(kind, p, y):
    """'linear': logit(q) = a + b*logit(p).  'curved': adds a squared term, which lets the very top and bottom flatten."""
    L = logit(p)
    X = L.reshape(-1, 1) if kind == 'linear' else np.c_[L, L ** 2]
    lr = LogisticRegression(C=100.0).fit(X, y)
    return {'kind': kind, 'coef': [float(lr.intercept_[0])] + [float(c) for c in lr.coef_[0]]}


def cal_apply(c, p):
    if not c or c['kind'] == 'none':
        return p
    L = logit(p); k = c['coef']
    if c['kind'] == 'linear':
        z = k[0] + k[1] * L
    else:
        if k[2] < 0:
            L = np.minimum(L, -k[1] / (2 * k[2]))       # stay on the rising side of the curve
        z = k[0] + k[1] * L + k[2] * L ** 2
    return 1 / (1 + np.exp(-z))


def loso_cal(kind, p, y, s):
    """Rescale each season with a fit on the other seasons."""
    q = np.empty_like(p, dtype=float)
    for ts in np.unique(s):
        q[s == ts] = cal_apply(cal_fit(kind, p[s != ts], y[s != ts]), p[s == ts])
    return q


def calib(p, y, edges):
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mk = (p >= lo) & (p < hi)
        if mk.sum() >= 30:
            rows.append({'bucket': f'{int(round(lo * 100))}-{int(round(min(hi, 1) * 100))}%', 'n': int(mk.sum()),
                         'expected': float(p[mk].mean()), 'actual': float(y[mk].mean())})
    return rows


def brier(p, y):
    return float(np.mean((p - y) ** 2))


# ---------------- first touchdown of every game, 2018-2025 ----------------
fr = []
for y in range(2018, 2026):
    p = pd.read_csv(f'raw/pbp_{y}.csv.gz', usecols=['game_id', 'season_type', 'play_id', 'touchdown', 'td_player_id', 'td_team', 'total_line'], low_memory=False)
    p = p[p.season_type == 'REG']
    tds = p[(p.touchdown == 1) & p.td_team.notna()].sort_values(['game_id', 'play_id'])
    first = tds.groupby('game_id').head(1)[['game_id', 'td_player_id']].rename(columns={'td_player_id': 'first_td'})
    cnt = tds.groupby('game_id').size().rename('n_td')
    g = p.groupby('game_id').total_line.first().to_frame().join(cnt).fillna({'n_td': 0}).reset_index().merge(first, on='game_id', how='left')
    g['season'] = y
    fr.append(g)
G = pd.concat(fr, ignore_index=True)
print('games without a touchdown: %.2f%%' % (100 * (G.n_td == 0).mean()))

# ---------------- touchdown model ----------------
d['is_qb'] = (d.position == 'QB').astype(int)
d['is_rb'] = (d.position == 'RB').astype(int)
d['is_te'] = (d.position == 'TE').astype(int)
FEATS = ['pg_any_td', 'pg_rz_carries', 'pg_rz_targets', 'pg_carries', 'pg_targets', 'avg_carry_share', 'avg_target_share',
         'implied_tt', 'pg_rushing_yards', 'pg_receiving_yards', 'is_qb', 'is_rb', 'is_te']
FEAT_LABEL = {'pg_any_td': 'Share of games with a TD so far', 'pg_rz_carries': 'Carries inside the 10', 'pg_rz_targets': 'Targets inside the 10',
              'pg_carries': 'Carries per game', 'pg_targets': 'Targets per game', 'avg_carry_share': "Share of the team's carries",
              'avg_target_share': "Share of the team's targets", 'implied_tt': 'Team total from the betting line',
              'pg_rushing_yards': 'Rushing yards per game', 'pg_receiving_yards': 'Receiving yards per game',
              'is_qb': 'Quarterback', 'is_rb': 'Running back', 'is_te': 'Tight end'}


def td_eligible(df):
    return (df.n_prior >= 3) & df.position.isin(['QB', 'RB', 'WR', 'TE']) & (
        ((df.position == 'QB') & (df.pg_attempts >= 20)) | ((df.position != 'QB') & ((df.pg_carries >= 3) | (df.pg_targets >= 2.5))))


e = d[td_eligible(d)].copy()
for c in ['avg_carry_share', 'avg_target_share']:
    e[c] = e[c].fillna(0)
e = e.dropna(subset=FEATS + ['any_td'])
e['td_n'] = e.rushing_tds.fillna(0) + e.receiving_tds.fillna(0)


def fit(df):
    mu, sd = df[FEATS].mean(), df[FEATS].std().replace(0, 1)
    lr = LogisticRegression(C=1.0, max_iter=2000).fit(((df[FEATS] - mu) / sd).values, df.any_td.values)
    return {'mu': mu.to_dict(), 'sd': sd.to_dict(), 'coef': lr.coef_[0].tolist(), 'intercept': float(lr.intercept_[0]), 'feats': FEATS}


def p_td(m, df):
    z = ((df[m['feats']] - pd.Series(m['mu'])) / pd.Series(m['sd'])).values
    return 1 / (1 + np.exp(-(z @ np.array(m['coef']) + m['intercept'])))


wf = []
for s in TEST:
    m = fit(e[e.season < s])
    x = e[e.season == s].copy()
    x['p_atd'] = p_td(m, x)
    gt = G[(G.season < s) & G.total_line.notna()]
    b_, a_ = np.polyfit(gt.total_line, gt.n_td, 1)
    x = x.merge(G[['game_id', 'total_line', 'first_td']].rename(columns={'total_line': 'gtl'}), on='game_id', how='left')
    x['lamg'] = (b_ * x.gtl.fillna(44) + a_).clip(lower=2)
    x['td2'] = (x.td_n >= 2).astype(int)
    x['ftd'] = (x.first_td == x.player_id).astype(int)
    wf.append(x)
W = pd.concat(wf, ignore_index=True)

EDGES = {'atd': [0, .1, .2, .3, .4, .5, .6, 1.01], 'td2': [0, .05, .1, .15, .2, .3, 1.01], 'ftd': [0, .03, .06, .09, .12, .15, .2, 1.01],
         'rec_yds_100': [0, .1, .2, .3, .4, .5, 1.01], 'rush_yds_100': [0, .1, .2, .3, .4, .5, 1.01], 'pass_yds_300': [0, .1, .2, .3, .4, .5, 1.01]}
CAL = {}


def settle(mk, p, y, s):
    """Pick no rescaling, linear or curved: whichever scores best on held-out seasons."""
    opts = {'none': p, 'linear': loso_cal('linear', p, y, s), 'curved': loso_cal('curved', p, y, s)}
    scores = {k: brier(v, y) for k, v in opts.items()}
    kind = min(scores, key=scores.get)
    CAL[mk] = {'kind': kind, 'fit': (cal_fit(kind, p, y) if kind != 'none' else {'kind': 'none', 'coef': []}),
               'brier': scores, 'used': kind != 'none', 'raw': calib(p, y, EDGES[mk]), 'final': calib(opts[kind], y, EDGES[mk])}
    print(f"{mk:13s} Brier " + '  '.join(f'{k} {v:.5f}' for k, v in scores.items()) + f"  -> {kind}")
    return opts[kind]


s_ = W.season.values
W['atd_p'] = settle('atd', W.p_atd.values, W.any_td.values, s_)
W['lam'] = -np.log(1 - np.clip(W.atd_p, 1e-4, 0.97))
W['p_td2'] = 1 - np.exp(-W.lam) * (1 + W.lam)                 # Poisson: 2+ touchdowns at the same scoring rate
W['p_ftd'] = W.lam / W.lamg * (1 - np.exp(-W.lamg))           # his share of the game's expected touchdowns
W['td2_p'] = settle('td2', W.p_td2.values, W.td2.values, s_)
W['ftd_p'] = settle('ftd', W.p_ftd.values, W.ftd.values, s_)


# ---------------- 100-yard and 300-yard games ----------------
def y_eligible(df, key):
    base = df.n_prior >= 3
    if key == 'pass_yds':
        return base & (df.position == 'QB') & (df.pg_attempts >= 25)
    if key == 'rush_yds':
        return base & (df.position == 'RB') & (df.avg_carry_share >= 0.45)
    return base & df.position.isin(['WR', 'TE']) & ((df.avg_target_share >= 0.18) | (df.pg_targets >= 6))


def build_dist(df, ycol, grid, nbins=20):
    y = df[ycol].values; p = df['pred'].values
    edges = np.quantile(p, np.linspace(0, 1, nbins + 1)); bins = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mk = (p >= lo) & (p <= hi); yy = y[mk]
        bins.append({'center': float(np.median(p[mk])), 'surv': [float((yy >= t).mean()) for t in grid]})
    return {'grid': grid, 'bins': bins}


def chance(dist, proj, t):
    grid, bins = dist['grid'], dist['bins']; cs = [x['center'] for x in bins]

    def surv(bb):
        j = int(np.searchsorted(grid, t)) - 1; w = (t - grid[j]) / (grid[j + 1] - grid[j])
        return bb['surv'][j] * (1 - w) + bb['surv'][j + 1] * w
    if proj <= cs[0]:
        return surv(bins[0])
    if proj >= cs[-1]:
        return surv(bins[-1])
    k = int(np.searchsorted(cs, proj)) - 1; w = (proj - cs[k]) / (cs[k + 1] - cs[k])
    return surv(bins[k]) * (1 - w) + surv(bins[k + 1]) * w


YT = {}
for key, ycol, t, grid in (('rec_yds', 'receiving_yards', 100, list(range(0, 205, 5))), ('rush_yds', 'rushing_yards', 100, list(range(0, 205, 5))),
                           ('pass_yds', 'passing_yards', 300, list(range(0, 460, 10)))):
    mk = f'{key}_{t}'
    mdl = PR['models'][key]
    x = d[y_eligible(d, key)].dropna(subset=mdl['feats'] + [ycol]).copy()
    x['pred'] = np.c_[x[mdl['feats']].values, np.ones(len(x))] @ np.array(mdl['beta'])
    parts = []
    for s in TEST:
        dist = build_dist(x[x.season != s], ycol, grid)
        tt = x[x.season == s].copy()
        tt['p_raw'] = [chance(dist, v, t) for v in tt.pred]
        tt['hit'] = (tt[ycol] >= t).astype(int)
        parts.append(tt)
    L = pd.concat(parts, ignore_index=True)
    L['p'] = settle(mk, L.p_raw.values, L.hit.values, L.season.values)
    CAL[mk]['rate_by_season'] = {int(k): float(v) for k, v in x.groupby('season').apply(lambda g: (g[ycol] >= t).mean()).items()}
    YT[mk] = L
res = {'calibration': CAL, 'test_seasons': TEST}


# ---------------- replay the weekly selection on 2021-2025 ----------------
def select(df, rule, pcol='p'):
    x = df[(df[pcol] >= rule['lo']) & (df[pcol] < rule['hi'])].sort_values(pcol, ascending=False)
    x = x[x.groupby(['season', 'week', 'game_id']).cumcount() < rule['per_game']]
    return x[x.groupby(['season', 'week']).cumcount() < rule['top']]


yy = pd.concat([YT['rec_yds_100'], YT['rush_yds_100']], ignore_index=True)
sel = {'atd': (select(W.assign(p=W.atd_p), RULES['atd']), 'any_td'),
       'ftd': (select(W.assign(p=W.ftd_p), RULES['ftd']), 'ftd'),
       'td2': (select(W.assign(p=W.td2_p), RULES['td2']), 'td2'),
       'yds100': (select(yy, RULES['yds100']), 'hit'),
       'pass300': (select(YT['pass_yds_300'], RULES['pass300']), 'hit')}
backtest = {}
for mk, (x, yc) in sel.items():
    wk = x.groupby(['season', 'week'])[yc].agg(['sum', 'size'])
    bands = []
    for lo, hi in ((0, .1), (.1, .2), (.2, .3), (.3, .4), (.4, .5)):
        b = x[(x.p >= lo) & (x.p < hi)]
        if len(b) >= 25:
            bands.append({'band': f'{int(lo * 100)}-{int(hi * 100)}%', 'n': int(len(b)), 'expected': float(b.p.mean()), 'actual': float(b[yc].mean())})
    by_season = [{'season': int(s), 'n': int(len(g)), 'expected': float(g.p.mean()), 'actual': float(g[yc].mean())} for s, g in x.groupby('season')]
    backtest[mk] = {'n': int(len(x)), 'weeks': int(len(wk)), 'expected': float(x.p.mean()), 'actual': float(x[yc].mean()),
                    'per_week': float(wk['size'].mean()), 'hits_per_week': float(wk['sum'].mean()),
                    'weeks_any_hit': float((wk['sum'] >= 1).mean()), 'weeks_3plus': float((wk['sum'] >= 3).mean()),
                    'bands': bands, 'by_season': by_season}
    print(f"{mk:8s} picks {len(x):4d}  rated {x.p.mean():.3f}  hit {x[yc].mean():.3f}  hits/week {wk['sum'].mean():.2f} of {wk['size'].mean():.1f}  "
          f"weeks with 1+ hit {(wk['sum'] >= 1).mean():.0%}")
    print('          by season', [(r['season'], round(r['expected'], 3), round(r['actual'], 3)) for r in by_season])
res['backtest'] = backtest
pd.concat([x[['season', 'week', 'game_id', 'player_id', 'p']].assign(market=mk_, hit=x[yc_].astype(int).values) for mk_, (x, yc_) in sel.items()],
          ignore_index=True).to_pickle('work/longshot_replay.pkl')   # per-pick results for the units replay
res['rules'] = RULES
pos = sel['atd'][0]
res['atd_by_position'] = {p_: {'n': int(len(g)), 'expected': float(g.p.mean()), 'actual': float(g.any_td.mean())} for p_, g in pos.groupby('position')}

# ---------------- production ----------------
m_prod = fit(e)
gall = G[G.total_line.notna()]
b_all, a_all = np.polyfit(gall.total_line, gall.n_td, 1)
res['game_td'] = {'slope': float(b_all), 'intercept': float(a_all)}
res['atd_predictors'] = sorted(({'feat': f, 'label': FEAT_LABEL[f], 'coef': c} for f, c in zip(FEATS, m_prod['coef'])), key=lambda r: -abs(r['coef']))
json.dump({'atd': m_prod, 'game_td': {'slope': float(b_all), 'intercept': float(a_all)},
           'calibration': {k: v['fit'] for k, v in CAL.items()}, 'rules': RULES},
          open('repo/pipeline/static/longshot_model.json', 'w'), indent=1)
json.dump(res, open('repo/pipeline/static/longshot_research.json', 'w'), indent=1)
print('game TDs = %.3f x total %+.3f' % (b_all, a_all))
print('predictors:', [(r['feat'], round(r['coef'], 3)) for r in res['atd_predictors']])
print('saved')
