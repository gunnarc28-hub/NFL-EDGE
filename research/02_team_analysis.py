"""Which team stats predict NFL game results? Builds pre-game ratings (prior season regressed + current season),
measures predictive vs descriptive correlation with the final margin, fits a margin model and a totals model,
and backtests both against closing lines. Writes work/team_research.json and work/team_ratings.pkl"""
import json, numpy as np, pandas as pd

tg = pd.read_pickle('work/team_games.pkl')
tg = tg.sort_values(['season', 'week', 'game_id']).reset_index(drop=True)

def ratio(a, b):
    return np.where(b > 0, a / np.where(b > 0, b, 1), np.nan)

# ---------- per-game metric values (team perspective) ----------
m = pd.DataFrame({'game_id': tg.game_id, 'team': tg.team, 'opp': tg.opp, 'season': tg.season, 'week': tg.week,
                  'home': tg.home, 'pf': tg.pf, 'pa': tg.pa, 'spread_line': tg.spread_line, 'total_line': tg.total_line,
                  'roof': tg.roof})
O, D = {}, {}
O['epa_play'] = ratio(tg.epa_sum, tg.plays);           D['epa_play'] = ratio(tg.d_epa_sum, tg.d_plays)
O['success'] = ratio(tg.succ_sum, tg.plays);           D['success'] = ratio(tg.d_succ_sum, tg.d_plays)
O['pass_epa'] = ratio(tg.pass_epa_sum, tg.dropbacks);  D['pass_epa'] = ratio(tg.d_pass_epa_sum, tg.d_dropbacks)
O['rush_epa'] = ratio(tg.rush_epa_sum, tg.rushes);     D['rush_epa'] = ratio(tg.d_rush_epa_sum, tg.d_rushes)
O['ypp'] = ratio(tg.yds_sum, tg.plays);                D['ypp'] = ratio(tg.d_yds_sum, tg.d_plays)
O['anya'] = ratio(tg.anya_num, tg.anya_den);           D['anya'] = ratio(tg.d_anya_num, tg.d_anya_den)
O['explosive'] = ratio(tg.explosive_n, tg.plays);      D['explosive'] = ratio(tg.d_explosive_n, tg.d_plays)
O['sack_rate'] = ratio(tg.sacks, tg.dropbacks);        D['sack_rate'] = ratio(tg.d_sacks, tg.d_dropbacks)
O['int_rate'] = ratio(tg.ints, tg.dropbacks);          D['int_rate'] = ratio(tg.d_ints, tg.d_dropbacks)
O['to'] = tg.to_n.values;                              D['to'] = tg.d_to_n.values
O['third'] = ratio(tg.third_conv, tg.third_conv + tg.third_fail); D['third'] = ratio(tg.d_third_conv, tg.d_third_conv + tg.d_third_fail)
O['rz_td'] = ratio(tg.rz_tds, tg.rz_trips);            D['rz_td'] = ratio(tg.d_rz_tds, tg.d_rz_trips)
O['ppd'] = ratio(tg.drive_pts, tg.drives);             D['ppd'] = ratio(tg.d_drive_pts, tg.d_drives)
O['early_epa'] = ratio(tg.early_epa_sum, tg.early_n);  D['early_epa'] = ratio(tg.d_early_epa_sum, tg.d_early_n)
O['pts'] = tg.pf.values;                               D['pts'] = tg.pa.values
O['ypg'] = tg.yds_sum.values;                          D['ypg'] = tg.d_yds_sum.values
O['rush_ypg'] = tg.rush_yds.values;                    D['rush_ypg'] = tg.d_rush_yds.values
O['top'] = tg.top_s.values / 60;                       D['top'] = tg.d_top_s.values / 60
O['pen'] = tg.pen_yds.values;                          D['pen'] = tg.d_pen_yds.values
O['plays'] = tg.plays.values;                          D['plays'] = tg.d_plays.values
O['proe'] = tg.proe.values;                            D['proe'] = tg.d_proe.values
LOWER_BETTER = {'sack_rate', 'int_rate', 'to', 'pen'}   # for offense, lower is better
for k in O:
    m['o_' + k] = O[k]; m['d_' + k] = D[k]
    if k in ('plays', 'proe'):
        continue
    m['n_' + k] = (D[k] - O[k]) if k in LOWER_BETTER else (O[k] - D[k])
m['n_win'] = np.where(m.pf > m.pa, 1.0, np.where(m.pf == m.pa, 0.5, 0.0))

