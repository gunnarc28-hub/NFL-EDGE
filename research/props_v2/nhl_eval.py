"""NHL prop lines (ESPN odds records, 2023-24 to now) matched to NHL box scores by game and name:
how the book's no-vig chance does on points, assists, shots and blocks; and what anytime-goal prices are worth.
Fits the market-anchored fair chance (logistic on the book) for the build. Writes work/nhl_props_v2.json."""
import pandas as pd, numpy as np, json, re, unicodedata
R = '/home/claude/research_work'
d = pd.read_csv(f'{R}/props/nhl_props.csv.gz', dtype={'side': str, 'athlete': str, 'event': str}, low_memory=False); d['side'] = d.side.fillna('')
ath = pd.read_csv('/home/claude/probe-wt/research/data/nhl_athletes.csv', dtype={'athlete': str})
ev = pd.read_csv(f'{R}/props/nhl_events.csv', dtype={'event': str})
ESPN = {'NJ': 'NJD', 'SJ': 'SJS', 'TB': 'TBL', 'LA': 'LAK', 'UTAH': 'UTA'}
ev['home'] = ev.home.replace(ESPN); ev['away'] = ev.away.replace(ESPN)
ev['day'] = pd.to_datetime(ev.date, utc=True).dt.tz_convert('America/New_York').dt.date.astype(str)
sk = pd.concat([pd.read_csv(f'{R}/raw/nhl_skater_box_{y}.csv', low_memory=False) for y in (2024, 2025, 2026, 2027)], ignore_index=True)
home = sk[sk.home_away == 'home'].groupby('game_id').team_abbrev.first(); away = sk[sk.home_away == 'away'].groupby('game_id').team_abbrev.first()
day = sk.groupby('game_id').game_date.first()
G = pd.DataFrame({'home': home, 'away': away, 'day': day}).reset_index()
emap = ev.merge(G, on=['day', 'home', 'away'])[['event', 'game_id', 'season']]
print('events matched to NHL games', len(emap), 'of', len(ev[ev.completed.astype(str) == 'True']))


def key(n):
    n = unicodedata.normalize('NFKD', str(n)).encode('ascii', 'ignore').decode().lower()
    n = re.sub(r'[^a-z ]', ' ', n).split()
    return (n[0][:1] + ' ' + n[-1]) if len(n) >= 2 else ''


ath['nk'] = ath.name.map(key); sk['nk'] = sk.player_name.map(key)
for c in ('goals', 'assists', 'points', 'shots_on_goal', 'blocked_shots'):
    sk[c] = pd.to_numeric(sk[c], errors='coerce')
sk = sk.drop_duplicates(['game_id', 'nk'], keep=False)              # two players with one key in a game: drop both
d = d.merge(emap, on='event', how='inner').merge(ath[['athlete', 'nk']], on='athlete', how='left')
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


