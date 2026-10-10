"""Which player stats predict next-game prop outcomes? Builds pre-game (season-to-date) player features for 2018-2025,
measures correlation with next-game results, fits small projection models and checks them out of sample (2024-25).
Writes work/player_research.json"""
import json, numpy as np, pandas as pd

COLS = ['player_id', 'player_display_name', 'position', 'season', 'week', 'season_type', 'game_id', 'team', 'opponent_team',
        'completions', 'attempts', 'passing_yards', 'passing_tds', 'passing_interceptions', 'sacks_suffered', 'passing_air_yards',
        'passing_epa', 'passing_cpoe', 'carries', 'rushing_yards', 'rushing_tds', 'rushing_epa', 'receptions', 'targets',
        'receiving_yards', 'receiving_tds', 'receiving_air_yards', 'receiving_yards_after_catch', 'receiving_epa',
        'target_share', 'air_yards_share', 'wopr', 'special_teams_tds']

def load_players(years):
    fr = []
    for y in years:
        p = pd.read_csv(f'raw/stats_player_week_{y}.csv', low_memory=False, usecols=COLS)
        fr.append(p[p.season_type == 'REG'])
    return pd.concat(fr, ignore_index=True)

def build_features(pw, sched, rz, ngs):
    """Season-to-date (pre-game) features for every player-game."""
    pw = pw.copy()
    pw = pw.merge(rz[['game_id', 'player_id', 'rz_carries', 'rz_targets']], on=['game_id', 'player_id'], how='left')
    pw[['rz_carries', 'rz_targets']] = pw[['rz_carries', 'rz_targets']].fillna(0)
    num = ['completions', 'attempts', 'passing_yards', 'passing_tds', 'passing_interceptions', 'sacks_suffered', 'passing_air_yards',
           'passing_epa', 'carries', 'rushing_yards', 'rushing_tds', 'rushing_epa', 'receptions', 'targets', 'receiving_yards',
           'receiving_tds', 'receiving_air_yards', 'receiving_yards_after_catch', 'receiving_epa', 'rz_carries', 'rz_targets']
    pw[num] = pw[num].fillna(0)
    pw['any_td'] = ((pw.rushing_tds + pw.receiving_tds) > 0).astype(int)
    pw['rush_rec_yds'] = pw.rushing_yards + pw.receiving_yards
    # team totals per game (for shares / team volume)
    team = pw.groupby(['game_id', 'team']).agg(team_att=('attempts', 'sum'), team_car=('carries', 'sum'),
                                               team_tgt=('targets', 'sum')).reset_index()
    pw = pw.merge(team, on=['game_id', 'team'], how='left')
    pw['carry_share'] = np.where(pw.team_car > 0, pw.carries / pw.team_car.replace(0, np.nan), np.nan)
    pw['tshare_calc'] = np.where(pw.team_tgt > 0, pw.targets / pw.team_tgt.replace(0, np.nan), np.nan)
    # NGS weekly
    if ngs is not None:
        pw = pw.merge(ngs, on=['player_id', 'season', 'week'], how='left')
    pw = pw.sort_values(['player_id', 'season', 'week']).reset_index(drop=True)
    key = [pw.player_id, pw.season]
    g = pw.groupby(['player_id', 'season'], sort=False)
    def pre_sum(col):
        x = pw[col].fillna(0)
        return x.groupby(key).cumsum() - x
    def pre_cnt(col):
        x = pw[col].notna().astype(float)
        return x.groupby(key).cumsum() - x
    def pre_mean(col):
        return pre_sum(col) / pre_cnt(col).replace(0, np.nan)
    def last_n(col, n):
        x = pw[col].fillna(0)
        cs = x.groupby(key).cumsum() - x                     # sum of all prior games
        cs_lag = cs.groupby(key).shift(n).fillna(0)          # sum of prior games before the last n
        cnt = (g.cumcount()).clip(upper=n)
        return (cs - cs_lag) / cnt.replace(0, np.nan)
    f = pd.DataFrame(index=pw.index)
    f['n_prior'] = g.cumcount()
    for c in ['targets', 'receptions', 'receiving_yards', 'receiving_air_yards', 'receiving_yards_after_catch', 'carries',
              'rushing_yards', 'attempts', 'passing_yards', 'completions', 'rz_carries', 'rz_targets', 'any_td', 'rush_rec_yds',
              'team_att', 'team_car']:
        f['pg_' + c] = pre_mean(c)
    for c in ['target_share', 'air_yards_share', 'wopr', 'carry_share']:
        f['avg_' + c] = pre_mean(c)
    f['l3_receiving_yards'] = last_n('receiving_yards', 3); f['l3_rushing_yards'] = last_n('rushing_yards', 3)
    f['l3_passing_yards'] = last_n('passing_yards', 3); f['l3_targets'] = last_n('targets', 3); f['l3_carries'] = last_n('carries', 3)
    f['ypt'] = pre_sum('receiving_yards') / pre_sum('targets').replace(0, np.nan)
    f['catch_rate'] = pre_sum('receptions') / pre_sum('targets').replace(0, np.nan)
    f['ypc'] = pre_sum('rushing_yards') / pre_sum('carries').replace(0, np.nan)
    f['rush_epa_c'] = pre_sum('rushing_epa') / pre_sum('carries').replace(0, np.nan)
    f['ypa'] = pre_sum('passing_yards') / pre_sum('attempts').replace(0, np.nan)
    f['epa_db'] = pre_sum('passing_epa') / (pre_sum('attempts') + pre_sum('sacks_suffered')).replace(0, np.nan)
    f['sack_rate'] = pre_sum('sacks_suffered') / (pre_sum('attempts') + pre_sum('sacks_suffered')).replace(0, np.nan)
    f['adot'] = pre_sum('passing_air_yards') / pre_sum('attempts').replace(0, np.nan)
    f['cpoe'] = pre_mean('passing_cpoe')
    f['rec_epa_t'] = pre_sum('receiving_epa') / pre_sum('targets').replace(0, np.nan)
    ngs_cols = [c for c in ['ngs_sep', 'ngs_yacoe', 'ngs_ryoe', 'ngs_ttt', 'ngs_cpoe', 'ngs_box8'] if c in pw.columns]
    for c in ngs_cols:
        f['pre_' + c] = pre_mean(c)
    # game environment: implied team total and spread from schedule
    s = sched[['game_id', 'home_team', 'away_team', 'spread_line', 'total_line']]
    pw = pw.merge(s, on='game_id', how='left')
    home = pw.team == pw.home_team
    f['implied_tt'] = np.where(home, (pw.total_line + pw.spread_line) / 2, (pw.total_line - pw.spread_line) / 2)
    f['team_spread'] = np.where(home, pw.spread_line, -pw.spread_line)
    f['is_home'] = home.astype(int)
    out = pd.concat([pw, f], axis=1)
    return out

