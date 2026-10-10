"""Which changes help the model against the closing spread? Walk-forward test: for each season 2020-2025,
fit on 2018..prior season, predict that season. Compares variants on ~1,600 out-of-sample games.
Writes work/spread_experiments.json"""
import sys, json, math
import numpy as np, pandas as pd
sys.path.insert(0, 'repo/pipeline')
import metrics as MX
from teams import INTERNATIONAL

tg = pd.read_pickle('work/team_games.pkl')
tg = tg[tg.season <= 2025].copy()
m = MX.team_metric_frame(tg).sort_values(['season', 'team', 'week']).reset_index(drop=True)

# ---------------- garbage-time filtered efficiency ----------------
gt = pd.read_pickle('work/gt.pkl')
gcols = ['plays_gt', 'epa_gt', 'succ_gt', 'pass_epa_gt', 'db_gt', 'rush_epa_gt', 'ru_gt']
m = m.merge(gt[['game_id', 'team'] + gcols], on=['game_id', 'team'], how='left')
x = gt[['game_id', 'team'] + gcols].rename(columns={'team': 'opp', **{c: 'x_' + c for c in gcols}})
m = m.merge(x, on=['game_id', 'opp'], how='left')
def rt(a, b):
    return np.where(b > 0, a / np.where(b > 0, b, 1), np.nan)
for nm, num, den in (('epa_gt', 'epa_gt', 'plays_gt'), ('sr_gt', 'succ_gt', 'plays_gt'), ('pass_gt', 'pass_epa_gt', 'db_gt'), ('rush_gt', 'rush_epa_gt', 'ru_gt')):
    m['o_' + nm] = rt(m[num], m[den]); m['d_' + nm] = rt(m['x_' + num], m['x_' + den]); m['n_' + nm] = m['o_' + nm] - m['d_' + nm]

# ---------------- pressure rates (Pro Football Reference, free; the stat PFF is best known for) ----------------
adv = pd.concat([pd.read_csv(f'raw/advstats_week_pass_{y}.csv', low_memory=False) for y in range(2018, 2026)])
prs = adv.groupby(['game_id', 'team']).agg(pressured=('times_pressured', 'sum'), blitzed=('times_blitzed', 'sum')).reset_index()
m = m.merge(prs, on=['game_id', 'team'], how='left')
xo = prs.rename(columns={'team': 'opp', 'pressured': 'x_pressured', 'blitzed': 'x_blitzed'})
m = m.merge(xo, on=['game_id', 'opp'], how='left')
db_ = m.merge(tg[['game_id', 'team', 'dropbacks', 'd_dropbacks']], on=['game_id', 'team'], how='left')
m['o_pressure'] = rt(m.pressured, db_.dropbacks.values); m['d_pressure'] = rt(m.x_pressured, db_.d_dropbacks.values)
m['n_pressure'] = m.d_pressure - m.o_pressure
m.loc[m.season < 2018, ['o_pressure', 'd_pressure', 'n_pressure']] = np.nan

# ---------------- rating machinery ----------------
def est(col):
    ts = m.groupby(['season', 'team'])[col].agg(['mean', 'var', 'count'])
    noise = ts['var'].mean(); true_var = max(ts['mean'].var() - noise / ts['count'].mean(), 1e-9)
    tm = ts['mean'].unstack('season')
    pr = np.vstack([tm[[s, s + 1]].dropna().values for s in range(2017, 2025) if s in tm.columns and s + 1 in tm.columns])
    return {'k': float(np.clip(noise / true_var, 1, 30)), 'rho': float(np.corrcoef(pr[:, 0], pr[:, 1])[0, 1]), 'mu': float(m[col].mean())}

GROUPS = list(m.groupby(['season', 'team']).groups.items())
SEASON_MEAN_CACHE = {}
def pregame(col, decay=1.0, pr=None):
    pr = pr or est(col)
    k, rho, mu = pr['k'], pr['rho'], pr['mu']
    sm = m.groupby(['season', 'team'])[col].mean()
    vals = m[col].values; out = np.full(len(m), np.nan)
    for (s, t), idx in GROUPS:
        prev = sm.get((s - 1, t), np.nan)
        prior = mu + rho * (prev - mu) if pd.notna(prev) else mu
        num = den = 0.0
        for i in idx:
            out[i] = (k * prior + num) / (k + den)
            num *= decay; den *= decay
            v = vals[i]
            if not np.isnan(v):
                num += v; den += 1
    return out

