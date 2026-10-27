"""NBA game model: opponent-adjusted efficiency ratings updated game by game, home court, rest.
Walk-forward: every prediction uses only games before it. Graded against the closing line."""
import pandas as pd, numpy as np, json, sys, itertools
WORK = 'work'
g = pd.read_pickle(f'{WORK}/nba_games.pkl')
tb = pd.read_pickle(f'{WORK}/nba_team_box.pkl')
g = g[g.status_type_completed.astype(str).isin(['True', 'true', '1']) & g.hs.notna()].copy()
g = g[g.home.str.len() <= 4]   # drop all-star style exhibitions if any slipped in
box = tb.set_index(['game_id', 'team_abbreviation'])
def poss_of(gid, h, a):
    try:
        x = box.loc[(gid, h)]; y = box.loc[(gid, a)]
        return float((x.poss + y.poss) / 2)
    except KeyError:
        return np.nan
g['poss'] = [poss_of(r.gid, r.home, r.away) for r in g.itertuples()]
g['poss'] = g.poss.fillna(g.groupby('season').poss.transform('median'))
g = g.sort_values('t').reset_index(drop=True)

def run(H=20, carry=0.55, hca0=2.4, pace_h=25, verbose=False):
    """Ratings: per-100 offense and defense, opponent-adjusted, exponentially weighted with half-life H games."""
    a = 0.5 ** (1 / H); ap = 0.5 ** (1 / pace_h)
    O, Dd, P, last, nG = {}, {}, {}, {}, {}
    lg_eff, lg_pace = 110.0, 98.0
    season = None
    out = []
    for r in g.itertuples():
        if r.season != season:            # new season: regress toward the league
            season = r.season
            for t in list(O): O[t] *= carry; Dd[t] *= carry
            nG = {}
        h, w = r.home, r.away
        for t in (h, w):
            O.setdefault(t, 0.0); Dd.setdefault(t, 0.0); P.setdefault(t, lg_pace)
        dd = pd.Timestamp(r.day)                      # rest counts calendar days (Eastern): back-to-back = played yesterday
        rest_h = (dd - last[h]).days if h in last else 7
        rest_a = (dd - last[w]).days if w in last else 7
        pace = (P[h] + P[w]) / 2
        # predicted points per 100 for each side, then scaled by pace
        eff_h = lg_eff + O[h] - Dd[w]; eff_a = lg_eff + O[w] - Dd[h]
        pred_margin = (eff_h - eff_a) * pace / 100
        pred_total = (eff_h + eff_a) * pace / 100
        out.append({'gid': r.gid, 'season': r.season, 'st': r.season_type, 'n_h': nG.get(h, 0), 'n_a': nG.get(w, 0), 'rate_m': pred_margin, 'rate_t': pred_total,
                    'rest_h': min(rest_h, 7), 'rest_a': min(rest_a, 7), 'neutral': bool(r.neutral_site), 'pace': pace, 'O_h': O[h], 'D_h': Dd[h], 'O_a': O[w], 'D_a': Dd[w]})
        # update with the result (home court removed from the observation)
        ph = r.poss
        if ph and ph > 50:
            off_h = r.hs / ph * 100; off_a = r.as_ / ph * 100
            hadj = 0 if r.neutral_site else hca0 / 2 / ph * 100 * (ph / 100)
            # observed efficiency over expectation, credited to offense and defense
            e_h = off_h - hadj - (lg_eff + O[h] - Dd[w]); e_a = off_a + hadj - (lg_eff + O[w] - Dd[h])
            O[h] += (1 - a) * e_h; Dd[w] -= (1 - a) * e_h
            O[w] += (1 - a) * e_a; Dd[h] -= (1 - a) * e_a
            lg_eff = 0.995 * lg_eff + 0.005 * (off_h + off_a) / 2
            P[h] = ap * P[h] + (1 - ap) * ph; P[w] = ap * P[w] + (1 - ap) * ph
            lg_pace = 0.995 * lg_pace + 0.005 * ph
        last[h] = dd; last[w] = dd; nG[h] = nG.get(h, 0) + 1; nG[w] = nG.get(w, 0) + 1
    return pd.DataFrame(out)