def add_defense_vs_position(df):
    """Opponent's season-to-date yards allowed per game to this position group (pre-game), vs league average."""
    df = df.copy()
    allowed = df.groupby(['season', 'week', 'opponent_team', 'position']).agg(
        rec_allowed=('receiving_yards', 'sum'), rush_allowed=('rushing_yards', 'sum'), pass_allowed=('passing_yards', 'sum')).reset_index()
    allowed = allowed.sort_values(['opponent_team', 'position', 'season', 'week'])
    k2 = [allowed.opponent_team, allowed.position, allowed.season]
    for c in ['rec_allowed', 'rush_allowed', 'pass_allowed']:
        x = allowed[c]
        cs = x.groupby(k2).cumsum() - x
        cnt = x.groupby(k2).cumcount()
        allowed['pre_' + c] = cs / cnt.replace(0, np.nan)
        lg = allowed.groupby(['season', 'position'])[c].transform('mean')
        allowed['rel_' + c] = allowed['pre_' + c] / lg
    df = df.merge(allowed[['season', 'week', 'opponent_team', 'position', 'rel_rec_allowed', 'rel_rush_allowed', 'rel_pass_allowed']],
                  on=['season', 'week', 'opponent_team', 'position'], how='left')
    return df

def load_ngs():
    fr = []
    a = pd.read_csv('raw/ngs_receiving.csv.gz', low_memory=False)
    a = a[a.week > 0][['player_gsis_id', 'season', 'week', 'avg_separation', 'avg_yac_above_expectation']].rename(
        columns={'player_gsis_id': 'player_id', 'avg_separation': 'ngs_sep', 'avg_yac_above_expectation': 'ngs_yacoe'})
    b = pd.read_csv('raw/ngs_rushing.csv.gz', low_memory=False)
    b = b[b.week > 0][['player_gsis_id', 'season', 'week', 'rush_yards_over_expected_per_att', 'percent_attempts_gte_eight_defenders']].rename(
        columns={'player_gsis_id': 'player_id', 'rush_yards_over_expected_per_att': 'ngs_ryoe', 'percent_attempts_gte_eight_defenders': 'ngs_box8'})
    c = pd.read_csv('raw/ngs_passing.csv.gz', low_memory=False)
    c = c[c.week > 0][['player_gsis_id', 'season', 'week', 'avg_time_to_throw', 'completion_percentage_above_expectation']].rename(
        columns={'player_gsis_id': 'player_id', 'avg_time_to_throw': 'ngs_ttt', 'completion_percentage_above_expectation': 'ngs_cpoe'})
    n = a.merge(b, on=['player_id', 'season', 'week'], how='outer').merge(c, on=['player_id', 'season', 'week'], how='outer')
    return n.groupby(['player_id', 'season', 'week']).mean(numeric_only=True).reset_index()