BASE = ['n_pts', 'n_epa_play', 'n_success', 'n_early_epa', 'n_pass_epa', 'n_rush_epa', 'n_sack_rate', 'n_to', 'n_explosive', 'n_ppd']
for c in BASE:
    m['pre_' + c] = pregame(c)
    m['dec_' + c] = pregame(c, decay=0.85)
for c in ['n_epa_gt', 'n_sr_gt', 'n_pass_gt', 'n_rush_gt', 'n_pressure']:
    m['pre_' + c] = pregame(c)

# opponent-adjusted efficiency: remove the strength of the defense (or offense) faced, then rate
ADJ = ['epa_play', 'success', 'pass_epa', 'rush_epa', 'early_epa']
for X in ADJ:
    m['pre_o_' + X] = pregame('o_' + X); m['pre_d_' + X] = pregame('d_' + X)
oppv = m[['game_id', 'team'] + [f'pre_{s}_{X}' for X in ADJ for s in ('o', 'd')]].rename(columns={'team': 'opp'})
oppv.columns = ['game_id', 'opp'] + ['opp_' + c for c in oppv.columns[2:]]
m = m.merge(oppv, on=['game_id', 'opp'], how='left').sort_values(['season', 'team', 'week']).reset_index(drop=True)
GROUPS = list(m.groupby(['season', 'team']).groups.items())
for X in ADJ:
    mu_o, mu_d = m['o_' + X].mean(), m['d_' + X].mean()
    m['adj_n_' + X] = (m['o_' + X] - (m['opp_pre_d_' + X] - mu_d)) - (m['d_' + X] - (m['opp_pre_o_' + X] - mu_o))
    m['pre_adj_n_' + X] = pregame('adj_n_' + X)

# ---------------- quarterback ratings (starter's prior dropback EPA, shrunk toward backup level) ----------------
sched = pd.read_csv('raw/games.csv', low_memory=False)
qg = pd.read_pickle('work/qb_games.pkl')
starter = qg.sort_values('db', ascending=False).groupby(['game_id', 'posteam']).head(1)[['game_id', 'posteam', 'qb', 'name']]
ids = sched[['game_id', 'home_team', 'away_team', 'home_qb_id', 'away_qb_id']]
st_map = {}
for _, r in ids.iterrows():
    st_map[(r.game_id, r.home_team)] = r.home_qb_id; st_map[(r.game_id, r.away_team)] = r.away_qb_id
starter['qb_listed'] = [st_map.get((g, t)) for g, t in zip(starter.game_id, starter.posteam)]
starter['qb_use'] = starter.qb_listed.where(starter.qb_listed.notna(), starter.qb)
qg = qg.merge(sched[['game_id', 'season', 'week', 'gameday']], on=['game_id', 'season', 'week'], how='left').sort_values(['gameday', 'game_id'])
K_QB, TARGET, SDEC = 300.0, -0.05, 0.6
hist = {}
qb_rating = {}
for gid, d in qg.groupby('game_id', sort=False):
    season = int(d.season.iloc[0])
    for _, srow in starter[starter.game_id == gid].iterrows():
        h = hist.get(srow.qb_use, [])
        num = sum(e * SDEC ** (season - s) for s, dbs, e in h if season - s <= 2)
        den = sum(dbs * SDEC ** (season - s) for s, dbs, e in h if season - s <= 2)
        qb_rating[(gid, srow.posteam)] = (K_QB * TARGET + num) / (K_QB + den)
    for _, r in d.iterrows():
        hist.setdefault(r.qb, []).append((season, r.db, r.qb_epa))
m['qb_r'] = [qb_rating.get((g, t), np.nan) for g, t in zip(m.game_id, m.team)]

