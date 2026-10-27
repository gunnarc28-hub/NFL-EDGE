"""NHL game model: online Poisson ratings from goals and shots, the starting goalie's save rate, home ice and rest.
Walk-forward; graded against closing moneylines and totals."""
import pandas as pd, numpy as np, json, itertools, math
from scipy.stats import poisson
WORK = 'work'
g = pd.read_pickle(f'{WORK}/nhl_games.pkl')
g = g[g.game_state.isin(['OFF', 'FINAL']) & g.hs.notna()].copy().sort_values('t').reset_index(drop=True)
gb = pd.read_pickle(f'{WORK}/nhl_goalie_box.pkl'); sk = pd.read_pickle(f'{WORK}/nhl_skater_box.pkl')
# shots for each side from skaters (consistent across seasons)
shots = sk.groupby(['game_id', 'team_abbrev']).shots_on_goal.sum().rename('sog').reset_index()
S = {(r.game_id, r.team_abbrev): r.sog for r in shots.itertuples()}
# starting goalie per team-game and his saves/shots
gb['toi_m'] = gb.toi.astype(str).str.split(':').apply(lambda x: int(x[0]) + int(x[1]) / 60 if len(x) == 2 and x[0].isdigit() else 0)
gb['is_start'] = gb.starter.astype(str).isin(['True', 'true', '1'])
st = gb[gb.is_start].drop_duplicates(['game_id', 'team_abbrev'])
STARTER = {(r.game_id, r.team_abbrev): r.player_id for r in st.itertuples()}
GL = {(r.game_id, r.player_id): (r.saves, r.shots_against) for r in gb.itertuples() if r.shots_against == r.shots_against}
g['sog_h'] = [S.get((r.gid, r.home), np.nan) for r in g.itertuples()]; g['sog_a'] = [S.get((r.gid, r.away), np.nan) for r in g.itertuples()]
g['gk_h'] = [STARTER.get((r.gid, r.home)) for r in g.itertuples()]; g['gk_a'] = [STARTER.get((r.gid, r.away)) for r in g.itertuples()]
print('games', len(g), 'with shots', g.sog_h.notna().mean().round(3), 'with starters', g.gk_h.notna().mean().round(3))
g.to_pickle(f'{WORK}/nhl_games_plus.pkl')

def win_prob(lh, la, ot_h=0.5, maxg=12):
    ph = poisson.pmf(np.arange(maxg), lh); pa = poisson.pmf(np.arange(maxg), la)
    m = np.outer(ph, pa)
    p_h = np.tril(m, -1).sum(); p_t = np.trace(m)
    return p_h + p_t * ot_h, m

