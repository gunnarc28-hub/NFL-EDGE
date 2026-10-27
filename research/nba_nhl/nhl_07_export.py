"""Write pipeline/static/nhl_model.json for the NHL build."""
import os, pandas as pd, numpy as np, json, importlib.util
from scipy.stats import poisson
WORK = 'work'
spec = importlib.util.spec_from_file_location('m', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nhl_02_model.py')); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
P = dict(H=35, Hs=35, w_shot=0.6, carry=0.7, gk_prior=1500, Hg=60, hca=0.06)
o, v = m.evaluate(m.run(**P), quiet=True)
dec = lambda x: 1 + (x / 100 if x > 0 else 100 / -x)
v['su_model'] = ((v.p_h > .5) == (v.y == 1)); v['su_mkt'] = ((v.mkt > .5) == (v.y == 1))
roi = {}
for thr in (0.03, 0.05, 0.08):
    bets = []
    for r in v.itertuples():
        if r.p_h - r.mkt >= thr: bets.append(r.y * dec(r.ml_home) - 1)
        elif r.mkt - r.p_h >= thr: bets.append((1 - r.y) * dec(r.ml_away) - 1)
    roi[str(thr)] = [len(bets), round(float(np.mean(bets)), 4)]
# calibration maps: predicted -> observed, from 2016 on
sk = pd.read_pickle(f'{WORK}/nhl_proj.pkl'); s = sk[sk.yr >= 2016]
def calmap(p, y, edges):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mk = (p >= lo) & (p < hi)
        if mk.sum() >= 200: out.append([round(float(p[mk].mean()), 4), round(float(y[mk].mean()), 4)])
    return out
E = np.array([0, .03, .06, .09, .12, .15, .18, .21, .25, .3, .35, .4, .45, .5, .55, .6, .65, .7, .75, .8, .85, .9, .95, 1.0])
cal = {'goal1': calmap(1 - np.exp(-s.g_p), (s.goals >= 1).astype(int), E), 'goal2': calmap(1 - poisson.cdf(1, s.g_p), (s.goals >= 2).astype(int), np.array([0, .005, .01, .02, .03, .05, .08, .12, .2, 1])),
       'point1': calmap(1 - np.exp(-s.p_p), (s.points >= 1).astype(int), E), 'point2': calmap(1 - poisson.cdf(1, s.p_p), (s.points >= 2).astype(int), E),
       'point3': calmap(1 - poisson.cdf(2, s.p_p), (s.points >= 3).astype(int), np.array([0, .005, .01, .02, .03, .05, .08, .12, .2, .3, 1])),
       'assist1': calmap(1 - np.exp(-s.a_p), (s.assists >= 1).astype(int), E)}
for kk in (1, 2, 3, 4, 5):
    cal[f'sog{kk}'] = calmap(1 - poisson.cdf(kk - 1, s.sog_p), (s.shots_on_goal >= kk).astype(int), E)
for kk in (1, 2, 3):
    cal[f'blk{kk}'] = calmap(1 - poisson.cdf(kk - 1, s.blk_p), (s.blocked_shots >= kk).astype(int), E)
    cal[f'hit{kk}'] = calmap(1 - poisson.cdf(kk - 1, s.hit_p), (s.hits >= kk).astype(int), E)
# goalie saves: the build uses a normal around the expected saves. Its spread has to include not knowing the shots in
# advance, so measure saves against a pre-game expectation (each team's recent shots allowed times the opponent's recent
# shots taken, over the league rate), for starters who faced 15+ shots since 2021-22.
gs = pd.read_pickle(f'{WORK}/nhl_goalie_starts.pkl').sort_values('t')
opp_ = gs[['game_id', 'team_abbrev']].rename(columns={'team_abbrev': 'opp'})
gx = gs.merge(opp_, on='game_id'); gx = gx[gx.opp != gx.team_abbrev].sort_values('t')
gx['sa_ew'] = gx.groupby('team_abbrev').sa.transform(lambda v: v.ewm(halflife=25, min_periods=5).mean().shift())
sf_ = gx[['game_id', 'opp', 'sa', 't']].rename(columns={'opp': 'team', 'sa': 'sf'}).sort_values('t')
sf_['sf_ew'] = sf_.groupby('team').sf.transform(lambda v: v.ewm(halflife=25, min_periods=5).mean().shift())
gx = gx.merge(sf_[['game_id', 'team', 'sf_ew']].rename(columns={'team': 'opp'}), on=['game_id', 'opp'])
gx['exp_sv'] = gx.sa_ew * gx.sf_ew / gx.sa.ewm(halflife=2000).mean().shift() * gx.sv_pct
gy = gx.dropna(subset=['exp_sv']); gy = gy[(gy.t > '2021-09-01') & (gy.sa > 15)]
sv_sd = float(np.std(gy.sv - gy.exp_sv))
# prop backtest numbers
pr = pd.read_pickle(f'{WORK}/nhl_prop_lines.pkl'); pr = pr[pr.actual.notna() & (pr.actual != pr.line) & pr.main].copy()
PROJ = {'points': 'p_p', 'assists': 'a_p', 'shots_on_goal': 'sog_p', 'blocked_shots': 'blk_p'}
pr['lam'] = [getattr(r, PROJ[r.stat]) for r in pr.itertuples()]
pr['p_model'] = (1 - poisson.cdf(np.floor(pr.line), pr.lam)).clip(0.02, 0.98); pr['over'] = (pr.actual > pr.line).astype(int)
decv = lambda o: np.where(o > 0, 1 + o / 100, 1 + 100 / np.abs(o))
ll = lambda p, y: float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
lg = lambda p: np.log(p / (1 - p)); sg = lambda x: 1 / (1 + np.exp(-x))
prop_bt, blend = {}, {}
for k, x in pr.groupby('stat'):
    ov = x[x.p_model - x.p1 >= .06]; un = x[x.p1 - x.p_model >= .06]
    rr = np.concatenate([ov.over * decv(ov.o) - 1, (1 - un.over) * decv(un.o2) - 1])
    w = min(((ll(sg((1 - w) * lg(x.p1) + w * lg(x.p_model)), x.over), w) for w in np.linspace(0, .6, 13)))[1]
    blend[k] = round(float(w), 2)
    prop_bt[k] = {'lines': int(len(x)), 'over_rate': round(float(x.over.mean()), 3), 'll_model': round(ll(x.p_model, x.over), 4), 'll_book': round(ll(x.p1, x.over), 4), 'bets': int(len(rr)), 'roi': round(float(rr.mean()), 4) if len(rr) else None}
Y = pd.read_pickle(f'{WORK}/nhl_prop_yes.pkl'); Y = Y[Y.player_id.notna() & Y.o.notna() & (Y.type == 'Anytime Goalscorer')]
imp = lambda x: np.where(x < 0, -x / (-x + 100), 100 / (x + 100))
pa = 1 - np.exp(-Y.g_p); yv = (Y.goals >= 1).astype(int); pi = imp(Y.o)
atg = {'lines': int(len(Y)), 'hit': round(float(yv.mean()), 3), 'model_mean': round(float(pa.mean()), 3), 'book_implied_mean': round(float(pi.mean()), 3),
       'bets_model_above_price': [int((pa > pi).sum()), round(float((yv[pa > pi] * decv(Y.o[pa > pi]) - 1).mean()), 4)]}
sit = json.load(open(f'{WORK}/situational.json'))['nhl']
for kk, vv in sit.items():
    for per in ('found', 'checked'):
        x = vv.get(per)
        if isinstance(x, list) and len(x) == 2 and (x[1] is None or not np.isfinite(x[1])): vv[per] = [x[0], None]
carry = json.load(open(f'{WORK}/trend_carry.json'))
out = {'game': dict(P, lg_goals=2.95, lg_shots=30.5, lg_sv=0.905),
       'props': {'toi_coef': json.load(open(f'{WORK}/nhl_prop_model.json'))['toi_coef'], 'half_life_toi': 5, 'half_life_rate': 20, 'prior_minutes': 300, 'sh_prior_shots': 60,
                 'sv_prior_shots': 900, 'goalie_half_life': 40, 'opp_sog_exp': 0.5, 'cal': cal, 'sv_sd': round(sv_sd, 1), 'blend': blend},
       'backtest': {'games': int(o['n']), 'seasons': [2016, 2027], 'll_model': float(o['ll_model']), 'll_market': float(o['ll_mkt']), 'brier_model': o['brier_model'], 'brier_market': o['brier_mkt'],
                    'su_model': round(float(v.su_model.mean()), 3), 'su_market': round(float(v.su_mkt.mean()), 3), 'roi': roi},
       'prop_backtest': {'by_market': prop_bt, 'anytime_goal': atg, 'seasons': sorted(pr.yr.dropna().astype(int).unique().tolist())},
       'situational': sit, 'carry': {k: v for k, v in carry.items() if k.startswith('nhl')}}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pipeline', 'static', 'nhl_model.json'), 'w'), separators=(',', ':'))
print(json.dumps({k: out[k] for k in ('backtest', 'prop_backtest')}, indent=1)); print('sv_sd', sv_sd); print({k: v[:4] for k, v in cal.items()})