# ---------------- game frame (home perspective) + situational features ----------------
TZ = {t: -4 for t in ['ATL', 'BAL', 'BUF', 'CAR', 'CIN', 'CLE', 'DET', 'IND', 'JAX', 'MIA', 'NE', 'NYG', 'NYJ', 'PHI', 'PIT', 'TB', 'WAS']}
TZ.update({t: -5 for t in ['CHI', 'DAL', 'GB', 'HOU', 'KC', 'MIN', 'NO', 'TEN']}); TZ.update({'DEN': -6, 'ARI': -7})
TZ.update({t: -7 for t in ['LA', 'LAC', 'LV', 'SF', 'SEA', 'OAK']})
h = m[m.home == 1]; a = m[m.home == 0]
g = h.merge(a, on='game_id', suffixes=('_h', '_a'))
g = g.merge(sched[['game_id', 'home_rest', 'away_rest', 'div_game', 'location', 'stadium', 'gametime', 'weekday', 'home_moneyline', 'away_moneyline']], on='game_id', how='left')
g['season'] = g.season_h; g['week'] = g.week_h
g['margin'] = g.pf_h - g.pa_h; g['spread'] = g.spread_line_h; g['ats'] = g.margin - g.spread
g = g[(g.season >= 2018) & g.spread.notna()].copy()
g['neutral'] = (g.location == 'Neutral') | g.stadium.fillna('').apply(lambda s: any(k in s for k in INTERNATIONAL))
g['rest_diff'] = (g.home_rest - g.away_rest).clip(-7, 7).fillna(0)
g['bye_diff'] = (g.home_rest >= 13).astype(int) - (g.away_rest >= 13).astype(int)
g['short_diff'] = (g.home_rest <= 5).astype(int) - (g.away_rest <= 5).astype(int)
g['tz_diff'] = [TZ.get(hh, -5) - TZ.get(aa, -5) for hh, aa in zip(g.team_h, g.team_a)]
g['west_early'] = [1 if (TZ.get(aa, -5) <= -7 and TZ.get(hh, -5) == -4 and str(gt_).startswith('13')) else 0 for hh, aa, gt_ in zip(g.team_h, g.team_a, g.gametime)]
g['altitude'] = (g.team_h == 'DEN').astype(int)
g['div_dog'] = g.div_game * np.sign(-g.spread)          # +1 home is a division underdog, -1 away is
g['home_dog'] = (g.spread < 0).astype(int)
g['neutral_i'] = g.neutral.astype(int)
g['qb_diff'] = g.qb_r_h - g.qb_r_a
SITU = ['rest_diff', 'bye_diff', 'short_diff', 'tz_diff', 'west_early', 'altitude', 'div_dog', 'home_dog', 'neutral_i']

def D(prefix_cols):
    return pd.DataFrame({c: g[c + '_h'] - g[c + '_a'] for c in prefix_cols}, index=g.index)

VARIANTS = {
    'Current model': D(['pre_' + c for c in BASE]),
    'Opponent-adjusted efficiency': pd.concat([D(['pre_' + c for c in BASE if c.replace('n_', '') not in ADJ]),
                                               D(['pre_adj_n_' + X for X in ADJ])], axis=1),
    'Garbage time removed': pd.concat([D(['pre_' + c for c in BASE if c not in ('n_epa_play', 'n_success', 'n_pass_epa', 'n_rush_epa')]),
                                       D(['pre_n_epa_gt', 'pre_n_sr_gt', 'pre_n_pass_gt', 'pre_n_rush_gt'])], axis=1),
    'Recent games weighted more': D(['dec_' + c for c in BASE]),
    'Starting QB rating added': pd.concat([D(['pre_' + c for c in BASE]), g[['qb_diff']]], axis=1),
    'Rest, travel and situation added': pd.concat([D(['pre_' + c for c in BASE]), g[SITU]], axis=1),
}
VARIANTS['Pressure rates added'] = pd.concat([D(['pre_' + c for c in BASE]), D(['pre_n_pressure'])], axis=1)
VARIANTS['All of the above'] = pd.concat([D(['pre_' + c for c in BASE if c.replace('n_', '') not in ADJ and c not in ('n_epa_play', 'n_success', 'n_pass_epa', 'n_rush_epa')]),
                                          D(['pre_adj_n_' + X for X in ADJ]), D(['pre_n_epa_gt', 'pre_n_sr_gt']), g[['qb_diff']], g[SITU]], axis=1)

