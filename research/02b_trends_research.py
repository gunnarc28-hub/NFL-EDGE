"""Do 2+ week trends carry over to the next game? Team streaks (SU, ATS, totals, stat surges) and player usage
trends, 2018-2025 regular seasons. Writes work/trend_research.json"""
import json, numpy as np, pandas as pd

m = pd.read_pickle('work/team_metrics.pkl').sort_values(['season', 'team', 'week']).reset_index(drop=True)
m = m[(m.season >= 2018) & (m.season <= 2025)].copy()
m['margin'] = m.pf - m.pa
m['exp_margin'] = np.where(m.home == 1, m.spread_line, -m.spread_line)
m['ats'] = m.margin - m.exp_margin              # >0 covered
m['over'] = (m.pf + m.pa) - m.total_line         # >0 over
m['win'] = np.sign(m.margin)
m['surge'] = m.n_epa_play - m.pre_n_epa_play     # game EPA vs pre-game rating

def streak(series_bool):
    """Length of current streak of True values ending at each row (computed within a group, shifted so it is pre-game)."""
    out, c = [], 0
    for v in series_bool:
        c = c + 1 if v else 0
        out.append(c)
    return out

grp = m.groupby(['season', 'team'])
feats = {
    'win_streak': lambda d: d.win > 0, 'loss_streak': lambda d: d.win < 0,
    'cover_streak': lambda d: d.ats > 0, 'nocover_streak': lambda d: d.ats < 0,
    'over_streak': lambda d: d.over > 0, 'under_streak': lambda d: d.over < 0,
    'surge_streak': lambda d: d.surge > 0.05, 'slump_streak': lambda d: d.surge < -0.05,
}
for name, fn in feats.items():
    m[name] = np.concatenate([np.r_[0, streak(fn(d).values)[:-1]] for _, d in grp])  # streak entering the game

def rate(mask, outcome):
    sub = outcome[mask]
    sub = sub[sub != 0]
    return (float((sub > 0).mean()) if len(sub) else None), int(len(sub))

base_cover, n_all = rate(np.ones(len(m), bool), m.ats)
base_over, _ = rate(np.ones(len(m), bool), m.over)
team_rows = []
def add(label, mask, outcome, kind, base):
    r, n = rate(mask, outcome)
    team_rows.append({'trend': label, 'next': kind, 'rate': round(r, 3) if r is not None else None, 'n': n, 'base': round(base, 3)})
for L in (2, 3):
    add(f'Won {L}+ straight', m.win_streak >= L, m.ats, 'covers next game', base_cover)
    add(f'Lost {L}+ straight', m.loss_streak >= L, m.ats, 'covers next game', base_cover)
    add(f'Covered {L}+ straight', m.cover_streak >= L, m.ats, 'covers next game', base_cover)
    add(f'Failed to cover {L}+ straight', m.nocover_streak >= L, m.ats, 'covers next game', base_cover)
    add(f'Games went over {L}+ straight', m.over_streak >= L, m.over, 'next game goes over', base_over)
    add(f'Games went under {L}+ straight', m.under_streak >= L, m.over, 'next game goes over', base_over)
    add(f'Offense+defense beat its rating {L}+ straight', m.surge_streak >= L, m.ats, 'covers next game', base_cover)
    add(f'Played below its rating {L}+ straight', m.slump_streak >= L, m.ats, 'covers next game', base_cover)
# does the surge itself continue (performance, not betting)?
cont_base = float((m.surge > 0).mean())
s2 = m.surge_streak >= 2
team_rows.append({'trend': 'Beat its rating 2+ straight', 'next': 'beats its (updated) rating again', 'rate': round(float((m.surge[s2] > 0).mean()), 3),
                  'n': int(s2.sum()), 'base': round(cont_base, 3)})
for r in team_rows:
    print(f"{r['trend']:45s} -> {r['next']:32s} {r['rate']}  (n={r['n']}, baseline {r['base']})")

# ---------------- player usage trends ----------------
frames = []
for y in range(2018, 2026):
    p = pd.read_csv(f'raw/stats_player_week_{y}.csv', low_memory=False,
                    usecols=['player_id', 'player_display_name', 'position', 'season', 'week', 'season_type', 'team',
                             'targets', 'receptions', 'receiving_yards', 'carries', 'rushing_yards', 'attempts', 'passing_yards',
                             'target_share', 'air_yards_share'])
    frames.append(p[p.season_type == 'REG'])
pw = pd.concat(frames).sort_values(['player_id', 'season', 'week']).reset_index(drop=True)
player_rows = []
def player_trend(pos, stat, label, min_avg):
    d = pw[pw.position.isin(pos)].copy()
    g = d.groupby(['player_id', 'season'])[stat]
    d['prior_avg'] = g.transform(lambda s: s.shift(1).expanding().mean())
    d['n_prior'] = g.cumcount()
    d['above'] = d[stat] > d['prior_avg']
    d['rise'] = d[stat] > g.shift(1)
    ab = d.groupby(['player_id', 'season'])['above']
    d['above_streak'] = np.concatenate([np.r_[0, streak(v.values)[:-1]] for _, v in ab])
    rs = d.groupby(['player_id', 'season'])['rise']
    d['rise_streak'] = np.concatenate([np.r_[0, streak(v.values)[:-1]] for _, v in rs])
    elig = (d.n_prior >= 3) & (d.prior_avg >= min_avg)
    base = float(d.loc[elig, 'above'].mean())
    for L in (2, 3):
        mk = elig & (d.above_streak >= L)
        player_rows.append({'trend': f'{label} above his average {L}+ straight', 'next': 'above his average again',
                            'rate': round(float(d.loc[mk, 'above'].mean()), 3), 'n': int(mk.sum()), 'base': round(base, 3)})
        mk2 = elig & (d.rise_streak >= L)
        player_rows.append({'trend': f'{label} rising {L}+ straight weeks', 'next': 'above his average again',
                            'rate': round(float(d.loc[mk2, 'above'].mean()), 3), 'n': int(mk2.sum()), 'base': round(base, 3)})
player_trend(['WR', 'TE'], 'targets', 'Targets', 3)
player_trend(['WR', 'TE'], 'receiving_yards', 'Receiving yards', 25)
player_trend(['RB'], 'carries', 'Carries', 6)
player_trend(['RB'], 'rushing_yards', 'Rushing yards', 25)
player_trend(['QB'], 'passing_yards', 'Passing yards', 150)
for r in player_rows:
    print(f"{r['trend']:45s} -> {r['next']:28s} {r['rate']}  (n={r['n']}, baseline {r['base']})")
json.dump({'team': team_rows, 'player': player_rows, 'base_cover': base_cover, 'base_over': base_over},
          open('work/trend_research.json', 'w'), indent=1)
