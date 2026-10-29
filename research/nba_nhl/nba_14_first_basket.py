"""NBA first basket (first field goal of the game, DraftKings' rule: free throws don't count) and first team to score.

P(player scores the first basket) = P(his team makes the first field goal) * P(him | his team makes it).
  - The tip: each team's usual jumper (whoever took its most recent opening tips), rated by his jump-ball record
    (wins + 3) / (jumps + 6) before the game; P(home wins the tip) from the two ratings (Bradley-Terry).
  - Team: the tip winner's chance of making the first field goal (fit), plus a lean toward the better offense.
  - Player: among his team's players, weight = (chance he starts)^g * (projected points)^a, fit by conditional logit.
The likeliest players hit a little less often than the product says, so a Platt curve (fit) trims them.
Knowing the real starters would sharpen this a lot (log loss per game 1.60 instead of 1.86 in the check seasons), but
lineups come out about half an hour before tip, so the site uses each player's recent starts.
Fit on 2020-21 to 2023-24, checked on 2024-25 and 2025-26, and compared with DraftKings' First Basket prices
(raw/props, 2023-24 on) where both exist. -> work/nba_first_basket.json"""
import json, numpy as np, pandas as pd
from scipy.optimize import minimize
WORK, RAW = '/home/claude/sports/work', '/home/claude/sports/raw'
Q = pd.read_pickle(f'{WORK}/nba_qscores.pkl')
Q['game_id'] = pd.to_numeric(Q.game_id)
P = pd.read_pickle(f'{WORK}/nba_proj.pkl')
P = P[P.season >= 2020][['game_id', 'season', 't', 'athlete_id', 'team_abbreviation', 'home_away', 'starter', 'started_prev', 'min', 'pts_proj', 'played']].copy()
P['athlete_id'] = P.athlete_id.astype(float)
TEAM_OF = P.set_index(['game_id', 'athlete_id']).team_abbreviation.to_dict()
G = pd.read_pickle(f'{WORK}/nba_games.pkl')[['gid', 'line', 'total']]
G['gid'] = pd.to_numeric(G.gid, errors='coerce')
Q = Q.merge(G, left_on='game_id', right_on='gid', how='left').sort_values('game_id')
gt = P.drop_duplicates('game_id').set_index('game_id').t
Q['t'] = Q.game_id.map(gt); Q = Q.dropna(subset=['t']).sort_values('t')
# ---------------- the tip: walk forward through games, rating jumpers and remembering each team's usual jumper
rec, usual = {}, {}
rows = []
for g in Q.itertuples():
    gid = g.game_id
    jh = usual.get(g.home); ja = usual.get(g.away)
    rate = lambda pid: (rec.get(pid, [0, 0])[0] + 3) / (rec.get(pid, [0, 0])[1] + 6)
    ph, pa = (rate(jh) if jh else 0.5), (rate(ja) if ja else 0.5)
    p_tip = ph * (1 - pa) / (ph * (1 - pa) + pa * (1 - ph))
    won = None
    if g.jb_poss == g.jb_poss and g.jb_poss is not None:
        won = TEAM_OF.get((gid, float(g.jb_poss)))
    j1, j2 = (float(g.jb_p1) if g.jb_p1 == g.jb_p1 else None), (float(g.jb_p2) if g.jb_p2 == g.jb_p2 else None)
    t1, t2 = TEAM_OF.get((gid, j1)), TEAM_OF.get((gid, j2))
    rows.append({'game_id': gid, 'season': g.season, 'home': g.home, 'away': g.away, 'p_tip_home': p_tip, 'tip_home': None if won is None else float(won == g.home),
                 'first_fg_home': None if g.first_fg_team != g.first_fg_team else float(g.first_fg_team == g.home_id),
                 'first_pts_home': None if g.first_pts_team != g.first_pts_team else float(g.first_pts_team == g.home_id),
                 'first_fg_player': g.first_fg_player, 'line': g.line, 'total': g.total})
    if won and t1 and t2 and t1 != t2:                   # update the jumpers' records and each team's usual jumper
        for pid, tm in ((j1, t1), (j2, t2)):
            r_ = rec.setdefault(pid, [0, 0]); r_[1] += 1; r_[0] += float(won == tm)
            usual[tm] = pid
