"""NBA quarters and halves: what each part of the game looks like given the full-game spread and total.

For every game 2020-21 to 2025-26 with a closing line (work/nba_games.pkl) and quarter scores (nba_11_pbp.py):
  segment margin = a + b * (expected full-game margin),  segment total = c + d * (full-game total),
fit on 2020-21 to 2023-24 and checked on 2024-25 and 2025-26. The spread around those expectations is measured too, as a
function of the segment's expected total (faster games swing more), and the chance a quarter ends tied (a push on a
quarter moneyline at most books) is checked against a rounded normal. The second half includes overtime; the 4th
quarter does not. -> work/nba_segments.json (copied to pipeline/static/)."""
import json, math, numpy as np, pandas as pd
WORK = '/home/claude/sports/work'
G = pd.read_pickle(f'{WORK}/nba_games.pkl')[['gid', 'season', 'home', 'away', 'hs', 'as_', 'line', 'total']]
Q = pd.read_pickle(f'{WORK}/nba_qscores.pkl')
G['gid'] = pd.to_numeric(G.gid, errors='coerce'); Q['game_id'] = pd.to_numeric(Q.game_id, errors='coerce')
d = G.merge(Q.drop(columns=['season']), left_on='gid', right_on='game_id').dropna(subset=['line', 'total', 'q4h'])
d = d[(d.q1h + d.q2h + d.q3h + d.q4h + d.ot_h == d.hs) & (d.q1a + d.q2a + d.q3a + d.q4a + d.ot_a == d.as_)]      # the play-by-play adds up
d['mu'] = -d.line; d['T'] = d.total
SEG = {'q1': (['q1'], False), 'q2': (['q2'], False), 'q3': (['q3'], False), 'q4': (['q4'], False), 'h1': (['q1', 'q2'], False), 'h2': (['q3', 'q4'], True)}
for s, (qs, ot) in SEG.items():
    d[f'{s}_h'] = sum(d[f'{q}h'] for q in qs) + (d.ot_h if ot else 0); d[f'{s}_a'] = sum(d[f'{q}a'] for q in qs) + (d.ot_a if ot else 0)
    d[f'{s}_m'] = d[f'{s}_h'] - d[f'{s}_a']; d[f'{s}_t'] = d[f'{s}_h'] + d[f'{s}_a']
