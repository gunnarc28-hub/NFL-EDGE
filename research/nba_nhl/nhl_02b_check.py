import os, pandas as pd, numpy as np, importlib.util
spec = importlib.util.spec_from_file_location('m', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nhl_02_model.py')); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
g = m.g
x = g[g.sbr_hs.notna()]
print('sbr score matches (home,away):', ((x.sbr_hs == x.hs) & (x.sbr_as == x.as_)).mean().round(3), ' swapped:', ((x.sbr_hs == x.as_) & (x.sbr_as == x.hs)).mean().round(3))
print(x[~((x.sbr_hs == x.hs) & (x.sbr_as == x.as_))][['day', 'home', 'away', 'hs', 'as_', 'sbr_hs', 'sbr_as', 'ml_h', 'ml_a', 'season']].head(12).to_string())
o, v = m.evaluate(m.run(H=35, Hs=35, w_shot=0.6, carry=0.7, gk_prior=1500), quiet=True)
ll = lambda p, y: -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
v['src'] = np.where(v.e_mlh.notna() if 'e_mlh' in v else False, 'espn', 'sbr') if False else 'x'
v = v.merge(g[['gid', 'e_mlh', 'ml_h', 'day', 'home', 'away']], on='gid')
v['src'] = np.where(v.e_mlh.notna(), 'espn', 'sbr')
print(v.groupby(['season']).apply(lambda d: pd.Series({'n': len(d), 'll_model': ll(d.p_h, d.y), 'll_mkt': ll(d.mkt, d.y), 'src': d.src.iloc[0],
      'fav_win': ((d.mkt > .5) == (d.y == 1)).mean()})).round(4))
