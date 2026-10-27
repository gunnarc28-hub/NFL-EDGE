"""When a regular misses a game, how much of his workload goes to each teammate, and does projecting it help?

With/without splits (13a) show the work stays inside the position: a missing WR's targets go mostly to the other WRs, a
missing TE's to the backup TE, a missing RB's carries to the other backs; players at other positions barely move.

So for every team game 2018-2025: a regular is absent when he played 2+ of the team's previous 4 games with a real role
(8%+ of targets or 15%+ of carries) and has no line in this game. Each teammate at his position gains
    k[pos] * (his share) * (teammate's share / the position's remaining share),
weighted by how many of the teammate's games came with him on the field (a share earned while he was already out has the
gain in it). k is fit on 2018-2022 by position. Then the site's own projections are multiplied by 1 + g * (m - 1),
m the teammate's new share over his old one, g fit per stat on 2018-2022, and checked on 2023-2025. -> work/injury_bump.json"""
import json, numpy as np, pandas as pd
d = pd.read_pickle('work/player_hist_features.pkl')
d = d[(d.season_type == 'REG') & d.position.isin(['WR', 'TE', 'RB', 'QB'])].copy()
MODELS = json.load(open('repo/pipeline/static/player_research.json'))['models']
d['ts'] = d.targets / d.team_tgt.replace(0, np.nan); d['cs'] = d.carries / d.team_car.replace(0, np.nan)
tg = d.drop_duplicates(['season', 'team', 'game_id'])[['season', 'team', 'week', 'game_id']].sort_values(['season', 'team', 'week'])
tg['gi'] = tg.groupby(['season', 'team']).cumcount()
d = d.merge(tg[['season', 'team', 'game_id', 'gi']], on=['season', 'team', 'game_id']).sort_values(['player_id', 'season', 'team', 'gi'])
d['ts_run'] = d.groupby(['player_id', 'season', 'team']).ts.transform(lambda s: s.expanding().mean())
d['cs_run'] = d.groupby(['player_id', 'season', 'team']).cs.transform(lambda s: s.expanding().mean())
APPS = {}
for (s_, t_, pid), v in d.groupby(['season', 'team', 'player_id']).gi:
    APPS.setdefault((s_, t_), []).append((pid, set(v)))
LAST = {(r.season, r.team, r.player_id, r.gi): (r.ts_run, r.cs_run, r.position) for r in d.itertuples()}
POS = ('WR', 'TE', 'RB')

rows = []
for (season, team, gi), x in d.groupby(['season', 'team', 'gi']):
    if gi < 2:
        continue
    present = set(x.player_id)
    absent = []
    for pid, gis in APPS[(season, team)]:
        if pid in present:
            continue
        played = [i for i in range(max(0, gi - 4), gi) if i in gis]
        if len(played) < 2 or max(played) < gi - 2:
            continue
        ts, cs, pos = LAST[(season, team, pid, max(played))]
        ts = 0.0 if pd.isna(ts) else ts; cs = 0.0 if pd.isna(cs) else cs
        if pos in POS and (ts >= 0.08 or cs >= 0.15):
            absent.append((pid, ts, cs, pos, gis))
    if not absent:
        continue
    x = x[x.position.isin(POS) & (x.n_prior >= 3)]
    S_t = x.groupby('position').avg_target_share.sum().to_dict(); S_c = x.groupby('position').avg_carry_share.sum().to_dict()
    mine = {pid: {i for i in gis if i < gi} for pid, gis in APPS[(season, team)]}
    for r in x.itertuples():
        f = {f'vt_{p}': 0.0 for p in POS}; f['vc_RB'] = 0.0
        for pid, ts, cs, pos, gis in absent:
            if pos != r.position:
                continue
            w = len(mine[r.player_id] & gis) / max(1, len(mine[r.player_id]))
            f[f'vt_{pos}'] += w * ts * (r.avg_target_share or 0) / max(S_t.get(pos, 0), 0.05)
            if pos == 'RB':
                f['vc_RB'] += w * cs * (r.avg_carry_share or 0) / max(S_c.get('RB', 0), 0.05)
        if any(f.values()):
            rows.append({'season': season, 'row': r.Index, **f})
V = pd.DataFrame(rows)
V = pd.concat([V.drop(columns='season').reset_index(drop=True), d.loc[V.row].reset_index(drop=True)], axis=1)
print('player-games with a same-position regular out', len(V), V.position.value_counts().to_dict())
TR, TE = V.season <= 2022, V.season >= 2023
out = {'k': {}, 'check': {}}