LABEL = {
    'epa_play': 'EPA per play', 'success': 'Success rate', 'pass_epa': 'Pass EPA per dropback', 'rush_epa': 'Rush EPA per carry',
    'ypp': 'Yards per play', 'anya': 'Adj. net yards per pass att (ANY/A)', 'explosive': 'Explosive play rate',
    'sack_rate': 'Sack rate (made vs allowed)', 'int_rate': 'Interception rate', 'to': 'Turnover margin',
    'third': '3rd-down conversion %', 'rz_td': 'Red-zone TD %', 'ppd': 'Points per drive', 'early_epa': 'Early-down EPA',
    'pts': 'Point differential', 'win': 'Win % (record)', 'ypg': 'Total yards per game', 'rush_ypg': 'Rushing yards per game',
    'top': 'Time of possession', 'pen': 'Penalty yards'}
NET = list(LABEL.keys())

# ---------- shrinkage (k) and year-to-year stability (rho) from 2017-2025 ----------
hist = m[m.season <= 2025]
params = {}
for k in NET + ['o_ppd', 'd_ppd', 'o_plays', 'd_plays', 'o_proe', 'o_epa_play', 'd_epa_play', 'o_pts', 'd_pts']:
    col = k if k.startswith(('o_', 'd_')) else 'n_' + k
    ts = hist.groupby(['season', 'team'])[col].agg(['mean', 'var', 'count'])
    noise = ts['var'].mean()
    true_var = max(ts['mean'].var() - noise / ts['count'].mean(), 1e-9)
    kk = float(np.clip(noise / true_var, 1, 30))
    tm = ts['mean'].unstack('season')
    pairs = []
    for s in range(2017, 2025):
        if s in tm.columns and s + 1 in tm.columns:
            pairs.append(tm[[s, s + 1]].dropna().values)
    pr = np.vstack(pairs)
    rho = float(np.corrcoef(pr[:, 0], pr[:, 1])[0, 1])
    params[col] = {'k': kk, 'rho': rho, 'league_mean': float(hist[col].mean())}

# ---------- pre-game ratings ----------
def pregame(df, col, k, rho, mu):
    """For each team-game, rating before the game = (k*prior + sum(prev games this season)) / (k + n).
    prior = mu + rho*(last season mean - mu)."""
    out = np.full(len(df), np.nan)
    season_mean = df.groupby(['season', 'team'])[col].mean()
    for (s, t), idx in df.groupby(['season', 'team']).groups.items():
        idx = sorted(idx, key=lambda i: (df.at[i, 'week']))
        prev = season_mean.get((s - 1, t), np.nan)
        prior = mu + rho * (prev - mu) if not np.isnan(prev) else mu
        csum, n = 0.0, 0
        for i in idx:
            out[i] = (k * prior + csum) / (k + n)
            v = df.at[i, col]
            if not np.isnan(v):
                csum += v; n += 1
    return out

for col, pr in params.items():
    m['pre_' + col] = pregame(m, col, pr['k'], pr['rho'], pr['league_mean'])
m['games_played'] = m.groupby(['season', 'team']).cumcount()
m.to_pickle('work/team_metrics.pkl')

# ---------- game-level frame (home vs away) ----------
h = m[m.home == 1].copy(); a = m[m.home == 0].copy()
g = h.merge(a, on='game_id', suffixes=('_h', '_a'))
g['margin'] = g.pf_h - g.pa_h
g['total'] = g.pf_h + g.pa_h
g['home_win'] = np.where(g.margin > 0, 1.0, np.where(g.margin == 0, 0.5, 0.0))
g['spread'] = g.spread_line_h             # + = home favored
g['tline'] = g.total_line_h
g['ats'] = g.margin - g.spread           # >0 home covered
g['season'] = g.season_h; g['week'] = g.week_h
bt = g[(g.season >= 2018) & (g.season <= 2025)].copy()

rows = []
for k in NET:
    c = 'n_' + k
    dpre = bt['pre_' + c + '_h'] - bt['pre_' + c + '_a']
    dnow = bt[c + '_h'] - bt[c + '_a']
    ok = dpre.notna() & dnow.notna()
    r_pred = float(np.corrcoef(dpre[ok], bt.margin[ok])[0, 1])
    r_desc = float(np.corrcoef(dnow[ok], bt.margin[ok])[0, 1])
    r_ats = float(np.corrcoef(dpre[ok], bt.ats[ok])[0, 1])
    # predictive accuracy when stat edge is used alone to pick straight-up winners (weeks 4+)
    late = ok & (bt.week >= 4) & (bt.margin != 0)
    acc = float(((np.sign(dpre[late]) == np.sign(bt.margin[late])).mean()))
    rows.append({'key': k, 'label': LABEL[k], 'r_predict': round(r_pred, 3), 'r_describe': round(r_desc, 3),
                 'r_vs_spread': round(r_ats, 3), 'pick_acc': round(acc, 3),
                 'stability': round(params['n_' + k]['rho'], 3), 'k_games': round(params['n_' + k]['k'], 1)})