PROPS = {
    'rec_yds': {'pos': ['WR', 'TE'], 'y': 'receiving_yards', 'min': ('pg_targets', 3),
                'X': ['pg_receiving_yards', 'l3_receiving_yards', 'pg_targets', 'avg_target_share', 'avg_air_yards_share', 'avg_wopr',
                      'pg_receiving_air_yards', 'pg_receptions', 'ypt', 'catch_rate', 'rec_epa_t', 'pg_rz_targets', 'pg_team_att',
                      'implied_tt', 'team_spread', 'rel_rec_allowed', 'pre_ngs_sep', 'pre_ngs_yacoe', 'is_home']},
    'receptions': {'pos': ['WR', 'TE', 'RB'], 'y': 'receptions', 'min': ('pg_targets', 2.5),
                   'X': ['pg_receptions', 'pg_targets', 'avg_target_share', 'catch_rate', 'avg_wopr', 'pg_team_att', 'implied_tt',
                         'team_spread', 'rel_rec_allowed', 'l3_targets']},
    'rush_yds': {'pos': ['RB'], 'y': 'rushing_yards', 'min': ('pg_carries', 6),
                 'X': ['pg_rushing_yards', 'l3_rushing_yards', 'pg_carries', 'l3_carries', 'avg_carry_share', 'ypc', 'rush_epa_c',
                       'pg_rz_carries', 'pg_team_car', 'implied_tt', 'team_spread', 'rel_rush_allowed', 'pre_ngs_ryoe', 'pre_ngs_box8', 'is_home']},
    'pass_yds': {'pos': ['QB'], 'y': 'passing_yards', 'min': ('pg_attempts', 18),
                 'X': ['pg_passing_yards', 'l3_passing_yards', 'pg_attempts', 'ypa', 'epa_db', 'cpoe', 'sack_rate', 'adot',
                       'implied_tt', 'team_spread', 'rel_pass_allowed', 'pre_ngs_ttt', 'pre_ngs_cpoe', 'is_home']},
    'any_td': {'pos': ['RB', 'WR', 'TE'], 'y': 'any_td', 'min': ('pg_rush_rec_yds', 20),
               'X': ['pg_any_td', 'pg_rz_carries', 'pg_rz_targets', 'pg_carries', 'pg_targets', 'pg_rush_rec_yds', 'implied_tt',
                     'team_spread', 'avg_target_share', 'avg_carry_share']},
}
LABELS = {
    'pg_receiving_yards': 'Receiving yards per game', 'l3_receiving_yards': 'Receiving yards, last 3 games', 'pg_targets': 'Targets per game',
    'avg_target_share': 'Target share', 'avg_air_yards_share': 'Air-yards share', 'avg_wopr': 'WOPR (target + air-yards share)',
    'pg_receiving_air_yards': 'Air yards per game', 'pg_receptions': 'Receptions per game', 'ypt': 'Yards per target',
    'catch_rate': 'Catch rate', 'rec_epa_t': 'Receiving EPA per target', 'pg_rz_targets': 'Targets inside the 10',
    'pg_team_att': "Team pass attempts per game", 'implied_tt': 'Vegas implied team total', 'team_spread': 'Team favored by (spread)',
    'rel_rec_allowed': 'Opponent yards allowed to position', 'pre_ngs_sep': 'NGS separation', 'pre_ngs_yacoe': 'NGS YAC over expected',
    'is_home': 'Home game', 'l3_targets': 'Targets, last 3 games', 'pg_rushing_yards': 'Rushing yards per game',
    'l3_rushing_yards': 'Rushing yards, last 3 games', 'pg_carries': 'Carries per game', 'l3_carries': 'Carries, last 3 games',
    'avg_carry_share': 'Carry share', 'ypc': 'Yards per carry', 'rush_epa_c': 'Rush EPA per carry', 'pg_rz_carries': 'Carries inside the 10',
    'pg_team_car': 'Team carries per game', 'rel_rush_allowed': 'Opponent rush yards allowed to RBs', 'pre_ngs_ryoe': 'NGS rush yards over expected',
    'pre_ngs_box8': 'NGS stacked-box rate', 'pg_passing_yards': 'Passing yards per game', 'l3_passing_yards': 'Passing yards, last 3 games',
    'pg_attempts': 'Pass attempts per game', 'ypa': 'Yards per attempt', 'epa_db': 'EPA per dropback', 'cpoe': 'Completion % over expected',
    'sack_rate': 'Sack rate', 'adot': 'Average depth of target', 'rel_pass_allowed': 'Opponent pass yards allowed',
    'pre_ngs_ttt': 'NGS time to throw', 'pre_ngs_cpoe': 'NGS completion % over expected', 'pg_any_td': 'TDs per game',
    'pg_rush_rec_yds': 'Scrimmage yards per game'}

