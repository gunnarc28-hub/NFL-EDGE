"""With/without splits: a teammate's target and carry share in games a regular missed vs games he played, same season."""
import pandas as pd, numpy as np
d = pd.read_pickle('work/player_hist_features.pkl'); d = d[(d.season_type == 'REG') & d.position.isin(['WR', 'TE', 'RB'])].copy()
d['ts'] = d.targets / d.team_tgt.replace(0, np.nan); d['cs'] = d.carries / d.team_car.replace(0, np.nan)
games = d.groupby(['season', 'team']).game_id.apply(set).to_dict()
res = []
for (season, team), x in d.groupby(['season', 'team']):
    gp = x.groupby('player_id').game_id.apply(set).to_dict()
    allg = games[(season, team)]
    sh = x.groupby('player_id')[['ts', 'cs']].mean()
    pos = x.groupby('player_id').position.first()
    # regulars: played 4+ games with a real role
    regs = [p for p in gp if len(gp[p]) >= 4 and (sh.loc[p, 'ts'] >= 0.12 or (pos[p] == 'RB' and sh.loc[p, 'cs'] >= 0.25))]
    for a in regs:
        missed = allg - gp[a]
        # count only games between his first and last appearance, or after: anything he missed while on the team
        if len(missed) < 1:
            continue
        for p in gp:
            if p == a or len(gp[p]) < 4:
                continue
            w_ = gp[p] & gp[a]; wo = gp[p] & missed
            if len(w_) < 3 or len(wo) < 1:
                continue
            xp = x[x.player_id == p].set_index('game_id')
            res.append({'season': season, 'team': team, 'abs_pos': pos[a], 'pos': pos[p], 'abs_ts': sh.loc[a, 'ts'], 'abs_cs': sh.loc[a, 'cs'],
                        'ts_with': xp.loc[list(w_), 'ts'].mean(), 'ts_wo': xp.loc[list(wo), 'ts'].mean(), 'cs_with': xp.loc[list(w_), 'cs'].mean(), 'cs_wo': xp.loc[list(wo), 'cs'].mean(),
                        'n_wo': len(wo), 'tgt_with': xp.loc[list(w_), 'targets'].mean(), 'tgt_wo': xp.loc[list(wo), 'targets'].mean(),
                        'car_with': xp.loc[list(w_), 'carries'].mean(), 'car_wo': xp.loc[list(wo), 'carries'].mean()})
R = pd.DataFrame(res)
print('pairs', len(R))
for ap in ('WR', 'TE', 'RB'):
    for pp in ('WR', 'TE', 'RB'):
        z = R[(R.abs_pos == ap) & (R.pos == pp) & (R.ts_with >= 0.05)]
        if len(z) < 30: continue
        w = z.n_wo
        print(f'{ap} out -> {pp}: pairs {len(z)}, target share {np.average(z.ts_with, weights=w):.3f} -> {np.average(z.ts_wo, weights=w):.3f}, '
              f'targets {np.average(z.tgt_with, weights=w):.2f} -> {np.average(z.tgt_wo, weights=w):.2f}')
z = R[(R.abs_pos == 'RB') & (R.pos == 'RB') & (R.cs_with >= 0.1)]; w = z.n_wo
print(f'RB out -> RB carries: pairs {len(z)}, carry share {np.average(z.cs_with, weights=w):.3f} -> {np.average(z.cs_wo, weights=w):.3f}, carries {np.average(z.car_with, weights=w):.2f} -> {np.average(z.car_wo, weights=w):.2f}')
# how much of the vacated share each teammate picked up, relative to his own share (proportional = 1)
z = R[(R.ts_with >= 0.05)].copy(); z['gain'] = z.ts_wo - z.ts_with; z['prop'] = z.ts_with * z.abs_ts / (1 - z.abs_ts)
for ap in ('WR', 'TE', 'RB'):
    for same in (True, False):
        q = z[(z.abs_pos == ap) & ((z.pos == ap) == same)]
        k = (q.gain * q.prop * q.n_wo).sum() / (q.prop ** 2 * q.n_wo).sum()
        print(f'{ap} out, {"same" if same else "other"} position: k = {k:.2f} (pairs {len(q)})')
R.to_pickle('work/with_without.pkl')