research = sorted(rows, key=lambda r: -abs(r['r_predict']))
for r in research:
    print(f"{r['label']:38s} predict r={r['r_predict']:+.3f}  describe r={r['r_describe']:+.3f}  vs-spread r={r['r_vs_spread']:+.3f}  SU acc={r['pick_acc']:.3f}  stab={r['stability']:+.2f} k={r['k_games']}")
mkt_r = float(np.corrcoef(bt.spread, bt.margin)[0, 1])
mkt_acc = float((np.sign(bt.spread[(bt.margin != 0) & (bt.spread != 0)]) == np.sign(bt.margin[(bt.margin != 0) & (bt.spread != 0)])).mean())
print('market spread r with margin', round(mkt_r, 3), 'favorite SU acc', round(mkt_acc, 3))

# ---------- margin model (standardized features, non-negative weights) ----------
from sklearn.linear_model import LinearRegression
FEATS = ['n_pts', 'n_epa_play', 'n_success', 'n_early_epa', 'n_pass_epa', 'n_rush_epa', 'n_sack_rate', 'n_to', 'n_explosive', 'n_ppd']
train = g[(g.season >= 2018) & (g.season <= 2023)].dropna(subset=['margin'])
test = g[(g.season >= 2024) & (g.season <= 2025)].dropna(subset=['margin'])
def rawD(df):
    return pd.DataFrame({f: df['pre_' + f + '_h'] - df['pre_' + f + '_a'] for f in FEATS})
_tr = rawD(train)
MU = _tr.mean(); SD = _tr.std()
def design(df):
    return ((rawD(df) - MU) / SD).fillna(0)
lr = LinearRegression(positive=True).fit(design(train).values, train.margin.values)
beta = np.append(lr.coef_, lr.intercept_)
coef = dict(zip(FEATS + ['const'], beta.round(4).tolist()))
print('margin coefs (per 1 SD)', coef)
def predict_margin(df):
    return design(df).values @ lr.coef_ + lr.intercept_
for name, df in [('train', train), ('test', test)]:
    pm = predict_margin(df)
    r = np.corrcoef(pm, df.margin)[0, 1]
    nz = df.margin != 0
    su = (np.sign(pm[nz]) == np.sign(df.margin[nz])).mean()
    print(name, 'model r', round(r, 3), 'SU acc', round(su, 3), 'MAE', round(np.abs(pm - df.margin).mean(), 2),
          'market MAE', round(np.abs(df.spread - df.margin).mean(), 2))
def ats_backtest(df, thr):
    pm = predict_margin(df)
    edge = pm - df.spread.values
    pick_home = edge >= thr; pick_away = edge <= -thr
    res = df.ats.values
    w = ((pick_home & (res > 0)) | (pick_away & (res < 0))).sum()
    l = ((pick_home & (res < 0)) | (pick_away & (res > 0))).sum()
    p = ((pick_home | pick_away) & (res == 0)).sum()
    return int(w), int(l), int(p)
bt_rows = []
for thr in [0, 1.5, 3, 4.5]:
    w, l, p = ats_backtest(test, thr)
    w2, l2, p2 = ats_backtest(train, thr)
    bt_rows.append({'threshold': thr, 'test_w': w, 'test_l': l, 'test_p': p, 'train_w': w2, 'train_l': l2, 'train_p': p2})
    print('ATS thr', thr, 'test', w, l, p, f'{w/(w+l):.3f}' if w + l else '-', '| train', w2, l2, p2, f'{w2/(w2+l2):.3f}' if w2 + l2 else '-')

# ---------- totals model ----------
def tdesign(df):
    X = pd.DataFrame({
        'h_off_ppd': df['pre_o_ppd_h'], 'a_def_ppd': df['pre_d_ppd_a'], 'a_off_ppd': df['pre_o_ppd_a'], 'h_def_ppd': df['pre_d_ppd_h'],
        'pace': (df['pre_o_plays_h'] + df['pre_o_plays_a'] + df['pre_d_plays_h'] + df['pre_d_plays_a']) / 2,
        'dome': df['roof_h'].isin(['dome', 'closed']).astype(float)})
    X['ppd_sum'] = X.h_off_ppd + X.a_def_ppd + X.a_off_ppd + X.h_def_ppd
    X = X[['ppd_sum', 'pace', 'dome']]
    X['const'] = 1.0
    return X
