"""When rotation players sit, who gets their minutes and shots? Fit on 2015-16 to 2022-23, checked on 2023-24 to 2025-26.

A player is missing when he averaged 15+ minutes (weighted toward recent games) in the team's last 10 games and didn't
play. His teammates' recent averages already include the games he has missed, so what is still "new" decays with each
game he has been out: half-life 5 games for minutes (the minutes average's own half-life) and 18 for per-minute rates.

Minutes: each teammate gains a * (new missing minutes) * (his projected minutes) / (the team's other projected minutes),
with a separate pull for teammates at the same position (guard, forward, center).
Rates: each per-minute rate rises by b * (new missing production of that stat) / (the team's remaining production).
Compared with the projection the site used before (no bump; minutes scaled up at most 15%). -> work/nba_injury_bump.json"""
import json, numpy as np, pandas as pd
WORK = 'work'
P = pd.read_pickle(f'{WORK}/nba_player_box.pkl')
d = pd.read_pickle(f'{WORK}/nba_proj.pkl')
STATS = ['pts', 'reb', 'ast', 'fg3m']
P = P.sort_values(['t', 'game_id'])
for k, c in {'pts': 'points', 'reb': 'rebounds', 'ast': 'assists', 'fg3m': 'three_point_field_goals_made'}.items():
    P[k] = P[c].fillna(0)
P['pos1'] = P.athlete_position_abbreviation.fillna('F').str[0].replace({'P': 'G', 'S': 'G'})
aM = 0.5 ** (1 / 5)
rows = []
for team, x in P.groupby('team_abbreviation'):
    st = {}                     # pid -> dict(min, pts, reb, ast, fg3m (ew per game), last (game idx), pos)
    for i, (gid, g) in enumerate(x.groupby('game_id', sort=False)):
        played = set(g[g.played].athlete_id)
        miss = {'vm': 0.0, 'vm_G': 0.0, 'vm_F': 0.0, 'vm_C': 0.0, **{f'v_{k}': 0.0 for k in STATS}}
        names = 0
        for pid, s in st.items():
            j = i - s['last'] - 1                       # team games he has already missed
            if j > 9 or s['min'] < 15 or pid in played:
                continue
            wm, wr = 0.5 ** (j / 5), 0.5 ** (j / 18)
            miss['vm'] += s['min'] * wm; miss['vm_' + s['pos']] += s['min'] * wm
            for k in STATS:
                miss[f'v_{k}'] += s[k] * wr
            names += 1
        rows.append({'game_id': gid, 'team_abbreviation': team, 'n_out': names, **miss})
        for r in g[g.played].itertuples():
            s = st.get(r.athlete_id)
            if s is None:
                st[r.athlete_id] = {'min': r.min, **{k: getattr(r, k) for k in STATS}, 'last': i, 'pos': r.pos1, 'n': 1}
            else:
                w = min(aM, 1 - 1 / (s['n'] + 1))
                s['min'] = w * s['min'] + (1 - w) * r.min
                for k in STATS:
                    s[k] = w * s[k] + (1 - w) * getattr(r, k)
                s['last'] = i; s['n'] += 1
MS = pd.DataFrame(rows)
d = d.merge(MS, on=['game_id', 'team_abbreviation'], how='left')
d = d[d.min_proj.notna() & (d.n_prev >= 5) & (d.min_ew >= 8)].copy()
# the team's projections among the players who did play
tm = d.groupby(['game_id', 'team_abbreviation'])
d['team_min'] = tm.min_proj.transform('sum')
for k in STATS:
    d[f'team_{k}'] = tm[k + '_proj'].transform('sum')
d['g_min'] = d.vm * d.min_proj / d.team_min.clip(lower=150)
d['g_min_same'] = np.select([d.pos1 == 'G', d.pos1 == 'F', d.pos1 == 'C'], [d.vm_G, d.vm_F, d.vm_C], 0) * d.min_proj / d.team_min.clip(lower=150)
TR = (d.season >= 2016) & (d.season <= 2023); TE = d.season >= 2024
hit = d.vm > 1
out = {'fit': {}, 'check': {}}
# ---------------- minutes: the gain depends on how much room a player has (bench players absorb most of it)
BK = [0, 15, 24, 31, 99]
d['bk'] = np.digitize(d.min_proj, BK[1:-1])
d['vm_same'] = np.select([d.pos1 == 'G', d.pos1 == 'F', d.pos1 == 'C'], [d.vm_G, d.vm_F, d.vm_C], 0)
d['vm_other'] = d.vm - d.vm_same
def X(z):
    cols = []
    for b in range(4):
        cols += [z.vm_same * (z.bk == b), z.vm_other * (z.bk == b)]
    return np.column_stack(cols).astype(float)
