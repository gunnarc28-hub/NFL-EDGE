"""Write pipeline/static/nba_model.json: everything the NBA build needs from the research, plus the numbers the site shows."""
import os, pandas as pd, numpy as np, json, importlib.util, itertools
WORK = 'work'
spec = importlib.util.spec_from_file_location('m2', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nba_02_model.py')); m2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(m2)
M = pd.read_pickle(f'{WORK}/nba_missing.pkl')
f = m2.run(H=20, carry=0.6)
d = m2.g[['gid', 'season', 'margin', 'line', 'total', 'hs', 'as_', 'home', 'away', 't', 'ml_home', 'ml_away']].merge(f.drop(columns=['season']), on='gid')
d = d.merge(M.rename(columns={'team': 'home', 'miss_v': 'miss_h', 'avail_v': 'av_h'})[['gid', 'home', 'miss_h', 'av_h']], on=['gid', 'home'], how='left')
d = d.merge(M.rename(columns={'team': 'away', 'miss_v': 'miss_a', 'avail_v': 'av_a'})[['gid', 'away', 'miss_a', 'av_a']], on=['gid', 'away'], how='left')
for c in ['miss_h', 'miss_a', 'av_h', 'av_a']: d[c] = d[c].fillna(d[c].median())
d['tot'] = d.hs + d.as_; d['b2b_h'] = (d.rest_h <= 1).astype(int); d['b2b_a'] = (d.rest_a <= 1).astype(int); d['hfa'] = (~d.neutral).astype(int)
d['miss_d'] = d.miss_a - d.miss_h; d['av_d'] = d.av_h - d.av_a
FE = ['rate_m', 'hfa', 'b2b_h', 'b2b_a', 'miss_d', 'av_d']
X = lambda x: np.column_stack([np.ones(len(x))] + [x[c] for c in FE])
Xt = lambda x: np.column_stack([np.ones(len(x)), x.rate_t, x.b2b_h + x.b2b_a])
res = []
for test in range(2016, 2027):
    tr = d[(d.season < test) & (d.season >= test - 4) & (d.n_h >= 5) & (d.n_a >= 5)]; te = d[d.season == test].copy()
    b = np.linalg.lstsq(X(tr), tr.margin, rcond=None)[0]; te['pm'] = X(te) @ b
    bt = np.linalg.lstsq(Xt(tr), tr.tot, rcond=None)[0]; te['pt'] = Xt(te) @ bt
    res.append(te)
r = pd.concat(res); r = r[r.line.notna()]; r['mkt'] = -r.line
resid_sd = float(np.std(r.margin - r.pm)); resid_t = float(np.std(r.tot - r.pt))
def ats(thr):
    e = r[abs(r.pm - r.mkt) >= thr]; c = np.sign(e.margin + e.line) * np.sign(e.pm - e.mkt); return [int((c > 0).sum()), int((c < 0).sum())]
def ou(thr):
    e = r[r.total.notna() & (abs(r.pt - r.total) >= thr)]; c = np.sign(e.tot - e.total) * np.sign(e.pt - e.total); return [int((c > 0).sum()), int((c < 0).sum())]
su_model = float(((r.pm > 0) == (r.margin > 0)).mean()); su_mkt = float(((r.mkt > 0) == (r.margin > 0))[r.mkt != 0].mean())
# production fit: the last four complete seasons
tr = d[(d.season >= 2023) & (d.season <= 2026) & (d.n_h >= 5) & (d.n_a >= 5)]
b = np.linalg.lstsq(X(tr), tr.margin, rcond=None)[0]; bt = np.linalg.lstsq(Xt(tr), tr.tot, rcond=None)[0]
# what each factor is worth on its own (for What matters): correlation of each with the margin, and how much each adds over the line
facts = {}
for c, nm in (('rate_m', 'Efficiency ratings'), ('miss_d', 'Who is missing'), ('b2b_h', 'Home team on a back-to-back'), ('b2b_a', 'Road team on a back-to-back')):
    facts[nm] = round(float(np.corrcoef(d[c], d.margin)[0, 1]), 3)
prop = json.load(open(f'{WORK}/nba_prop_model.json'))
L = pd.read_pickle(f'{WORK}/nba_prop_eval.pkl'); L = L[L.main]
dec = lambda o: np.where(o > 0, 1 + o / 100, 1 + 100 / np.abs(o))
lg = lambda p: np.log(p / (1 - p)); sg = lambda x: 1 / (1 + np.exp(-x))
ll = lambda p, y: float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
prop_bt, blend = {}, {}
for k, x in L.groupby('k'):
    ov = x[x.p_model - x.p1 >= .06]; un = x[x.p1 - x.p_model >= .06]
    rr = np.concatenate([ov.over * dec(ov.o) - 1, (1 - un.over) * dec(un.o2) - 1])
    w = min(((ll(sg((1 - w) * lg(x.p1) + w * lg(x.p_model.clip(.02, .98))), x.over), w) for w in np.linspace(0, .6, 13)))[1]
    blend[k] = round(float(w), 2)
    prop_bt[k] = {'lines': int(len(x)), 'over_rate': round(float(x.over.mean()), 3), 'll_model': round(ll(x.p_model, x.over), 4), 'll_book': round(ll(x.p1, x.over), 4),
                  'bets': int(len(rr)), 'roi': round(float(rr.mean()), 4) if len(rr) else None}
seasons = sorted(L.season.dropna().astype(int).unique().tolist())
sit = json.load(open(f'{WORK}/situational.json'))['nba']; carry = json.load(open(f'{WORK}/trend_carry.json'))
CAL = json.load(open(f'{WORK}/nba_cal.json'))            # nba_08b_calibrate.py: tail maps and the high-chance / long-shot checks
out = {
    'ratings': {'half_life_games': 20, 'carry': 0.6, 'hca': 2.4, 'pace_half_life': 25, 'lg_eff': 110.0, 'lg_pace': 98.0},
    'availability': {'half_life': 12, 'repl': 0.18, 'min_minutes': 12, 'recent_games': 10},
    'margin_model': {'features': FE, 'coef': [round(float(x), 4) for x in b], 'resid_sd': round(resid_sd, 2)},
    'total_model': {'coef': [round(float(x), 4) for x in bt], 'resid_sd': round(resid_t, 2)},
    'props': {'min_coef': prop['min_coef'], 'adj': prop['best'], 'dist': prop['dist'], 'blend': blend, 'half_life_min': 5, 'half_life_rate': 18, 'prior_minutes': 150,
              'cal': CAL['maps']},
    'backtest': {'games': int(len(r)), 'seasons': [2016, 2026], 'rmse_model': round(float(np.sqrt(((r.margin - r.pm) ** 2).mean())), 2), 'rmse_line': round(float(np.sqrt(((r.margin - r.mkt) ** 2).mean())), 2),
                 'su_model': round(su_model, 3), 'su_market': round(su_mkt, 3), 'ats': {str(t): ats(t) for t in (2, 3, 4, 5, 6)}, 'ou': {str(t): ou(t) for t in (3, 5, 7)},
                 'factor_corr': facts},
    'prop_backtest': {'seasons': seasons, 'by_market': prop_bt, 'total_lines': int(len(L)), 'hc_check': CAL['hc_check'], 'ls_check': CAL['ls_check'],
                      'check_seasons': CAL['check_seasons']},
    'situational': sit, 'carry': {k: v for k, v in carry.items() if k.startswith('nba')},
}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pipeline', 'static', 'nba_model.json'), 'w'), separators=(',', ':'))
print(json.dumps({k: v for k, v in out.items() if k not in ('props', 'situational', 'carry')}, indent=1)[:3000])