def ridge_fit(X, y, lam=30.0):
    mu, sd = X.mean(), X.std().replace(0, 1)
    Z = ((X - mu) / sd).fillna(0).values
    Z1 = np.c_[Z, np.ones(len(Z))]
    P = lam * np.eye(Z1.shape[1]); P[-1, -1] = 0
    b = np.linalg.solve(Z1.T @ Z1 + P, Z1.T @ y)
    return lambda Xn: np.c_[((Xn - mu) / sd).fillna(0).values, np.ones(len(Xn))] @ b

def walk_forward(X, target='margin', resid=False):
    preds = pd.Series(np.nan, index=g.index)
    for s in range(2020, 2026):
        tr = (g.season < s) & (g.season >= 2018); te = g.season == s
        y = (g.margin - g.spread) if resid else g.margin
        f = ridge_fit(X[tr], y[tr].values)
        preds[te] = f(X[te])
    return preds

def ats_eval(edge):
    out = {}
    te = g.season >= 2020
    res = g.ats[te]; e = edge[te]
    for thr in (0, 1.5, 3.0):
        ph = e >= thr if thr > 0 else e > 0; pa_ = e <= -thr if thr > 0 else e < 0
        w = int(((ph & (res > 0)) | (pa_ & (res < 0))).sum()); l = int(((ph & (res < 0)) | (pa_ & (res > 0))).sum())
        out[str(thr)] = {'w': w, 'l': l, 'pct': w / (w + l) if w + l else None}
    # does the model's disagreement with the line predict the ATS result at all?
    ok = e.notna()
    b = np.polyfit(e[ok], res[ok], 1)[0]
    r = float(np.corrcoef(e[ok], res[ok])[0, 1])
    t = r * math.sqrt((ok.sum() - 2) / (1 - r * r))
    out['slope'] = float(b); out['r'] = r; out['t'] = float(t); out['n'] = int(ok.sum())
    return out

results = {}
for name, X in VARIANTS.items():
    pm = walk_forward(X)
    te = g.season >= 2020
    su = float((np.sign(pm[te]) == np.sign(g.margin[te]))[g.margin[te] != 0].mean())
    mae = float((pm[te] - g.margin[te]).abs().mean())
    r = ats_eval(pm - g.spread)
    results[name] = {'su': su, 'mae': mae, **r}
    print(f"{name:34s} SU {su:.3f}  MAE {mae:.2f}  ATS all {r['0']['pct']:.3f} ({r['0']['w']}-{r['0']['l']})  1.5+ {r['1.5']['pct']:.3f} ({r['1.5']['w']}-{r['1.5']['l']})  3+ {r['3.0']['pct']:.3f} ({r['3.0']['w']}-{r['3.0']['l']})  r={r['r']:+.3f} t={r['t']:+.2f}")
mkt_mae = float((g.spread[g.season >= 2020] - g.margin[g.season >= 2020]).abs().mean())
print('market MAE', round(mkt_mae, 2))

