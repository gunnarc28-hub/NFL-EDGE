"""NBA prop lines from ESPN's odds records, paired over/under (ESPN BET marks sides; DraftKings lists the over first) and joined to the box score."""
import pandas as pd, numpy as np
WORK = 'work'; RAW = 'raw'
d = pd.read_csv(f'{RAW}/props/nba_props.csv.gz', dtype={'side': str})
d['side'] = d.side.fillna('')
def am(x):
    x = str(x).strip()
    if x.lower() == 'even': return 100.0
    try: return float(x.replace('+', ''))
    except ValueError: return np.nan
d['o'] = d.odds.map(am)
TYPES = {'Total Points': 'pts', 'Total Rebounds': 'reb', 'Total Assists': 'ast', 'Total 3-Point Field Goals': 'fg3m', 'Total Points, Rebounds, and Assists': 'pra',
         'Total Points and Rebounds': 'pr', 'Total Points and Assists': 'pa', 'Total Assists and Rebounds': 'ra', 'Total Steals': 'stl', 'Total Blocks': 'blk', 'Total Turnovers': 'tov'}
ou = d[d.type.isin(TYPES)].sort_values(['event', 'book', 'i']).copy()
ou['k'] = ou.type.map(TYPES)
# sides: marked, or (DraftKings) first listed of the pair is the over; unmarked ESPN BET pairs are dropped
ou['n'] = ou.groupby(['event', 'book', 'type', 'athlete', 'line']).cumcount()
unmarked = ou.side == ''
ou.loc[unmarked & (ou.book == 100), 'side'] = np.where(ou.loc[unmarked & (ou.book == 100), 'n'] == 0, 'over', 'under')
ou = ou[ou.side.isin(['over', 'under'])]
key = ['event', 'book', 'type', 'athlete', 'line']
ov = ou[ou.side == 'over'].drop_duplicates(key).set_index(key); un = ou[ou.side == 'under'].drop_duplicates(key).set_index(key)
pr = ov[['k', 'o', 'updated']].join(un[['o']].rename(columns={'o': 'o2'}), how='inner').reset_index()
imp = lambda o: np.where(o < 0, -o / (-o + 100), 100 / (o + 100))
pr['p1'] = imp(pr.o) / (imp(pr.o) + imp(pr.o2))
pr['vig'] = imp(pr.o) + imp(pr.o2) - 1
# the main line for each player and market: the pair priced closest to even
pr['bal'] = (pr.p1 - 0.5).abs()
pr['main'] = pr.groupby(['event', 'book', 'type', 'athlete']).bal.rank(method='first') == 1
P = pd.read_pickle(f'{WORK}/nba_player_box.pkl')
P['fg3m'] = P.three_point_field_goals_made
for k, cols in {'pts': ['points'], 'reb': ['rebounds'], 'ast': ['assists'], 'stl': ['steals'], 'blk': ['blocks'], 'tov': ['turnovers'],
                'pra': ['points', 'rebounds', 'assists'], 'pr': ['points', 'rebounds'], 'pa': ['points', 'assists'], 'ra': ['rebounds', 'assists']}.items():
    P['v_' + k] = P[cols].sum(axis=1)
P['v_fg3m'] = P.fg3m
box = P[P.played][['game_id', 'athlete_id', 'min', 't'] + [c for c in P.columns if c.startswith('v_')]]
pr = pr.merge(box, left_on=['event', 'athlete'], right_on=['game_id', 'athlete_id'], how='left')
pr['actual'] = [getattr(r, 'v_' + r.k) if r.min == r.min else np.nan for r in pr.itertuples()]
pr = pr.drop(columns=[c for c in pr.columns if c.startswith('v_')] + ['game_id', 'athlete_id'])
pr['hours_before'] = (pr.t - pd.to_datetime(pr.updated, utc=True)).dt.total_seconds() / 3600
pl = pr[pr.actual.notna() & (pr.actual != pr.line)]
pl = pl.assign(over=(pl.actual > pl.line).astype(int))
print('pairs', len(pr), 'main', int(pr.main.sum()), 'with result', len(pl))
print(pl.groupby('book').apply(lambda x: pd.Series({'n': len(x), 'corr': np.corrcoef(x.p1, x.over)[0, 1], 'over_rate': x.over.mean(), 'vig': x.vig.mean(),
                                                    'hours_before_med': x.hours_before.median()})).round(3))
pl['bin'] = pd.cut(pl.p1, [0, .2, .3, .4, .45, .5, .55, .6, .7, .8, 1])
print(pl.groupby('bin', observed=True).agg(n=('over', 'size'), p=('p1', 'mean'), hit=('over', 'mean')).round(3).T)
pr.to_pickle(f'{WORK}/nba_prop_lines.pkl')
