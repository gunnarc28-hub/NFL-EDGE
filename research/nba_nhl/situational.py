"""Situational angles against the closing line, found on 2012-2019 and checked on 2020-2026."""
import pandas as pd, numpy as np, json
WORK = 'work'
dec = lambda o: np.where(o > 0, 1 + o / 100, 1 + 100 / np.abs(o))
out = {'nba': {}, 'nhl': {}}
# ---------------- NBA: spreads and totals
g = pd.read_pickle(f'{WORK}/nba_games.pkl')
g = g[g.status_type_completed.astype(str).isin(['True', 'true', '1']) & g.line.notna() & g.hs.notna()].sort_values('t').copy()
last = {}; rest_h = []; rest_a = []; g4_h = []; g4_a = []; hist = {}
for r in g.itertuples():
    dd = pd.Timestamp(r.day)                         # calendar days (Eastern): back-to-back = played yesterday
    for t, lst, l4 in ((r.home, rest_h, g4_h), (r.away, rest_a, g4_a)):
        lst.append((dd - last[t]).days if t in last else 7)
        h = hist.setdefault(t, []); l4.append(sum(1 for x in h if (dd - x).days <= 3))
        h.append(dd); last[t] = dd
g['rest_h'], g['rest_a'], g['g4_h'], g['g4_a'] = rest_h, rest_a, g4_h, g4_a
g['cover_h'] = np.sign(g.margin + g.line)          # +1 home covered
g['tot_res'] = np.sign(g.hs + g.as_ - g.total)
def ats(mask, side):     # side: +1 bet home, -1 bet away
    x = g[mask]; c = x.cover_h * side; w = int((c > 0).sum()); l = int((c < 0).sum()); return w, l
def rate(w, l): return round(w / max(1, w + l), 3)
NBA = {
    'Home underdogs': (g.line > 0, 1), 'Road underdogs': (g.line < 0, -1), 'Big home favorites (10+)': (g.line <= -10, 1), 'Big road favorites (10+)': (g.line >= 10, -1),
    'Rested team vs. a team on a back-to-back (bet the rested team, home)': ((g.rest_a <= 1) & (g.rest_h >= 2), 1),
    'Rested team vs. a team on a back-to-back (bet the rested team, road)': ((g.rest_h <= 1) & (g.rest_a >= 2), -1),
    'Fade a road team on its 3rd game in 4 nights': ((g.g4_a >= 2), 1), 'Home teams after 3+ days off': ((g.rest_h >= 4), 1),
}
for nm, (m, side) in NBA.items():
    early = m & (g.season <= 2019); late = m & (g.season >= 2020)
    w1, l1 = ats(early, side); w2, l2 = ats(late, side)
    out['nba'][nm] = {'found': [w1, l1, rate(w1, l1)], 'checked': [w2, l2, rate(w2, l2)]}
for nm, m, side in (('Unders when both teams are on a back-to-back', (g.rest_h <= 1) & (g.rest_a <= 1), -1), ('Unders with totals of 235+', g.total >= 235, -1),
                    ('Overs with totals under 210', g.total < 210, 1)):
    for per, pm in (('found', g.season <= 2019), ('checked', g.season >= 2020)):
        x = g[m & pm & g.total.notna()]; c = x.tot_res * side; w = int((c > 0).sum()); l = int((c < 0).sum())
        out['nba'].setdefault(nm, {})[per] = [w, l, rate(w, l)]
# ---------------- NHL: moneylines
h = pd.read_pickle(f'{WORK}/nhl_games_plus.pkl')
h = h[h.hs.notna() & h.ml_home.notna() & h.ml_away.notna()].sort_values('t').copy()
last = {}; rh = []; ra = []
for r in h.itertuples():
    dd = pd.Timestamp(r.day)
    rh.append((dd - last[r.home]).days if r.home in last else 5); ra.append((dd - last[r.away]).days if r.away in last else 5)
    last[r.home] = dd; last[r.away] = dd
h['rest_h'], h['rest_a'] = rh, ra
gs = pd.read_pickle(f'{WORK}/nhl_goalie_starts.pkl')
# a team's usual starter: most starts over its last 20 games
gs = gs.sort_values('t'); usual = {}
gs['usual'] = None
uu = []
for r in gs.itertuples():
    lst = usual.setdefault(r.team_abbrev, []); uu.append(max(set(lst[-20:]), key=lst[-20:].count) if lst else None); lst.append(r.player_id)
gs['usual'] = uu; gs['backup'] = gs.player_id != gs.usual
bk = {(r.game_id, r.team_abbrev): r.backup for r in gs.itertuples()}
h['bk_h'] = [bk.get((r.gid, r.home), False) for r in h.itertuples()]; h['bk_a'] = [bk.get((r.gid, r.away), False) for r in h.itertuples()]
h['win_h'] = (h.hs > h.as_).astype(int)
def ml(mask, side):
    x = h[mask]
    r = np.where(side > 0, x.win_h * dec(x.ml_home) - 1, (1 - x.win_h) * dec(x.ml_away) - 1)
    return len(x), round(float(r.mean()), 3) if len(x) else None
NHL = {'Home underdogs': (h.ml_home > 100, 1), 'Road underdogs': (h.ml_away > 100, -1), 'Big home favorites (-200 or shorter)': (h.ml_home <= -200, 1),
       'Road team on a back-to-back (bet the home team)': ((h.rest_a <= 1) & (h.rest_h >= 2), 1), 'Home team on a back-to-back (bet the road team)': ((h.rest_h <= 1) & (h.rest_a >= 2), -1),
       "Bet against a team starting its backup goalie (home backup)": (h.bk_h & ~h.bk_a, -1), "Bet against a team starting its backup goalie (road backup)": (h.bk_a & ~h.bk_h, 1)}
for nm, (m, side) in NHL.items():
    out['nhl'][nm] = {'found': ml(m & (h.season <= 2019), side), 'checked': ml(m & (h.season >= 2020), side)}
h['tot_res'] = np.sign(h.hs + h.as_ - h.total)
for nm, m, side in (('Unders at 6.5', h.total == 6.5, -1), ('Overs at 5.5', h.total == 5.5, 1), ('Unders when both teams are on a back-to-back', (h.rest_h <= 1) & (h.rest_a <= 1), -1)):
    for per, pm in (('found', h.season <= 2019), ('checked', h.season >= 2020)):
        x = h[m & pm & h.total.notna()]; c = x.tot_res * side; w = int((c > 0).sum()); l = int((c < 0).sum())
        out['nhl'].setdefault(nm, {})[per] = [w, l, rate(w, l)]
print(json.dumps(out, indent=1))
json.dump(out, open(f'{WORK}/situational.json', 'w'))