def evaluate(f, quiet=False):
    d = g[['gid', 'season', 'margin', 'line', 'total', 'hs', 'as_', 'ml_home', 'ml_away', 't']].merge(f.drop(columns=['season']), on='gid')
    d['tot'] = d.hs + d.as_
    d['b2b_h'] = (d.rest_h <= 1).astype(int); d['b2b_a'] = (d.rest_a <= 1).astype(int)
    d['hfa'] = (~d.neutral).astype(int)
    d['rest_diff'] = d.rest_h.clip(0, 3) - d.rest_a.clip(0, 3)
    res = []
    for test in range(2016, 2027):
        tr = d[(d.season < test) & (d.season >= test - 4) & (d.n_h >= 5) & (d.n_a >= 5)]
        te = d[(d.season == test)].copy()
        X = lambda x: np.column_stack([np.ones(len(x)), x.rate_m, x.hfa, x.b2b_h, x.b2b_a])
        beta = np.linalg.lstsq(X(tr), tr.margin, rcond=None)[0]
        te['pm'] = X(te) @ beta
        Xt = lambda x: np.column_stack([np.ones(len(x)), x.rate_t, x.b2b_h + x.b2b_a])
        bt = np.linalg.lstsq(Xt(tr), tr.tot, rcond=None)[0]
        te['pt'] = Xt(te) @ bt
        res.append(te)
    r = pd.concat(res)
    r = r[r.line.notna()]
    r['mkt'] = -r.line
    out = {'n': len(r), 'rmse_model': float(np.sqrt(((r.margin - r.pm) ** 2).mean())), 'rmse_line': float(np.sqrt(((r.margin - r.mkt) ** 2).mean())),
           'corr_model': float(np.corrcoef(r.pm, r.margin)[0, 1]), 'corr_line': float(np.corrcoef(r.mkt, r.margin)[0, 1])}
    # does the model add anything to the line? regress margin on line and (model - line)
    Z = np.column_stack([np.ones(len(r)), r.mkt, r.pm - r.mkt]); bz = np.linalg.lstsq(Z, r.margin, rcond=None)[0]
    out['beta_gap'] = float(bz[2])
    for thr in (2, 3, 4, 5, 6):
        e = r[abs(r.pm - r.mkt) >= thr]
        cover = np.sign(e.margin + e.line)          # + = home covered
        pick_home = np.sign(e.pm - e.mkt)
        w = (cover * pick_home > 0).sum(); l = (cover * pick_home < 0).sum()
        out[f'ats_{thr}'] = [int(w), int(l), round(w / max(1, w + l), 4)]
    rt = r[r.total.notna()]
    out['rmse_t_model'] = float(np.sqrt(((rt.tot - rt.pt) ** 2).mean())); out['rmse_t_line'] = float(np.sqrt(((rt.tot - rt.total) ** 2).mean()))
    for thr in (3, 5, 7):
        e = rt[abs(rt.pt - rt.total) >= thr]; side = np.sign(e.pt - e.total); res_ = np.sign(e.tot - e.total)
        w = (side * res_ > 0).sum(); l = (side * res_ < 0).sum()
        out[f'ou_{thr}'] = [int(w), int(l), round(w / max(1, w + l), 4)]
    if not quiet: print(json.dumps(out))
    return out, r

if __name__ == '__main__':
    best = None
    for H, carry in itertools.product((12, 20, 30, 45), (0.4, 0.6, 0.75)):
        o, _ = evaluate(run(H=H, carry=carry), quiet=True)
        print(H, carry, round(o['rmse_model'], 3), round(o['rmse_line'], 3), o['ats_3'], o['ats_5'], round(o['rmse_t_model'], 2), round(o['rmse_t_line'], 2), o['ou_5'], round(o['beta_gap'], 3))
        if best is None or o['rmse_model'] < best[0]: best = (o['rmse_model'], H, carry)
    print('best', best)