OU = {'Total Points': 'points', 'Total Assists': 'assists', 'Total Shots on Goal': 'shots_on_goal', 'Total Blocked Shots': 'blocked_shots'}
o = d[d.type.isin(OU)].sort_values(['event', 'book', 'i']).copy()
o['n'] = o.groupby(['event', 'book', 'type', 'athlete', 'line']).cumcount()
um = o.side == ''
o.loc[um & (o.book == 100), 'side'] = np.where(o.loc[um & (o.book == 100), 'n'] == 0, 'over', 'under')
o = o[o.side.isin(['over', 'under'])]
K = ['event', 'game_id', 'season', 'book', 'type', 'athlete', 'nk', 'line']
pr = o[o.side == 'over'].drop_duplicates(K).set_index(K)[['o']].join(o[o.side == 'under'].drop_duplicates(K).set_index(K)[['o']].rename(columns={'o': 'o2'}), how='inner').reset_index()
pr = pr[pr.o.notna() & pr.o2.notna()]
pr['p1'] = imp(pr.o) / (imp(pr.o) + imp(pr.o2))
pr['main'] = (pr.p1 - .5).abs().groupby([pr.event, pr.book, pr.type, pr.athlete]).rank(method='first') == 1
pr['stat'] = pr.type.map(OU)
pr = pr[pr.main].merge(sk[['game_id', 'nk', 'goals', 'assists', 'points', 'shots_on_goal', 'blocked_shots']], on=['game_id', 'nk'], how='inner')
pr['actual'] = [getattr(r, r.stat) for r in pr.itertuples()]
pr = pr[pr.actual.notna() & (pr.actual != pr.line)]
pr['y'] = (pr.actual > pr.line).astype(int)
out = {'fair': {}, 'check': {}}
NAME = {'points': 'points', 'assists': 'assists', 'shots_on_goal': 'sog', 'blocked_shots': 'blocks'}
for s, x in pr.groupby('stat'):
    f, t = x[x.season < 2026], x[x.season >= 2026]
    w = fitlog(lg(f.p1).values[:, None], f.y.values)
    pt = 1 / (1 + np.exp(-(w[0] + w[1] * lg(t.p1))))
    ro = (t.y * dec(t.o) - 1); ru = ((1 - t.y) * dec(t.o2) - 1)
    wa = fitlog(lg(x.p1).values[:, None], x.y.values)
    out['fair'][NAME[s]] = [round(float(wa[0]), 4), round(float(wa[1]), 4)]
    out['check'][NAME[s]] = {'n': len(x), 'over_rate': round(float(x.y.mean()), 3), 'book_mean': round(float(x.p1.mean()), 3), 'test_n': len(t),
                             'll_book_test': round(ll(t.p1, t.y), 4), 'll_fair_test': round(ll(pt, t.y), 4), 'roi_all_over_test': round(float(ro.mean()), 4),
                             'roi_all_under_test': round(float(ru.mean()), 4), 'by_line': x.groupby('line').agg(n=('y', 'size'), over=('y', 'mean'), book=('p1', 'mean')).round(3).head(6).reset_index().values.tolist()}
    print(s, out['fair'][NAME[s]], out['check'][NAME[s]])
# anytime goal: the book prices only the yes side
Y = d[d.type == 'Anytime Goalscorer'].drop_duplicates(['event', 'athlete']).merge(sk[['game_id', 'nk', 'goals']], on=['game_id', 'nk'], how='inner')
Y = Y[Y.o.notna() & Y.goals.notna()].copy()
Y['pi'] = imp(Y.o); Y['y'] = (Y.goals >= 1).astype(int)
print('anytime goal rows by season', Y.groupby('season').size().to_dict())
f, t = (Y[Y.season < 2026], Y[Y.season >= 2026]) if (Y.season < 2026).sum() > 500 else (Y[Y.season < 2027], Y[Y.season >= 2027])
w = fitlog(lg(f.pi).values[:, None], f.y.values)
pt = 1 / (1 + np.exp(-(w[0] + w[1] * lg(t.pi))))
wa = fitlog(lg(Y.pi).values[:, None], Y.y.values)
Y['b'] = pd.cut(Y.pi, [0, .15, .2, .25, .3, .35, .4, .5, 1])
print('anytime goal: n', len(Y), 'hit', round(Y.y.mean(), 3), 'implied', round(Y.pi.mean(), 3), '| test ll implied', round(ll(t.pi, t.y), 4), 'fair', round(ll(pt, t.y), 4),
      '| ROI betting every scorer', round(float((Y.y * dec(Y.o) - 1).mean()), 3))
print(Y.groupby('b', observed=True).agg(n=('y', 'size'), implied=('pi', 'mean'), hit=('y', 'mean')).round(3).to_string())
out['fair']['atg'] = [round(float(wa[0]), 4), round(float(wa[1]), 4)]
out['atg_check'] = {'n': len(Y), 'hit': round(float(Y.y.mean()), 3), 'implied': round(float(Y.pi.mean()), 3), 'roi_all': round(float((Y.y * dec(Y.o) - 1).mean()), 3)}
json.dump(out, open(f'{R}/work/nhl_props_v2.json', 'w'), indent=1)