def run(H=25, Hs=25, w_shot=0.5, carry=0.6, gk_prior=900, Hg=60, hca=0.06, verbose=False):
    a = 0.5 ** (1 / H); as_ = 0.5 ** (1 / Hs); ag = 0.5 ** (1 / Hg)
    O, Dd, SO, SD, last = {}, {}, {}, {}, {}
    GK = {}                       # goalie -> [ew saves, ew shots]
    lg_g, lg_s = 2.95, 30.5
    season = None; out = []
    for r in g.itertuples():
        if r.season != season:
            season = r.season
            for t in list(O): O[t] *= carry; Dd[t] *= carry; SO[t] *= carry; SD[t] *= carry
        h, w = r.home, r.away
        for t in (h, w):
            for X in (O, Dd, SO, SD): X.setdefault(t, 0.0)
        lg_sv = 1 - lg_g / lg_s
        def gk_sv(pid):
            if pid is None or pid not in GK: return lg_sv
            sv, sh = GK[pid]; return (sv + lg_sv * gk_prior) / (sh + gk_prior)
        sv_h, sv_a = gk_sv(r.gk_h), gk_sv(r.gk_a)
        # expected goals: blend of goal ratings and shot ratings x league shooting, then the opposing goalie
        eg_h_goal = lg_g * math.exp(O[h] - Dd[w] + hca / 2); eg_a_goal = lg_g * math.exp(O[w] - Dd[h] - hca / 2)
        es_h = lg_s * math.exp(SO[h] - SD[w] + hca / 2); es_a = lg_s * math.exp(SO[w] - SD[h] - hca / 2)
        eg_h_shot = es_h * (1 - lg_sv); eg_a_shot = es_a * (1 - lg_sv)
        lam_h = (w_shot * eg_h_shot + (1 - w_shot) * eg_h_goal) * (1 - sv_a) / (1 - lg_sv)
        lam_a = (w_shot * eg_a_shot + (1 - w_shot) * eg_a_goal) * (1 - sv_h) / (1 - lg_sv)
        dd = pd.Timestamp(r.day)
        rest_h = (dd - last[h]).days if h in last else 5; rest_a = (dd - last[w]).days if w in last else 5
        out.append({'gid': r.gid, 'season': r.season, 'gt': r.game_type, 'lam_h': lam_h, 'lam_a': lam_a, 'rest_h': min(rest_h, 5), 'rest_a': min(rest_a, 5), 'sv_h': sv_h, 'sv_a': sv_a})
        # updates (remove home ice from the observation)
        gh, ga = r.hs, r.as_
        # a shootout goal isn't a real goal for ratings: cap a one-goal OT/SO result at the regulation tie
        O[h] += (1 - a) * (math.log((gh + 0.5) / (eg_h_goal + 0.5))) ; Dd[w] -= (1 - a) * (math.log((gh + 0.5) / (eg_h_goal + 0.5)))
        O[w] += (1 - a) * (math.log((ga + 0.5) / (eg_a_goal + 0.5))) ; Dd[h] -= (1 - a) * (math.log((ga + 0.5) / (eg_a_goal + 0.5)))
        if r.sog_h == r.sog_h and r.sog_a == r.sog_a and r.sog_h > 5 and r.sog_a > 5:
            SO[h] += (1 - as_) * math.log(r.sog_h / es_h); SD[w] -= (1 - as_) * math.log(r.sog_h / es_h)
            SO[w] += (1 - as_) * math.log(r.sog_a / es_a); SD[h] -= (1 - as_) * math.log(r.sog_a / es_a)
            lg_s = 0.998 * lg_s + 0.002 * (r.sog_h + r.sog_a) / 2
        lg_g = 0.998 * lg_g + 0.002 * (gh + ga) / 2
        for side in ('h', 'a'):
            pid = r.gk_h if side == 'h' else r.gk_a
            if pid is None: continue
            x = GL.get((r.gid, pid))
            if not x: continue
            sv, sh = x
            cur = GK.get(pid, [0.0, 0.0]); GK[pid] = [ag * cur[0] + sv, ag * cur[1] + sh]
        last[h] = dd; last[w] = dd
    return pd.DataFrame(out)

def novig(a, b):
    pa = (-a / (-a + 100)) if a < 0 else 100 / (a + 100); pb = (-b / (-b + 100)) if b < 0 else 100 / (b + 100)
    return pa / (pa + pb)

def evaluate(f, quiet=False, b2b_adj=0.0):
    d = g[['gid', 'season', 'hs', 'as_', 'ml_home', 'ml_away', 'total', 'over_odds', 'under_odds', 'game_type']].merge(f.drop(columns=['season']), on='gid')
    d = d[d.season >= 2016]
    d['lam_h'] *= np.where(d.rest_h <= 1, 1 - b2b_adj, 1); d['lam_a'] *= np.where(d.rest_a <= 1, 1 - b2b_adj, 1)
    ps, tots = [], []
    for r in d.itertuples():
        p, m = win_prob(r.lam_h, r.lam_a); ps.append(p)
    d['p_h'] = ps
    d['y'] = (d.hs > d.as_).astype(int)
    v = d[d.ml_home.notna() & d.ml_away.notna()].copy()
    v['mkt'] = [novig(a, b) for a, b in zip(v.ml_home, v.ml_away)]
    ll = lambda p, y: -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    o = {'n': len(v), 'll_model': round(ll(v.p_h, v.y), 4), 'll_mkt': round(ll(v.mkt, v.y), 4), 'brier_model': round(float(((v.p_h - v.y) ** 2).mean()), 4), 'brier_mkt': round(float(((v.mkt - v.y) ** 2).mean()), 4)}
    dec = lambda x: 1 + (x / 100 if x > 0 else 100 / -x)
    for thr in (0.03, 0.05, 0.08):
        bets = []
        for r in v.itertuples():
            if r.p_h - r.mkt >= thr: bets.append(r.y * dec(r.ml_home) - 1)
            elif r.mkt - r.p_h >= thr: bets.append((1 - r.y) * dec(r.ml_away) - 1)
        o[f'roi_{thr}'] = [len(bets), round(float(np.mean(bets)), 4) if bets else None]
    if not quiet: print(o)
    return o, v

if __name__ == '__main__':
    for H, w_shot, carry, gk_prior in itertools.product((20, 35), (0.3, 0.6), (0.5, 0.7), (600, 1500)):
        o, _ = evaluate(run(H=H, Hs=H, w_shot=w_shot, carry=carry, gk_prior=gk_prior), quiet=True)
        print(H, w_shot, carry, gk_prior, o)
