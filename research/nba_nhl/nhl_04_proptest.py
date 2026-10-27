"""NHL skater projections -> chances; calibration on held-out seasons."""
import pandas as pd, numpy as np, json
from scipy.stats import poisson, nbinom
WORK = 'work'
sk = pd.read_pickle(f'{WORK}/nhl_proj_base.pkl')
d = sk[(sk.n_prev >= 5) & sk.toi_ew.notna() & sk.yr.ge(2014)].copy()
# ice time: fit lightly on 2014-2021
tr = d[d.yr <= 2021]
X = lambda x: np.column_stack([np.ones(len(x)), x.toi_ew, x.toi_ewr.fillna(x.toi_ew)])
bt = np.linalg.lstsq(X(tr), tr.toi_m, rcond=None)[0]; d['toi_p'] = X(d) @ bt
opp_f = (d.sog_allow / d.sog_lg).fillna(1).clip(0.75, 1.3)
d['sog_p'] = d.toi_p * d.sog_rate * opp_f ** 0.5
gk_f = ((1 - d.opp_sv) / (1 - 0.905)).clip(0.7, 1.4)
d['g_p'] = (0.5 * d.sog_p * d.sh_pct + 0.5 * d.toi_p * d.g_rate) * gk_f
d['a_p'] = d.toi_p * d.a_rate * gk_f ** 0.5
d['p_p'] = d.g_p + d.a_p
d['hit_p'] = d.toi_p * d.hit_rate; d['blk_p'] = d.toi_p * d.blk_rate
for k, col in (('sog', 'shots_on_goal'), ('g', 'goals'), ('a', 'assists'), ('p', 'points'), ('hit', 'hits'), ('blk', 'blocked_shots')):
    te = d[d.yr >= 2022]
    print(k, 'MAE', np.abs(te[col] - te[k + '_p']).mean().round(3), 'mean actual', te[col].mean().round(3), 'mean proj', te[k + '_p'].mean().round(3))
# calibration of anytime goal (Poisson) and 1+ point, 2+ SOG, 3+ SOG on 2022+
te = d[d.yr >= 2022].copy()
te['p_goal'] = 1 - np.exp(-te.g_p); te['p_pt'] = 1 - np.exp(-te.p_p)
for k, y in (('p_goal', te.goals >= 1), ('p_pt', te.points >= 1)):
    b = pd.cut(te[k], [0, .05, .1, .15, .2, .25, .3, .35, .4, .5, .6, .7, 1])
    print(k); print(te.assign(y=y.astype(int)).groupby(b, observed=True).agg(n=('y', 'size'), pred=(k, 'mean'), hit=('y', 'mean')).round(3).T.to_string())
# SOG: Poisson vs negative binomial dispersion
for L in (1.5, 2.5, 3.5):
    lam = te.sog_p
    pp = 1 - poisson.cdf(np.floor(L), lam)
    r = 12.0; pnb = 1 - nbinom.cdf(np.floor(L), r, r / (r + lam))
    y = (te.shots_on_goal > L).astype(int)
    ll = lambda p: float(-np.mean(y * np.log(np.clip(p, 1e-4, 1 - 1e-4)) + (1 - y) * np.log(np.clip(1 - p, 1e-4, 1))))
    print('SOG over', L, 'rate', y.mean().round(3), 'poisson mean', pp.mean().round(3), 'll', round(ll(pp), 4), '| nb mean', pnb.mean().round(3), 'll', round(ll(pnb), 4))
d.to_pickle(f'{WORK}/nhl_proj.pkl')
json.dump({'toi_coef': bt.tolist()}, open(f'{WORK}/nhl_prop_model.json', 'w'))