# direct model of the market's error: predict (margin - spread) from the stat gap vs the line + situation
VARIANTS['All of the above + pressure'] = pd.concat([VARIANTS['All of the above'], D(['pre_n_pressure'])], axis=1)
pm_ = walk_forward(VARIANTS['All of the above + pressure']); te_ = g.season >= 2020
r_ = ats_eval(pm_ - g.spread)
results['All of the above + pressure'] = {'su': float((np.sign(pm_[te_]) == np.sign(g.margin[te_]))[g.margin[te_] != 0].mean()), 'mae': float((pm_[te_] - g.margin[te_]).abs().mean()), **r_}
print(f"{'All of the above + pressure':34s} SU {results['All of the above + pressure']['su']:.3f}  MAE {results['All of the above + pressure']['mae']:.2f}  ATS all {r_['0']['pct']:.3f} ({r_['0']['w']}-{r_['0']['l']})  1.5+ {r_['1.5']['pct']:.3f}  3+ {r_['3.0']['pct']:.3f}  r={r_['r']:+.3f} t={r_['t']:+.2f}")
dp = g['pre_n_pressure_h'] - g['pre_n_pressure_a']; okp = dp.notna() & (g.season >= 2019)
print('pressure gap vs margin r=%.3f, vs ATS result r=%.3f (n=%d)' % (np.corrcoef(dp[okp], g.margin[okp])[0, 1], np.corrcoef(dp[okp], g.ats[okp])[0, 1], okp.sum()))
results['pressure_corr'] = {'margin_r': float(np.corrcoef(dp[okp], g.margin[okp])[0, 1]), 'ats_r': float(np.corrcoef(dp[okp], g.ats[okp])[0, 1]), 'n': int(okp.sum())}
Xr = pd.concat([VARIANTS['All of the above'], g[['spread']]], axis=1)
pr_ = walk_forward(Xr, resid=True)
r = ats_eval(pr_)
results['Predict the line\'s error directly'] = {**r}
print(f"{'Predict the lines error directly':34s} ATS all {r['0']['pct']:.3f} ({r['0']['w']}-{r['0']['l']})  1.5+ {r['1.5']['pct']}  3+ {r['3.0']['pct']}  t={r['t']:+.2f}")

# which situational factors move the ATS result on their own? (2018-2025, all games)
sit = {}
for c in SITU + ['qb_diff']:
    ok = g[c].notna()
    rr = float(np.corrcoef(g.loc[ok, c], g.loc[ok, 'ats'])[0, 1]); n = int(ok.sum())
    sit[c] = {'r': rr, 't': rr * math.sqrt((n - 2) / (1 - rr * rr)), 'n': n}
    print(f'  situational {c:12s} r={rr:+.3f} t={sit[c]["t"]:+.2f}')
# simple splits bettors ask about
def cover_rate(mask, side):
    sub = g[mask]; res = sub.ats if side == 'home' else -sub.ats
    res = res[res != 0]
    return {'rate': float((res > 0).mean()), 'n': int(len(res))}
splits = {
    'Home underdogs': cover_rate(g.spread < 0, 'home'),
    'Road underdogs': cover_rate(g.spread > 0, 'away'),
    'Division underdogs': {'rate': float(((g.ats[g.div_game.astype(bool) & (g.spread != 0)] * np.sign(-g.spread[g.div_game.astype(bool) & (g.spread != 0)])) > 0)[g.ats[g.div_game.astype(bool) & (g.spread != 0)] != 0].mean()), 'n': int(((g.div_game == 1) & (g.spread != 0) & (g.ats != 0)).sum())},
    'Teams off a bye (vs non-bye)': cover_rate(g.bye_diff == 1, 'home') ,
    'West-coast teams in 1pm ET games': cover_rate(g.west_early == 1, 'away'),
    'Home teams in Denver': cover_rate(g.altitude == 1, 'home'),
}
for k_, v in splits.items():
    print(f'  {k_:36s} cover {v["rate"]:.3f} (n={v["n"]})')

# key numbers: how often games land exactly on 3 or 7, and what half a point is worth
sc = sched[(sched.season.between(2018, 2025)) & (sched.game_type == 'REG') & sched.result.notna()].copy()
margin_abs = sc.result.abs()
key = {'p3': float((margin_abs == 3).mean()), 'p7': float((margin_abs == 7).mean()), 'p6': float((margin_abs == 6).mean()),
       'p10': float((margin_abs == 10).mean()), 'p4': float((margin_abs == 4).mean()), 'p1': float((margin_abs == 1).mean())}
near3 = sc[sc.spread_line.abs().between(2.5, 3.5)]
fav_margin = np.where(near3.spread_line > 0, near3.result, -near3.result)
key['p_fav_by_3_when_line_near_3'] = float((fav_margin == 3).mean())
near7 = sc[sc.spread_line.abs().between(6.5, 7.5)]
fav7 = np.where(near7.spread_line > 0, near7.result, -near7.result)
key['p_fav_by_7_when_line_near_7'] = float((fav7 == 7).mean())
print('key numbers', {k_: round(v, 3) for k_, v in key.items()})