ttr = train.dropna(subset=['total']); tte = test.dropna(subset=['total'])
TMEANS = tdesign(ttr).mean()
Xt = tdesign(ttr).fillna(TMEANS).values
tbeta = np.linalg.lstsq(Xt, ttr.total.values, rcond=None)[0]
tcoef = dict(zip(['ppd_sum', 'pace', 'dome', 'const'], tbeta.round(4).tolist()))
print('total coefs', tcoef)
def predict_total(df):
    X = tdesign(df)
    return X.fillna(TMEANS).values @ tbeta
def ou_backtest(df, thr):
    pt = predict_total(df); edge = pt - df.tline.values; res = df.total.values - df.tline.values
    po = edge >= thr; pu = edge <= -thr
    w = ((po & (res > 0)) | (pu & (res < 0))).sum(); l = ((po & (res < 0)) | (pu & (res > 0))).sum(); p = ((po | pu) & (res == 0)).sum()
    return int(w), int(l), int(p)
ou_rows = []
for thr in [0, 1.5, 3, 4.5]:
    w, l, p = ou_backtest(tte, thr); w2, l2, p2 = ou_backtest(ttr, thr)
    ou_rows.append({'threshold': thr, 'test_w': w, 'test_l': l, 'test_p': p, 'train_w': w2, 'train_l': l2, 'train_p': p2})
    print('O/U thr', thr, 'test', w, l, p, f'{w/(w+l):.3f}' if w + l else '-', '| train', w2, l2, p2, f'{w2/(w2+l2):.3f}' if w2 + l2 else '-')
print('total MAE model', round(np.abs(predict_total(tte) - tte.total).mean(), 2), 'market', round(np.abs(tte.tline - tte.total).mean(), 2))

# ---------- moneyline-style: win probability from predicted margin (normal, sd fit) ----------
resid_sd = float(np.std(predict_margin(train) - train.margin))
print('margin resid sd', round(resid_sd, 2))
from math import erf, sqrt
def ncdf(x):
    return 0.5 * (1 + np.vectorize(erf)(x / sqrt(2)))
def am_to_prob(ml):
    ml = np.asarray(ml, dtype=float)
    return np.where(ml < 0, -ml / (-ml + 100), 100 / (ml + 100))
def am_profit(ml):
    ml = np.asarray(ml, dtype=float)
    return np.where(ml < 0, 100 / -ml, ml / 100)
sched = pd.read_csv('raw/games.csv', low_memory=False)[['game_id', 'home_moneyline', 'away_moneyline']]
def ml_backtest(df, thr):
    d = df.merge(sched, on='game_id', how='left').dropna(subset=['home_moneyline', 'away_moneyline'])
    p_home = ncdf(predict_margin(d) / resid_sd)
    ih, ia = am_to_prob(d.home_moneyline), am_to_prob(d.away_moneyline)
    nv_h = ih / (ih + ia)
    bet_h = (p_home - nv_h) >= thr; bet_a = ((1 - p_home) - (1 - nv_h)) >= thr
    won_h = d.margin.values > 0; won_a = d.margin.values < 0
    units = np.where(bet_h, np.where(won_h, am_profit(d.home_moneyline), -1), 0) + \
            np.where(bet_a, np.where(won_a, am_profit(d.away_moneyline), -1), 0)
    n = int(bet_h.sum() + bet_a.sum()); w = int((bet_h & won_h).sum() + (bet_a & won_a).sum())
    return {'threshold': thr, 'bets': n, 'wins': w, 'units': round(float(units.sum()), 1), 'roi': round(float(units.sum() / n), 3) if n else None}
ml_rows = []
for thr in [0.03, 0.05, 0.08]:
    rt, rr = ml_backtest(test, thr), ml_backtest(train, thr)
    ml_rows.append({'threshold': thr, 'test': rt, 'train': rr})
    print('ML thr', thr, 'test', rt, '| train', rr)

json.dump({'feat_mu': MU.to_dict(), 'feat_sd': SD.to_dict(), 'research': research, 'market_r': round(mkt_r, 3), 'market_su_acc': round(mkt_acc, 3),
           'margin_features': FEATS, 'margin_beta': beta.tolist(), 'margin_coef': coef, 'margin_resid_sd': resid_sd,
           'ats_backtest': bt_rows, 'total_beta': tbeta.tolist(), 'total_coef': tcoef, 'ou_backtest': ou_rows,
           'total_fill': TMEANS.to_dict(), 'ml_backtest': ml_rows,
           'params': params, 'n_games': int(len(bt))}, open('work/team_research.json', 'w'), indent=1)