if __name__ == '__main__':
    sched = pd.read_csv('raw/games.csv', low_memory=False)
    rz = pd.read_pickle('work/player_rz.pkl')
    ngs = load_ngs()
    pw = load_players(range(2018, 2026))
    df = build_features(pw, sched, rz, ngs)
    df = add_defense_vs_position(df)
    df.to_pickle('work/player_hist_features.pkl')
    res, models = {}, {}
    for key, spec in PROPS.items():
        d = df[df.position.isin(spec['pos']) & (df.n_prior >= 3)]
        d = d[d[spec['min'][0]] >= spec['min'][1]]
        y = d[spec['y']]
        rows = []
        for x in spec['X']:
            ok = d[x].notna() & y.notna()
            if ok.sum() < 200:
                continue
            r = float(np.corrcoef(d.loc[ok, x], y[ok])[0, 1])
            rows.append({'key': x, 'label': LABELS.get(x, x), 'r': round(r, 3), 'n': int(ok.sum())})
        rows.sort(key=lambda r: -abs(r['r']))
        # projection model: OLS on the strongest, non-NGS features (NGS has gaps), train 2018-23, test 2024-25
        feats = [r['key'] for r in rows if not r['key'].startswith('pre_ngs')][:6]
        tr = d[(d.season <= 2023)].dropna(subset=feats + [spec['y']])
        te = d[(d.season >= 2024)].dropna(subset=feats + [spec['y']])
        X = np.c_[tr[feats].values, np.ones(len(tr))]
        b = np.linalg.lstsq(X, tr[spec['y']].values, rcond=None)[0]
        pred = np.c_[te[feats].values, np.ones(len(te))] @ b
        base_col = {'rec_yds': 'pg_receiving_yards', 'receptions': 'pg_receptions', 'rush_yds': 'pg_rushing_yards',
                    'pass_yds': 'pg_passing_yards', 'any_td': 'pg_any_td'}[key]
        mae_model = float(np.abs(pred - te[spec['y']]).mean()); mae_base = float(np.abs(te[base_col] - te[spec['y']]).mean())
        r_model = float(np.corrcoef(pred, te[spec['y']])[0, 1]); r_base = float(np.corrcoef(te[base_col], te[spec['y']])[0, 1])
        resid_sd = float(np.std(pred - te[spec['y']]))
        res[key] = {'predictors': rows, 'model_feats': feats, 'mae_model': round(mae_model, 2), 'mae_season_avg': round(mae_base, 2),
                    'r_model': round(r_model, 3), 'r_season_avg': round(r_base, 3), 'n_test': int(len(te)), 'resid_sd': round(resid_sd, 2)}
        models[key] = {'feats': feats, 'beta': b.tolist(), 'resid_sd': resid_sd}
        print(f'\n== {key} (n={len(d)}) model r={r_model:.3f} vs season-avg r={r_base:.3f}; MAE {mae_model:.1f} vs {mae_base:.1f}')
        for r in rows:
            print(f"   {r['label']:40s} r={r['r']:+.3f}")
        print('   model feats:', feats, np.round(b, 3))
    json.dump({'props': res, 'models': models, 'labels': LABELS}, open('work/player_research.json', 'w'), indent=1)
