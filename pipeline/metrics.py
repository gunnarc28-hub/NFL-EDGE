"""Per-game team metric values (offense, defense allowed, net) and Bayesian-style pre-game ratings.
The weights, shrinkage and stability values come from static/team_research.json (fit on 2017-2025)."""
import numpy as np, pandas as pd

LOWER_BETTER = {'sack_rate', 'int_rate', 'to', 'pen'}   # for an offense, lower is better


def ratio(a, b):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(b > 0, a / np.where(b > 0, b, 1), np.nan)


def team_metric_frame(tg):
    """One row per team-game with o_*, d_* and n_* (net, higher = better) metric values."""
    tg = tg.sort_values(['season', 'week', 'game_id']).reset_index(drop=True)
    m = pd.DataFrame({'game_id': tg.game_id, 'team': tg.team, 'opp': tg.opp, 'season': tg.season, 'week': tg.week,
                      'home': tg.home, 'pf': tg.pf, 'pa': tg.pa, 'spread_line': tg.spread_line,
                      'total_line': tg.total_line, 'roof': tg.roof})
    O, D = {}, {}
    O['epa_play'] = ratio(tg.epa_sum, tg.plays);           D['epa_play'] = ratio(tg.d_epa_sum, tg.d_plays)
    O['success'] = ratio(tg.succ_sum, tg.plays);           D['success'] = ratio(tg.d_succ_sum, tg.d_plays)
    O['pass_epa'] = ratio(tg.pass_epa_sum, tg.dropbacks);  D['pass_epa'] = ratio(tg.d_pass_epa_sum, tg.d_dropbacks)
    O['rush_epa'] = ratio(tg.rush_epa_sum, tg.rushes);     D['rush_epa'] = ratio(tg.d_rush_epa_sum, tg.d_rushes)
    O['ypp'] = ratio(tg.yds_sum, tg.plays);                D['ypp'] = ratio(tg.d_yds_sum, tg.d_plays)
    O['anya'] = ratio(tg.anya_num, tg.anya_den);           D['anya'] = ratio(tg.d_anya_num, tg.d_anya_den)
    O['explosive'] = ratio(tg.explosive_n, tg.plays);      D['explosive'] = ratio(tg.d_explosive_n, tg.d_plays)
    O['sack_rate'] = ratio(tg.sacks, tg.dropbacks);        D['sack_rate'] = ratio(tg.d_sacks, tg.d_dropbacks)
    O['int_rate'] = ratio(tg.ints, tg.dropbacks);          D['int_rate'] = ratio(tg.d_ints, tg.d_dropbacks)
    O['to'] = tg.to_n.values;                              D['to'] = tg.d_to_n.values
    O['third'] = ratio(tg.third_conv, tg.third_conv + tg.third_fail)
    D['third'] = ratio(tg.d_third_conv, tg.d_third_conv + tg.d_third_fail)
    O['rz_td'] = ratio(tg.rz_tds, tg.rz_trips);            D['rz_td'] = ratio(tg.d_rz_tds, tg.d_rz_trips)
    O['ppd'] = ratio(tg.drive_pts, tg.drives);             D['ppd'] = ratio(tg.d_drive_pts, tg.d_drives)
    O['early_epa'] = ratio(tg.early_epa_sum, tg.early_n);  D['early_epa'] = ratio(tg.d_early_epa_sum, tg.d_early_n)
    O['pts'] = tg.pf.values;                               D['pts'] = tg.pa.values
    O['ypg'] = tg.yds_sum.values;                          D['ypg'] = tg.d_yds_sum.values
    O['rush_ypg'] = tg.rush_yds.values;                    D['rush_ypg'] = tg.d_rush_yds.values
    O['top'] = tg.top_s.values / 60;                       D['top'] = tg.d_top_s.values / 60
    O['pen'] = tg.pen_yds.values;                          D['pen'] = tg.d_pen_yds.values
    O['plays'] = tg.plays.values;                          D['plays'] = tg.d_plays.values
    O['proe'] = tg.proe.values;                            D['proe'] = tg.d_proe.values
    cols = {}
    for k in O:
        cols['o_' + k] = np.asarray(O[k], dtype=float); cols['d_' + k] = np.asarray(D[k], dtype=float)
        if k in ('plays', 'proe'):
            continue
        cols['n_' + k] = (cols['d_' + k] - cols['o_' + k]) if k in LOWER_BETTER else (cols['o_' + k] - cols['d_' + k])
    cols['n_win'] = np.where(m.pf > m.pa, 1.0, np.where(m.pf == m.pa, 0.5, 0.0))
    return pd.concat([m, pd.DataFrame(cols)], axis=1)


def add_pregame(m, params):
    """pre_<col>: rating entering each game = (k*prior + sum of earlier games this season) / (k + n),
    prior = league mean + rho * (team's previous-season mean - league mean)."""
    m = m.sort_values(['season', 'team', 'week']).reset_index(drop=True)
    new = {}
    for col, pr in params.items():
        if col not in m.columns:
            continue
        k, rho, mu = pr['k'], pr['rho'], pr['league_mean']
        season_mean = m.groupby(['season', 'team'])[col].mean()
        prev = pd.Series([season_mean.get((s - 1, t), np.nan) for s, t in zip(m.season, m.team)], index=m.index)
        prior = np.where(prev.notna(), mu + rho * (prev - mu), mu)
        x = m[col]
        key = [m.season, m.team]
        csum = x.fillna(0).groupby(key).cumsum() - x.fillna(0)
        cnt = x.notna().astype(float).groupby(key).cumsum() - x.notna().astype(float)
        new['pre_' + col] = (k * prior + csum) / (k + cnt)
    return pd.concat([m, pd.DataFrame(new, index=m.index)], axis=1)


def post_ratings(m, params, season, teams):
    """Rating after every game played so far this season (what the next game uses)."""
    cur = m[m.season == season]; prev = m[m.season == season - 1]
    out = {}
    for col, pr in params.items():
        if col not in m.columns:
            continue
        k, rho, mu = pr['k'], pr['rho'], pr['league_mean']
        out[col] = {}
        for t in teams:
            pv = prev.loc[prev.team == t, col].mean()
            prior = mu + rho * (pv - mu) if pd.notna(pv) else mu
            vals = cur.loc[cur.team == t, col].dropna()
            out[col][t] = float((k * prior + vals.sum()) / (k + len(vals)))
    return out