D = pd.DataFrame(rows)
TR, TE = D.season <= 2024, D.season >= 2025
z = D[TR].dropna(subset=['tip_home'])
print('games', len(D), '| tip: home won', round(z.tip_home.mean(), 3), '| rated favorite won', round(float(((z.p_tip_home > .5) == (z.tip_home == 1)).mean()), 3))
# tip calibration
b = pd.cut(D[TE].p_tip_home, [0, .35, .45, .55, .65, 1]); print(D[TE].groupby(b, observed=True).tip_home.agg(['size', 'mean']).round(3).to_dict())
# ---------------- team: first field goal and first points, from the tip and the spread
z = D[TR].dropna(subset=['first_fg_home', 'tip_home', 'line'])
q_fg = float((z.first_fg_home == z.tip_home).mean()); q_pts = float((z.first_pts_home == z.tip_home).mean())
print('tip winner makes the first FG', round(q_fg, 3), '| scores first', round(q_pts, 3))
def fit_team(col):
    zz = D[TR].dropna(subset=[col, 'line'])
    X = np.column_stack([np.ones(len(zz)), np.log(zz.p_tip_home / (1 - zz.p_tip_home)), -zz.line / 10])
    y = zz[col].values
    f = lambda w: -float(np.sum(y * (X @ w) - np.log1p(np.exp(X @ w))))
    return minimize(f, np.zeros(3)).x
w_fg, w_pts = fit_team('first_fg_home'), fit_team('first_pts_home')
def p_team(z, w):
    X = np.column_stack([np.ones(len(z)), np.log(z.p_tip_home / (1 - z.p_tip_home)), -z.line.fillna(0) / 10]); return 1 / (1 + np.exp(-(X @ w)))
te = D[TE].dropna(subset=['first_fg_home'])
pt = p_team(te, w_fg)
print('team first FG: weights', np.round(w_fg, 3), '| check log loss', round(float(-np.mean(te.first_fg_home * np.log(pt) + (1 - te.first_fg_home) * np.log(1 - pt))), 4), 'vs coin', round(np.log(2), 4))
# ---------------- player within team: conditional logit on (start chance, projected points)
C = P[P.played].merge(D[['game_id', 'home', 'first_fg_player']], on='game_id')
C = C[C.game_id.isin(set(D.game_id))]
C['side_home'] = C.team_abbreviation == C.home
fg_team = Q.set_index('game_id').first_fg_team.to_dict(); home_id = Q.set_index('game_id').home_id.to_dict()
C['team_first'] = [(fg_team.get(g) == home_id.get(g)) == h for g, h in zip(C.game_id, C.side_home)]
C = C[C.team_first]                                   # the team that made the first field goal
C['y'] = (C.athlete_id == C.first_fg_player).astype(float)
C = C[C.groupby('game_id').y.transform('sum') == 1]
C['ls'] = np.log(C.started_prev.clip(0.02, 1)); C['lp'] = np.log(C.pts_proj.clip(0.5))
def nll(w, z):
    u = w[0] * z.ls + w[1] * z.lp
    lse = u.groupby(z.game_id).transform(lambda s: np.log(np.exp(s - s.max()).sum()) + s.max())
    return -float((z.y * (u - lse)).sum())
ztr, zte = C[C.season <= 2024], C[C.season >= 2025]
wp = minimize(lambda w: nll(w, ztr), np.array([1.0, 1.0]), method='Nelder-Mead').x
print('player weights (start chance, projected points):', np.round(wp, 3), '| check log loss per game', round(nll(wp, zte) / zte.game_id.nunique(), 4),
      '| equal among starters would be', round(np.log(5), 4))