TR, TE = d.season <= 2024, d.season >= 2025
print('games', len(d), 'train', int(TR.sum()), 'test', int(TE.sum()))
ncdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
out = {'fit_seasons': [2021, 2024], 'check_seasons': [2025, 2026], 'segments': {}}
for s in SEG:
    tr, te = d[TR], d[TE]
    b, a = np.polyfit(tr.mu, tr[f'{s}_m'], 1); dd, c = np.polyfit(tr['T'], tr[f'{s}_t'], 1)
    em = lambda z: a + b * z.mu; et = lambda z: c + dd * z['T']
    # spread around the expectation grows with the segment's pace: sd = k * sqrt(expected segment total)
    rm, rt = tr[f'{s}_m'] - em(tr), tr[f'{s}_t'] - et(tr)
    km = float(np.sqrt((rm ** 2 / et(tr)).mean())); kt = float(np.sqrt((rt ** 2 / et(tr)).mean()))
    sm = lambda z: km * np.sqrt(et(z)); st = lambda z: kt * np.sqrt(et(z))
    # checks on later seasons: errors, ties, and how often each side of a line at the model's own number wins
    zm, zt = (te[f'{s}_m'] - em(te)) / sm(te), (te[f'{s}_t'] - et(te)) / st(te)
    p_tie = np.array([ncdf((0.5 - m) / v) - ncdf((-0.5 - m) / v) for m, v in zip(em(te), sm(te))])
    # calibration of P(home covers L) at lines around the fair number, every half point from -3 to +3
    rows = []
    for off in np.arange(-3, 3.5, 0.5):
        L = np.round(em(te) * 2) / 2 + off + 0.5 * ((np.round(em(te) * 2) % 2 == 0))      # a half-point line near the fair margin
        p = np.array([1 - ncdf((l - m) / v) for l, m, v in zip(L, em(te), sm(te))])
        rows.append(pd.DataFrame({'p': p, 'hit': (te[f'{s}_m'].values > L).astype(float)}))
    cal = pd.concat(rows); cal['bin'] = pd.cut(cal.p, [0, .3, .4, .45, .5, .55, .6, .7, 1])
    calm = cal.groupby('bin', observed=True).agg(n=('p', 'size'), p=('p', 'mean'), hit=('hit', 'mean')).round(3)
    rows = []
    for off in np.arange(-6, 6.5, 1.0):
        L = np.round(et(te)) + 0.5 + off
        p = np.array([1 - ncdf((l - m) / v) for l, m, v in zip(L, et(te), st(te))])
        rows.append(pd.DataFrame({'p': p, 'hit': (te[f'{s}_t'].values > L).astype(float)}))
    calt = pd.concat(rows); calt['bin'] = pd.cut(calt.p, [0, .3, .4, .45, .5, .55, .6, .7, 1])
    calt = calt.groupby('bin', observed=True).agg(n=('p', 'size'), p=('p', 'mean'), hit=('hit', 'mean')).round(3)
    out['segments'][s] = {'margin': [round(float(a), 3), round(float(b), 4)], 'total': [round(float(c), 3), round(float(dd), 4)],
                          'k_margin': round(km, 4), 'k_total': round(kt, 4), 'ot': SEG[s][1],
                          'check': {'n': int(len(te)), 'mae_margin': round(float((te[f'{s}_m'] - em(te)).abs().mean()), 2),
                                    'mae_total': round(float((te[f'{s}_t'] - et(te)).abs().mean()), 2),
                                    'z_sd_margin': round(float(zm.std()), 3), 'z_sd_total': round(float(zt.std()), 3),
                                    'kurtosis_margin': round(float(zm.kurt()), 2), 'kurtosis_total': round(float(zt.kurt()), 2),
                                    'ties': round(float((te[f'{s}_m'] == 0).mean()), 4), 'ties_model': round(float(p_tie.mean()), 4),
                                    'home_win': round(float((te[f'{s}_m'] > 0).mean()), 4),
                                    'spread_calibration': [[str(i), int(r.n), float(r.p), float(r.hit)] for i, r in calm.iterrows()],
                                    'total_calibration': [[str(i), int(r.n), float(r.p), float(r.hit)] for i, r in calt.iterrows()]}}
    print(s, json.dumps({k: v for k, v in out['segments'][s].items() if k != 'check'}), json.dumps({k: v for k, v in out['segments'][s]['check'].items() if 'calibration' not in k}))
    print('   spread cal', out['segments'][s]['check']['spread_calibration'])
    print('   total cal ', out['segments'][s]['check']['total_calibration'])
# the site's numbers: the same fits on the latest four seasons (quarter scoring has shifted a little lately)
out['site_fit_seasons'] = [2023, 2026]; out['site'] = {}
for s in SEG:
    z = d[d.season >= 2023]
    b, a = np.polyfit(z.mu, z[f'{s}_m'], 1); dd, c = np.polyfit(z['T'], z[f'{s}_t'], 1)
    et_ = c + dd * z['T']
    km = float(np.sqrt(((z[f'{s}_m'] - a - b * z.mu) ** 2 / et_).mean())); kt = float(np.sqrt(((z[f'{s}_t'] - et_) ** 2 / et_).mean()))
    out['site'][s] = {'margin': [round(float(a), 3), round(float(b), 4)], 'total': [round(float(c), 3), round(float(dd), 4)], 'k_margin': round(km, 4),
                      'k_total': round(kt, 4), 'ot': SEG[s][1]}
    print('site', s, out['site'][s])
json.dump(out, open(f'{WORK}/nba_segments.json', 'w'), indent=1)