tr = d[TR & hit]
ab = np.linalg.lstsq(X(tr), tr['min'] - tr.min_proj, rcond=None)[0]
out['fit']['min'] = {'buckets': BK, 'same': [round(float(ab[2 * b]), 3) for b in range(4)], 'other': [round(float(ab[2 * b + 1]), 3) for b in range(4)]}
te = d[TE & hit].copy()
te['m_new'] = np.clip(te.min_proj + X(te) @ ab, 0, 44)
te['m_old'] = np.clip(te.min_proj * np.minimum(1.15, (te.team_min + 0.8 * te.vm) / te.team_min), 0, 44)
out['check']['minutes'] = {'n': len(te), 'mae_plain': round(float((te['min'] - te.min_proj).abs().mean()), 3), 'mae_before': round(float((te['min'] - te.m_old).abs().mean()), 3),
                           'mae_new': round(float((te['min'] - te.m_new).abs().mean()), 3), 'bias_plain': round(float((te['min'] - te.min_proj).mean()), 3),
                           'bias_before': round(float((te['min'] - te.m_old).mean()), 3), 'bias_new': round(float((te['min'] - te.m_new).mean()), 3)}
fresh = te[te.vm_same >= 25]
out['check']['minutes_fresh_same_position_starter_out'] = {'n': len(fresh), 'mae_plain': round(float((fresh['min'] - fresh.min_proj).abs().mean()), 3),
    'mae_new': round(float((fresh['min'] - fresh.m_new).abs().mean()), 3), 'bias_plain': round(float((fresh['min'] - fresh.min_proj).mean()), 3),
    'bias_new': round(float((fresh['min'] - fresh.m_new).mean()), 3)}
print('minutes', out['fit']['min'], out['check']['minutes'], out['check']['minutes_fresh_same_position_starter_out'])
# ---------------- per-minute rates
d['m_new'] = np.clip(d.min_proj + X(d) @ ab, 0, 44)
for k in STATS:
    d[f'u_{k}'] = d[f'v_{k}'] / d[f'team_{k}'].clip(lower=1)
    tr = d[TR & hit & (d[k + '_proj'] > 0.3)]
    base = tr[k + '_proj'] * tr.m_new / tr.min_proj.clip(lower=1)          # minutes-adjusted projection
    b = float(((tr[k] - base) * base * tr[f'u_{k}']).sum() / ((base * tr[f'u_{k}']) ** 2).sum())
    out['fit'][k] = round(b, 3)
    te = d[TE & hit & (d[k + '_proj'] > 0.3)]
    p_plain = te[k + '_proj']
    p_old = te[k + '_proj'] * np.minimum(1.15, (te.team_min + 0.8 * te.vm) / te.team_min)
    p_min = te[k + '_proj'] * te.m_new / te.min_proj.clip(lower=1)
    p_new = p_min * (1 + b * te[f'u_{k}'])
    out['check'][k] = {'n': len(te), **{f'mae_{nm}': round(float((te[k] - p).abs().mean()), 3) for nm, p in (('plain', p_plain), ('before', p_old), ('minutes_only', p_min), ('new', p_new))},
                       **{f'bias_{nm}': round(float((te[k] - p).mean()), 3) for nm, p in (('plain', p_plain), ('before', p_old), ('new', p_new))}}
    print(k, b, out['check'][k])
# how big the bump typically is when a starter-level player (30+ minutes) has just gone out
big = d[TE & (d.vm >= 30)]
out['typical'] = {'n': len(big), 'min_gain': round(float((big.m_new - big.min_proj).mean()), 2),
                  'pts_gain_pct': round(float(((big.m_new / big.min_proj.clip(lower=1)) * (1 + out['fit']['pts'] * big.u_pts) - 1).mean() * 100), 1)}
print('typical', out['typical'])
json.dump(out, open(f'{WORK}/nba_injury_bump.json', 'w'), indent=1)

# ---------------- the case people ask about: a same-position player with 25+ minutes has just gone out
fresh = d[TE & (d.vm_same >= 25)]
out['check']['fresh_stats'] = {}
for k in STATS:
    z = fresh[fresh[k + '_proj'] > 0.3]
    p_plain = z[k + '_proj']; p_min = z[k + '_proj'] * z.m_new / z.min_proj.clip(lower=1); p_new = p_min * (1 + out['fit'][k] * z[f'u_{k}'])
    out['check']['fresh_stats'][k] = {'n': len(z), **{f'mae_{nm}': round(float((z[k] - p).abs().mean()), 3) for nm, p in (('plain', p_plain), ('minutes_only', p_min), ('new', p_new))},
                                     **{f'bias_{nm}': round(float((z[k] - p).mean()), 3) for nm, p in (('plain', p_plain), ('minutes_only', p_min), ('new', p_new))}}
    print('fresh', k, out['check']['fresh_stats'][k])
json.dump(out, open(f'{WORK}/nba_injury_bump.json', 'w'), indent=1)