# ---------------- full chance and calibration on the check seasons
zte = zte.copy(); u = wp[0] * zte.ls + wp[1] * zte.lp
zte['share'] = np.exp(u) / np.exp(u).groupby(zte.game_id).transform('sum')
A = P[P.played & (P.season >= 2021)].merge(D[['game_id', 'home', 'first_fg_player', 'p_tip_home', 'line']], on='game_id')
A['ls'] = np.log(A.started_prev.clip(0.02, 1)); A['lp'] = np.log(A.pts_proj.clip(0.5))
u = wp[0] * A.ls + wp[1] * A.lp
A['share'] = np.exp(u) / np.exp(u).groupby([A.game_id, A.team_abbreviation]).transform('sum')
ph = p_team(A.assign(line=A.line), w_fg)
A['p'] = np.where(A.team_abbreviation == A.home, ph, 1 - ph) * A.share
A['y'] = (A.athlete_id == A.first_fg_player).astype(float)
A = A[A.first_fg_player.notna()]
# the very likeliest players come in a little less often than the product says: a Platt curve on the fit seasons
lg = lambda p: np.log(p / (1 - p))
Atr = A[A.season <= 2024]
cw = minimize(lambda w: -float(np.sum(Atr.y * (w[0] + w[1] * lg(Atr.p.clip(1e-4, .9))) - np.log1p(np.exp(w[0] + w[1] * lg(Atr.p.clip(1e-4, .9)))))), np.array([0.0, 1.0])).x
A['p_raw'] = A.p; A['p'] = 1 / (1 + np.exp(-(cw[0] + cw[1] * lg(A.p.clip(1e-4, .9)))))
print('Platt', np.round(cw, 3))
A = A[A.season >= 2025]
cal = A.groupby(pd.cut(A.p, [0, .02, .05, .08, .11, .14, .18, .25, 1]), observed=True).agg(n=('p', 'size'), p=('p', 'mean'), hit=('y', 'mean')).round(4)
print(cal.to_string())
# ---------------- against DraftKings' First Basket prices
pr = pd.read_csv(f'{RAW}/props/nba_props.csv.gz', low_memory=False)
pr = pr[pr.type == 'First Basket'].copy()
pr['odds'] = pd.to_numeric(pr.odds, errors='coerce'); pr = pr.dropna(subset=['odds'])
pr['imp'] = np.where(pr.odds > 0, 100 / (pr.odds + 100), -pr.odds / (-pr.odds + 100))
pr = pr.groupby(['event', 'athlete']).imp.last().reset_index()
m = A.merge(pr.rename(columns={'event': 'game_id', 'athlete': 'athlete_id'}).assign(athlete_id=lambda x: x.athlete_id.astype(float)), on=['game_id', 'athlete_id'])
cmp_ = {}
if len(m):
    # the saved prices cover about five players a game, so the book's hold can't be taken out: compare as priced
    ll = lambda p, y: float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    cmp_ = {'n': int(len(m)), 'games': int(m.game_id.nunique()), 'logloss_model': round(ll(m.p.clip(1e-4, .99), m.y), 5),
            'logloss_book_as_priced': round(ll(m.imp.clip(1e-4, .99), m.y), 5),
            'hit': round(float(m.y.mean()), 4), 'model_avg': round(float(m.p.mean()), 4), 'book_implied_avg': round(float(m.imp.mean()), 4)}
    # would betting the model's favorites at the book's price have paid? (prices with the vig)
    m['dec'] = np.where(m.imp > 0, 1 / m.imp, np.nan)
    for edge in (0.0, 0.02, 0.04):
        bet = m[m.p > m.imp + edge]
        cmp_[f'roi_model_above_price_by_{edge}'] = [int(len(bet)), round(float((bet.y * bet.dec - 1).mean()), 3) if len(bet) else None]
print('vs DraftKings', cmp_)
# ---------------- the site's numbers: the same fits on the latest four seasons, so they follow how the game is played now
LAST4 = D.season >= 2023
TRs = TR
TR = LAST4
w_fg_p, w_pts_p = fit_team('first_fg_home'), fit_team('first_pts_home')
q_fg_p = float((D[LAST4].dropna(subset=['first_fg_home', 'tip_home']).pipe(lambda z: (z.first_fg_home == z.tip_home).mean())))
wp_p = minimize(lambda w: nll(w, C[C.season >= 2023]), np.array([1.0, 1.0]), method='Nelder-Mead').x
print('site fit (2022-23 to 2025-26): team', np.round(w_fg_p, 3), 'points', np.round(w_pts_p, 3), 'player', np.round(wp_p, 3))
out = {'site_fit_seasons': [2023, 2026], 'site': {'team_first_fg': [round(float(v), 4) for v in w_fg_p], 'team_first_points': [round(float(v), 4) for v in w_pts_p],
                                                  'player': [round(float(v), 4) for v in wp_p], 'tip_winner_first_fg': round(q_fg_p, 4), 'tip_prior': [3, 6]},
       'fit_seasons': [2021, 2024], 'check_seasons': [2025, 2026], 'tip_prior': [3, 6], 'tip_winner_first_fg': round(q_fg, 4), 'tip_winner_first_points': round(q_pts, 4),
       'team_first_fg': [round(float(v), 4) for v in w_fg], 'team_first_points': [round(float(v), 4) for v in w_pts], 'player': [round(float(v), 4) for v in wp], 'platt': [round(float(v), 4) for v in cw],
       'check': {'calibration': [[str(i), int(r.n), float(r.p), float(r.hit)] for i, r in cal.iterrows()], 'vs_draftkings': cmp_}}
# every jumper's opening-tip record since 2020-21, the site's starting point (the build adds this season's tips as they happen)
out['jumpers'] = {str(int(k)): v for k, v in rec.items() if v[1] >= 3}
json.dump(out, open(f'{WORK}/nba_first_basket.json', 'w'), indent=1)
