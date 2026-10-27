"""NHL: when a regular skater sits, who gets his ice time? Same method as nba_10_injury_bump.py.

A skater is missing when he averaged 14+ minutes (weighted toward recent games) in the team's last 10 games and didn't
play; what is still new decays with each game he has been out (half-life 5 games, the ice-time average's own).
Ice-time gain = c[bucket, same/other position] * new missing minutes, buckets by projected ice time. Shots, points and
blocks then scale with the ice time. Fit on 2015-16 to 2022-23, checked on 2023-24 to 2025-26. -> work/nhl_injury_bump.json"""
import json, numpy as np, pandas as pd
WORK = 'work'
d = pd.read_pickle(f'{WORK}/nhl_proj.pkl').sort_values(['t', 'game_id'])
d['yr'] = d.season.astype(str).str[-4:].astype(int)
aM = 0.5 ** (1 / 5)
rows = []
for team, x in d.groupby('team_abbrev'):
    st = {}
    for i, (gid, g) in enumerate(x.groupby('game_id', sort=False)):
        played = set(g.player_id)
        m = {'vm_F': 0.0, 'vm_D': 0.0}
        for pid, s in st.items():
            j = i - s['last'] - 1
            if j > 9 or s['toi'] < 14 or pid in played:
                continue
            m['vm_' + s['pos']] += s['toi'] * 0.5 ** (j / 5)
        rows.append({'game_id': gid, 'team_abbrev': team, **m})
        for r in g.itertuples():
            s = st.get(r.player_id)
            if s is None:
                st[r.player_id] = {'toi': r.toi_m, 'last': i, 'pos': r.pos1, 'n': 1}
            else:
                w = min(aM, 1 - 1 / (s['n'] + 1)); s['toi'] = w * s['toi'] + (1 - w) * r.toi_m; s['last'] = i; s['n'] += 1
MS = pd.DataFrame(rows)
d = d.merge(MS, on=['game_id', 'team_abbrev'], how='left')
d = d[d.toi_p.notna() & (d.n_prev >= 5)].copy()
d['vm_same'] = np.where(d.pos1 == 'D', d.vm_D, d.vm_F); d['vm_other'] = np.where(d.pos1 == 'D', d.vm_F, d.vm_D)
BK = [0, 12, 16, 20, 99]
d['bk'] = np.digitize(d.toi_p, BK[1:-1])
def X(z):
    cols = []
    for b in range(4):
        cols += [z.vm_same * (z.bk == b), z.vm_other * (z.bk == b)]
    return np.column_stack(cols).astype(float)
TR = (d.yr >= 2016) & (d.yr <= 2023); TE = d.yr >= 2024; hit = (d.vm_F + d.vm_D) > 1
tr = d[TR & hit]
c = np.linalg.lstsq(X(tr), tr.toi_m - tr.toi_p, rcond=None)[0]
out = {'fit': {'buckets': BK, 'same': [round(float(c[2 * b]), 3) for b in range(4)], 'other': [round(float(c[2 * b + 1]), 3) for b in range(4)]}, 'check': {}}
d['toi_new'] = np.clip(d.toi_p + X(d) @ c, 0, 30)
for nm, sub in (('all', TE & hit), ('fresh_same_position_regular_out', TE & (d.vm_same >= 14))):
    z = d[sub]; o = {'n': len(z)}
    for stat, act, pj in (('toi', 'toi_m', 'toi_p'), ('sog', 'shots_on_goal', 'sog_p'), ('points', 'points', 'p_p'), ('blocks', 'blocked_shots', 'blk_p')):
        p0 = z[pj]; p1 = z.toi_new if stat == 'toi' else z[pj] * z.toi_new / z.toi_p.clip(lower=1)
        o[stat] = {'mae_plain': round(float((z[act] - p0).abs().mean()), 3), 'mae_new': round(float((z[act] - p1).abs().mean()), 3),
                   'bias_plain': round(float((z[act] - p0).mean()), 3), 'bias_new': round(float((z[act] - p1).mean()), 3)}
    out['check'][nm] = o
print(json.dumps(out, indent=1))
json.dump(out, open(f'{WORK}/nhl_injury_bump.json', 'w'), indent=1)