# ---------------- shares: gain = k * f
for pos in POS:
    z = V[(V.position == pos) & (V[f'vt_{pos}'] > 0) & V.ts.notna() & V.avg_target_share.notna()]
    tr = z[z.season <= 2022]
    k = float(((tr.ts - tr.avg_target_share) * tr[f'vt_{pos}']).sum() / (tr[f'vt_{pos}'] ** 2).sum())
    te = z[z.season >= 2023]
    out['k'][f'tgt_{pos}'] = round(k, 3)
    out['check'][f'target share, {pos} out'] = {'n': len(te), 'mae_plain': round(float((te.ts - te.avg_target_share).abs().mean()), 4),
                                                'mae_bump': round(float((te.ts - te.avg_target_share - k * te[f'vt_{pos}']).abs().mean()), 4),
                                                'bias_plain': round(float((te.ts - te.avg_target_share).mean()), 4)}
z = V[(V.position == 'RB') & (V.vc_RB > 0) & V.cs.notna() & V.avg_carry_share.notna()]
tr = z[z.season <= 2022]; te = z[z.season >= 2023]
k = float(((tr.cs - tr.avg_carry_share) * tr.vc_RB).sum() / (tr.vc_RB ** 2).sum())
out['k']['car_RB'] = round(k, 3)
out['check']['carry share, RB out'] = {'n': len(te), 'mae_plain': round(float((te.cs - te.avg_carry_share).abs().mean()), 4),
                                       'mae_bump': round(float((te.cs - te.avg_carry_share - k * te.vc_RB).abs().mean()), 4),
                                       'bias_plain': round(float((te.cs - te.avg_carry_share).mean()), 4)}
print(json.dumps(out, indent=1))

# ---------------- the projections
K = out['k']
gain_t = sum(K[f'tgt_{p}'] * V[f'vt_{p}'] for p in POS); gain_c = K['car_RB'] * V.vc_RB
V['m_t'] = 1 + gain_t / V.avg_target_share.clip(lower=0.02); V['m_c'] = 1 + gain_c / V.avg_carry_share.clip(lower=0.03)


def proj(df, key):
    m = MODELS[key]; return df[m['feats']].astype(float).values @ np.array(m['beta'][:-1]) + m['beta'][-1]


out['g'] = {}
for stat, key, mcol, act, vol in (('rec_yds', 'rec_yds', 'm_t', 'receiving_yards', 'targets'), ('receptions', 'receptions', 'm_t', 'receptions', 'targets'),
                                  ('rush_yds', 'rush_yds', 'm_c', 'rushing_yards', 'carries')):
    s = V.copy(); s['p0'] = proj(s, key)
    s = s[s.p0.notna() & (s.p0 > 1) & (s[mcol] > 1.001)]
    if stat == 'rush_yds':
        s = s[s.position == 'RB']
    tr, te = s[s.season <= 2022], s[s.season >= 2023]
    g = float(((tr[act] - tr.p0) * tr.p0 * (tr[mcol] - 1)).sum() / ((tr.p0 * (tr[mcol] - 1)) ** 2).sum())
    p1 = te.p0 * (1 + g * (te[mcol] - 1))
    out['g'][stat] = round(g, 3)
    out['check'][stat] = {'n': len(te), 'mae_plain': round(float((te[act] - te.p0).abs().mean()), 3), 'mae_bump': round(float((te[act] - p1).abs().mean()), 3),
                          'bias_plain': round(float((te[act] - te.p0).mean()), 3), 'bias_bump': round(float((te[act] - p1).mean()), 3),
                          'avg_bump': round(float((p1 - te.p0).mean()), 2), 'avg_proj': round(float(te.p0.mean()), 1),
                          f'{vol}_before': round(float(te['pg_' + vol].mean()), 2), f'{vol}_actual': round(float(te[vol].mean()), 2)}
print(json.dumps({k: out[k] for k in ('g', 'check')}, indent=1))
json.dump(out, open('work/injury_bump.json', 'w'), indent=1)

# ---------------- touchdowns: scale the scoring rate (-ln(1 - p)) the same way, with the volume the player gains
s = V.copy(); s['p0'] = np.clip(proj(s, 'any_td'), 0.02, 0.85)
s['m'] = np.where(s.position == 'RB', 0.5 * (s.m_c + s.m_t), s.m_t)
s = s[s.m > 1.001]; tr, te = s[s.season <= 2022], s[s.season >= 2023]
lam = lambda p: -np.log(1 - p)
def brier(z, g): p = 1 - np.exp(-lam(z.p0) * (1 + g * (z.m - 1))); return float(((z.any_td.clip(0, 1) - p) ** 2).mean())
g_td = min(np.linspace(0, 1.5, 31), key=lambda g: brier(tr, g))
out['g']['any_td'] = round(float(g_td), 2)
out['check']['any_td'] = {'n': len(te), 'brier_plain': round(brier(te, 0), 4), 'brier_bump': round(brier(te, g_td), 4),
                          'rate_actual': round(float(te.any_td.clip(0, 1).mean()), 3), 'p_plain': round(float(te.p0.mean()), 3),
                          'p_bump': round(float((1 - np.exp(-lam(te.p0) * (1 + g_td * (te.m - 1)))).mean()), 3)}
print('any_td', out['g']['any_td'], out['check']['any_td'])
json.dump(out, open('work/injury_bump.json', 'w'), indent=1)
