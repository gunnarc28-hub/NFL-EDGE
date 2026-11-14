"""NBA prop lines from ESPN's odds records: over/under pairs (main line = the pair priced closest to even) and milestone
(X+) prices, joined to what the player actually did. Writes work/nba_ou.pkl and work/nba_ms.pkl."""
import pandas as pd, numpy as np
RAW = '/home/claude/research_work/props'; WORK = '/home/claude/research_work/work'
d = pd.read_csv(f'{RAW}/nba_props.csv.gz', dtype={'side': str, 'athlete': str, 'event': str})
d['side'] = d.side.fillna('')
am = lambda x: 100.0 if str(x).strip().lower() == 'even' else pd.to_numeric(str(x).replace('+', ''), errors='coerce')
d['o'] = d.odds.map(am); d['o_open'] = d.odds_open.map(am)
d['line'] = pd.to_numeric(d.line, errors='coerce'); d['line_open'] = pd.to_numeric(d.line_open, errors='coerce')
TYPES = {'Total Points': 'pts', 'Total Rebounds': 'reb', 'Total Assists': 'ast', 'Total 3-Point Field Goals': 'fg3m', 'Total Points, Rebounds, and Assists': 'pra',
         'Total Points and Rebounds': 'pr', 'Total Points and Assists': 'pa', 'Total Assists and Rebounds': 'ra', 'Total Steals': 'stl', 'Total Blocks': 'blk', 'Total Turnovers': 'tov'}
MS = {'Points Milestones': 'pts', 'Rebounds Milestones': 'reb', 'Assists Milestones': 'ast', '3-Point Field Goals Milestones': 'fg3m',
      'Points + Assists + Rebounds Milestones': 'pra', 'Points + Rebounds Milestones': 'pr', 'Points + Assists Milestones': 'pa', 'Rebounds + Assists Milestones': 'ra',
      'Steals Milestones': 'stl', 'Blocks Milestones': 'blk'}
ou = d[d.type.isin(TYPES)].sort_values(['event', 'book', 'i']).copy()
ou['k'] = ou.type.map(TYPES)
ou['n'] = ou.groupby(['event', 'book', 'type', 'athlete', 'line']).cumcount()
un = ou.side == ''
ou.loc[un & (ou.book == 100), 'side'] = np.where(ou.loc[un & (ou.book == 100), 'n'] == 0, 'over', 'under')
ou = ou[ou.side.isin(['over', 'under'])]
key = ['event', 'book', 'type', 'athlete', 'line']
ov = ou[ou.side == 'over'].drop_duplicates(key).set_index(key); uu = ou[ou.side == 'under'].drop_duplicates(key).set_index(key)
pr = ov[['k', 'o', 'o_open', 'line_open', 'updated']].join(uu[['o', 'o_open']].rename(columns={'o': 'o2', 'o_open': 'o2_open'}), how='inner').reset_index()
imp = lambda o: np.where(o < 0, -o / (-o + 100), 100 / (o + 100))
pr = pr[pr.o.notna() & pr.o2.notna()]
pr['p1'] = imp(pr.o) / (imp(pr.o) + imp(pr.o2)); pr['vig'] = imp(pr.o) + imp(pr.o2) - 1
pr['bal'] = (pr.p1 - 0.5).abs()
pr['main'] = pr.groupby(['event', 'book', 'type', 'athlete']).bal.rank(method='first') == 1
# actuals
P = pd.read_pickle(f'{WORK}/nba_feat.pkl')[['game_id', 'athlete_id', 'season', 't', 'min', 'pts', 'reb', 'ast', 'fg3m', 'stl', 'blk', 'tov']]
P['pra'] = P.pts + P.reb + P.ast; P['pr'] = P.pts + P.reb; P['pa'] = P.pts + P.ast; P['ra'] = P.reb + P.ast
A = P.melt(id_vars=['game_id', 'athlete_id', 'season', 't', 'min'], value_vars=list(TYPES.values()), var_name='k', value_name='actual')
pr = pr.merge(A, left_on=['event', 'athlete', 'k'], right_on=['game_id', 'athlete_id', 'k'], how='left')
pr.to_pickle(f'{WORK}/nba_ou.pkl')
ms = d[d.type.isin(MS)].copy(); ms['k'] = ms.type.map(MS)
ms = ms[ms.o.notna() & ms.line.notna()].drop_duplicates(['event', 'book', 'type', 'athlete', 'line'])
ms = ms.merge(A, left_on=['event', 'athlete', 'k'], right_on=['game_id', 'athlete_id', 'k'], how='left')
ms.to_pickle(f'{WORK}/nba_ms.pkl')
m = pr[pr.main & pr.actual.notna()]
print('over/under pairs', len(pr), '| main lines with a result', len(m), 'by season', m.groupby('season').size().to_dict(), '| books', m.book.value_counts().to_dict())
print('milestones', len(ms), 'with a result', ms.actual.notna().sum(), '| sample', ms[ms.actual.notna()].head(3)[['k', 'line', 'o', 'actual']].values.tolist())
