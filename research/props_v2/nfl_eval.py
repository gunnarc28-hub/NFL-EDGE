"""NFL prop lines (ESPN odds records, 2023 to now) matched to nflverse weekly stats through ESPN ids on the weekly rosters:
how the book's no-vig chance does by market (is the over over-priced?), and anytime-TD prices. Writes work/nfl_props_v2.json."""
import pandas as pd, numpy as np, json
R = '/home/claude/research_work'
d = pd.read_csv(f'{R}/props/nfl_props.csv.gz', dtype={'side': str, 'athlete': str, 'event': str}, low_memory=False); d['side'] = d.side.fillna('')
ev = pd.read_csv(f'{R}/props/nfl_events.csv', dtype={'event': str})
FIX = {'WSH': 'WAS', 'LAR': 'LA'}
ev['home'] = ev.home.replace(FIX); ev['away'] = ev.away.replace(FIX)
st = pd.concat([pd.read_csv(f'{R}/raw/nfl_stats_{y}.csv', low_memory=False) for y in (2023, 2024, 2025, 2026)], ignore_index=True)
ro = pd.concat([pd.read_csv(f'{R}/raw/nfl_roster_{y}.csv', usecols=['season', 'week', 'team', 'gsis_id', 'espn_id'], low_memory=False) for y in (2023, 2024, 2025, 2026)])
ro = ro.dropna(subset=['espn_id', 'gsis_id']); ro['athlete'] = ro.espn_id.astype(float).astype(int).astype(str)
ids = ro.drop_duplicates('athlete').set_index('athlete').gsis_id
# event -> season, week from the stats (a team and its opponent)
gw = st[['season', 'week', 'team', 'opponent_team']].drop_duplicates()
ev['season_nfl'] = pd.to_datetime(ev.date, utc=True).map(lambda t: t.year if t.month >= 6 else t.year - 1)
emap = ev.merge(gw, left_on=['season_nfl', 'home', 'away'], right_on=['season', 'team', 'opponent_team'], how='inner', suffixes=('', '_s'))[['event', 'season_nfl', 'week']]
print('events matched', len(emap), 'of', (ev.completed.astype(str) == 'True').sum())
d = d.merge(emap, on='event', how='inner')
d['gsis'] = d.athlete.map(ids)
for c in ('passing_yards', 'rushing_yards', 'receiving_yards', 'receptions', 'completions', 'attempts', 'passing_tds', 'carries', 'rushing_tds', 'receiving_tds'):
    st[c] = pd.to_numeric(st[c], errors='coerce').fillna(0)
st['rush_rec'] = st.rushing_yards + st.receiving_yards; st['any_td'] = ((st.rushing_tds + st.receiving_tds) > 0).astype(int)
A = st[['season', 'week', 'player_id', 'passing_yards', 'rushing_yards', 'receiving_yards', 'receptions', 'completions', 'attempts', 'passing_tds', 'carries', 'rush_rec', 'any_td']]
am = lambda x: 100.0 if str(x).strip().lower() == 'even' else pd.to_numeric(str(x).replace('+', ''), errors='coerce')
d['o'] = d.odds.map(am); d['line'] = pd.to_numeric(d.line, errors='coerce')
imp = lambda o: np.where(o < 0, -o / (-o + 100), 100 / (o + 100))
dec = lambda o: np.where(o > 0, 1 + o / 100, 1 + 100 / np.abs(o))
clip = lambda p: np.clip(p, 0.01, 0.99); lg = lambda p: np.log(clip(p) / (1 - clip(p)))
ll = lambda p, y: float(-np.mean(y * np.log(clip(p)) + (1 - y) * np.log(1 - clip(p))))


def fitlog(X, y, l2=1.0, it=60):
    X = np.column_stack([np.ones(len(X)), X]); w = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ w)); g = X.T @ (p - y) + l2 * np.r_[0, w[1:]]
        H = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.diag(np.r_[0, np.ones(len(w) - 1)]); w -= np.linalg.solve(H, g)
    return w


OU = {'Total Passing Yards (incl. overtime)': ('pass_yds', 'passing_yards'), 'Total Rushing Yards (incl. overtime)': ('rush_yds', 'rushing_yards'),
      'Total Receiving Yards (incl. overtime)': ('rec_yds', 'receiving_yards'), 'Total Receptions (incl. overtime)': ('receptions', 'receptions'),
      'Total Rushing Plus Receiving Yards (incl. overtime)': ('rush_rec', 'rush_rec'), 'Total Pass Completions (incl. overtime)': ('completions', 'completions'),
      'Total Passing Attempts (incl. overtime)': ('pass_att', 'attempts'), 'Total Passing Touchdowns (incl. overtime)': ('pass_td', 'passing_tds'),
      'Total Carries (incl. overtime)': ('carries', 'carries')}