# six-point teasers through 3 and 7 ("Wong" teasers), per leg
sc['fav_margin'] = np.where(sc.spread_line > 0, sc.result, -sc.result)
fl = sc[sc.spread_line.abs().between(7.5, 8.5)]
fav_leg = (fl.fav_margin > fl.spread_line.abs() - 6)
dl = sc[sc.spread_line.abs().between(1.5, 2.5)]
dog_leg = (-dl.fav_margin + dl.spread_line.abs() + 6 > 0)
lo_total_f = fl.total_line <= 49; lo_total_d = dl.total_line <= 49
teaser = {'fav_leg': float(fav_leg.mean()), 'fav_n': int(len(fl)), 'dog_leg': float(dog_leg.mean()), 'dog_n': int(len(dl)),
          'fav_leg_lowtotal': float(fav_leg[lo_total_f].mean()), 'dog_leg_lowtotal': float(dog_leg[lo_total_d].mean()),
          'breakeven_2team_minus120': (1 / (1 + 100 / 120)) ** 0.5}
by_season = {int(s): float(pd.concat([fav_leg[fl.season == s], dog_leg[dl.season == s]]).mean()) for s in range(2018, 2026)}
teaser['by_season'] = by_season
print('teasers', {k_: (round(v, 3) if isinstance(v, float) else v) for k_, v in teaser.items()})
json.dump({'variants': results, 'situational': sit, 'splits': splits, 'key': key, 'teaser': teaser, 'market_mae': mkt_mae},
          open('work/spread_experiments.json', 'w'), indent=1)

# ---------------- production model: stats + starting-QB rating + rest/travel (no market-derived inputs) ----------------
PROD_SITU = ['rest_diff', 'bye_diff', 'short_diff', 'tz_diff', 'west_early', 'altitude', 'neutral_i']
Xp = pd.concat([D(['pre_' + c for c in BASE]), g[['qb_diff']], g[PROD_SITU]], axis=1)
Xp.columns = [c.replace('pre_', '') for c in Xp.columns]
pm_p = walk_forward(Xp); te = g.season >= 2020
rp = ats_eval(pm_p - g.spread)
prod_wf = {'su': float((np.sign(pm_p[te]) == np.sign(g.margin[te]))[g.margin[te] != 0].mean()), 'mae': float((pm_p[te] - g.margin[te]).abs().mean()), **rp}
fav_su = float((np.sign(g.spread[te]) == np.sign(g.margin[te]))[(g.margin[te] != 0) & (g.spread[te] != 0)].mean())
print(f"PRODUCTION walk-forward SU {prod_wf['su']:.3f} MAE {prod_wf['mae']:.2f} ATS {rp['0']['pct']:.3f} 2.5+? | favorites SU {fav_su:.3f}")
ok = g.season.between(2018, 2025)
mu, sd = Xp[ok].mean(), Xp[ok].std().replace(0, 1)
Z = ((Xp[ok] - mu) / sd).fillna(0).values; Z1 = np.c_[Z, np.ones(len(Z))]
P = 30.0 * np.eye(Z1.shape[1]); P[-1, -1] = 0
b = np.linalg.solve(Z1.T @ Z1 + P, Z1.T @ g.margin[ok].values)
resid_sd = float(np.std(Z1 @ b - g.margin[ok].values))
model_v2 = {'features': list(Xp.columns), 'mu': mu.to_dict(), 'sd': sd.to_dict(), 'beta': b[:-1].tolist(), 'intercept': float(b[-1]),
            'resid_sd': resid_sd, 'qb': {'k': K_QB, 'target': TARGET, 'season_decay': SDEC, 'seasons_back': 2},
            'tz': TZ, 'walk_forward': prod_wf, 'favorites_su': fav_su, 'qb_mean_starter': float(np.nanmean(m.qb_r))}
print('coefs per SD:', {f: round(v, 2) for f, v in zip(Xp.columns, b[:-1])}, 'intercept', round(b[-1], 2), 'resid sd', round(resid_sd, 2))
json.dump(model_v2, open('repo/pipeline/static/model_v2.json', 'w'), indent=1)
out = json.load(open('work/spread_experiments.json'))
out['production'] = prod_wf; out['favorites_su'] = fav_su
json.dump(out, open('work/spread_experiments.json', 'w'), indent=1)