o = d[d.type.isin(OU)].sort_values(['event', 'book', 'i']).copy()
o['n'] = o.groupby(['event', 'book', 'type', 'athlete', 'line']).cumcount()
um = o.side == ''
o.loc[um & (o.book == 100), 'side'] = np.where(o.loc[um & (o.book == 100), 'n'] == 0, 'over', 'under')
print('sides', o.side.value_counts().to_dict(), 'books', o.book.value_counts().to_dict())
o = o[o.side.isin(['over', 'under'])]
K = ['event', 'season_nfl', 'week', 'book', 'type', 'athlete', 'gsis', 'line']
pr = o[o.side == 'over'].drop_duplicates(K).set_index(K)[['o']].join(o[o.side == 'under'].drop_duplicates(K).set_index(K)[['o']].rename(columns={'o': 'o2'}), how='inner').reset_index()
pr = pr[pr.o.notna() & pr.o2.notna()]
pr['p1'] = imp(pr.o) / (imp(pr.o) + imp(pr.o2))
pr['main'] = (pr.p1 - .5).abs().groupby([pr.event, pr.book, pr.type, pr.athlete]).rank(method='first') == 1
print('priced over/under pairs', len(pr), pr.book.value_counts().to_dict())
pr = pr[pr.main].merge(A, left_on=['season_nfl', 'week', 'gsis'], right_on=['season', 'week', 'player_id'], how='inner')
pr['k'] = pr.type.map(lambda t: OU[t][0]); pr['actual'] = [getattr(r, OU[r.type][1]) for r in pr.itertuples()]
pr = pr[pr.actual != pr.line]; pr['y'] = (pr.actual > pr.line).astype(int)
out = {'fair': {}, 'check': {}}
for k, x in pr.groupby('k'):
    if len(x) < 300:
        continue
    wa = fitlog(lg(x.p1).values[:, None], x.y.values)
    f, t = x[x.season_nfl < 2025], x[x.season_nfl >= 2025]
    r = {'n': len(x), 'over_rate': round(float(x.y.mean()), 3), 'book_mean': round(float(x.p1.mean()), 3),
         'roi_all_over': round(float((x.y * dec(x.o) - 1).mean()), 4), 'roi_all_under': round(float(((1 - x.y) * dec(x.o2) - 1).mean()), 4)}
    if len(f) > 200 and len(t) > 200:
        w = fitlog(lg(f.p1).values[:, None], f.y.values); pt = 1 / (1 + np.exp(-(w[0] + w[1] * lg(t.p1))))
        r.update({'ll_book_test': round(ll(t.p1, t.y), 4), 'll_fair_test': round(ll(pt, t.y), 4), 'test_n': len(t)})
    out['fair'][k] = [round(float(wa[0]), 4), round(float(wa[1]), 4)]; out['check'][k] = r
    print(k, out['fair'][k], r)
Y = d[d.type == 'Anytime Touchdown Scorer'].drop_duplicates(['event', 'athlete']).merge(A, left_on=['season_nfl', 'week', 'gsis'], right_on=['season', 'week', 'player_id'], how='inner')
Y = Y[Y.o.notna()].copy(); Y['pi'] = imp(Y.o); Y['y'] = Y.any_td
print('anytime TD rows with a price', len(Y), Y.book.value_counts().to_dict())
wa = fitlog(lg(Y.pi).values[:, None], Y.y.values)
Y['b'] = pd.cut(Y.pi, [0, .1, .2, .3, .4, .5, .6, 1])
print('anytime TD: n', len(Y), 'hit', round(Y.y.mean(), 3), 'implied', round(Y.pi.mean(), 3), 'ROI every bet', round(float((Y.y * dec(Y.o) - 1).mean()), 3))
print(Y.groupby('b', observed=True).agg(n=('y', 'size'), implied=('pi', 'mean'), hit=('y', 'mean')).round(3).to_string())
out['fair']['any_td'] = [round(float(wa[0]), 4), round(float(wa[1]), 4)]
out['td_check'] = {'n': len(Y), 'hit': round(float(Y.y.mean()), 3), 'implied': round(float(Y.pi.mean()), 3)}
out['types'] = {t: v[0] for t, v in OU.items()}
json.dump(out, open(f'{R}/work/nfl_props_v2.json', 'w'), indent=1)
