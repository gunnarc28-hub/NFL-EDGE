"""NBA player projections rebuilt game by game (walk-forward) the way pipeline/nba.py makes them, plus variants to test.
Box scores: sportsdataverse 2022-23 to now. Writes work/nba_feat.pkl."""
import pandas as pd, numpy as np, json, os
RAW = '/home/claude/research_work/raw'; WORK = '/home/claude/research_work/work'; os.makedirs(WORK, exist_ok=True)
FIX = {'GSW': 'GS', 'NOP': 'NO', 'NYK': 'NY', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH', 'PHO': 'PHX', 'BRK': 'BKN'}
STATS = ['pts', 'reb', 'ast', 'fg3m', 'stl', 'blk', 'tov']
P = pd.concat([pd.read_csv(f'{RAW}/nba_player_box_{y}.csv', low_memory=False) for y in range(2023, 2028)], ignore_index=True)
P = P[P.season_type.isin([2, 3])].drop_duplicates(['game_id', 'athlete_id'])
P['game_id'] = P.game_id.astype(str); P['athlete_id'] = P.athlete_id.astype(str).str.replace(r'\.0$', '', regex=True)
for c in ('team_abbreviation', 'opponent_team_abbreviation'):
    P[c] = P[c].map(lambda a: FIX.get(a, a))
P['t'] = pd.to_datetime(P.game_date_time, utc=True, format='ISO8601')
P['min'] = pd.to_numeric(P.minutes, errors='coerce').fillna(0)
P['played'] = (P['min'] > 0) & (~P.did_not_play.astype(str).str.lower().isin(['true', '1']))
for a, b in zip(STATS, ['points', 'rebounds', 'assists', 'three_point_field_goals_made', 'steals', 'blocks', 'turnovers']):
    P[a] = pd.to_numeric(P[b], errors='coerce').fillna(0)
for c in ('field_goals_attempted', 'three_point_field_goals_attempted', 'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds'):
    P[c] = pd.to_numeric(P[c], errors='coerce').fillna(0)
P['starter_f'] = P.starter.astype(str).str.lower().isin(['true', '1']).astype(float)
P['pos1'] = P.athlete_position_abbreviation.fillna('F').astype(str).str[0].replace({'P': 'G', 'S': 'G'})
P = P.sort_values(['t', 'game_id']).reset_index(drop=True)
pl = P[P.played].copy().reset_index(drop=True)
g = pl.groupby('athlete_id', sort=False)
pl['n_prev'] = g.cumcount()
ew = lambda col, hl: g[col].transform(lambda s: s.ewm(halflife=hl, min_periods=1).mean().shift())
pl['min_ew'] = ew('min', 5); pl['min_l10'] = g['min'].transform(lambda s: s.rolling(10, min_periods=1).mean().shift())
pl['min_last'] = g['min'].shift()
pl['started'] = g['starter_f'].transform(lambda s: s.ewm(halflife=3, min_periods=1).mean().shift())
pl['started_last'] = g['starter_f'].shift()
pl['prev_t'] = g['t'].shift()
pl['prev_season'] = g['season'].shift()
pl['day_et'] = pl.t.dt.tz_convert('America/New_York').dt.tz_localize(None).dt.normalize()
pl['rest'] = (pl.day_et - g['day_et'].shift()).dt.days
pl['b2b'] = (pl.rest <= 1).astype(float)
# games this season before this one (for season-aware weighting)
pl['n_season'] = pl.groupby(['athlete_id', 'season']).cumcount()
for hl in (6, 10, 18):
    pl[f'minr_{hl}'] = ew('min', hl)
    for k in STATS:
        pl[f'{k}_ew{hl}'] = ew(k, hl)
# this season only: per-minute rates so far (cumulative)
gs = pl.groupby(['athlete_id', 'season'], sort=False)
pl['min_cs'] = gs['min'].transform(lambda s: s.cumsum().shift())
for k in STATS:
    pl[f'{k}_cs'] = gs[k].transform(lambda s: s.cumsum().shift())
# league per-minute rate by position: the last 400 days before each game (approximated per season and position, prior season)
lg = pl.groupby(['season', 'pos1'])[STATS + ['min']].sum()
for k in STATS:
    lg[k + '_r'] = lg[k] / lg['min']
pl = pl.join(lg[[k + '_r' for k in STATS]].rename(columns={k + '_r': k + '_lgpos' for k in STATS}), on=['season', 'pos1'])
# opponent allowed per 48 (ewm hl 15 games), league ewm (hl 400), pace by team possessions (ewm hl 15)
tg = pl.groupby(['game_id', 'team_abbreviation', 'opponent_team_abbreviation', 't'])[STATS + ['min', 'field_goals_attempted', 'offensive_rebounds', 'free_throws_attempted']].sum().reset_index().sort_values('t')
for k in STATS:
    tg[k + '_pm'] = tg[k] / tg['min'].clip(lower=200) * 240
og = tg.groupby('opponent_team_abbreviation', sort=False)
for k in STATS:
    tg[k + '_allow'] = og[k + '_pm'].transform(lambda s: s.ewm(halflife=15, min_periods=1).mean().shift())
    tg[k + '_lg'] = tg[k + '_pm'].ewm(halflife=400, min_periods=1).mean().shift()
tg['poss'] = tg.field_goals_attempted - tg.offensive_rebounds + tg.tov + 0.44 * tg.free_throws_attempted
tg['pace_ew'] = tg.groupby('team_abbreviation').poss.transform(lambda s: s.ewm(halflife=15, min_periods=1).mean().shift())
tg['pace_lg'] = tg.poss.ewm(halflife=400, min_periods=1).mean().shift()
opp = tg[['game_id', 'opponent_team_abbreviation'] + [k + '_allow' for k in STATS] + [k + '_lg' for k in STATS]]
pl = pl.merge(opp, on=['game_id', 'opponent_team_abbreviation'], how='left')
pc = tg[['game_id', 'team_abbreviation', 'pace_ew', 'pace_lg']]
pl = pl.merge(pc, on=['game_id', 'team_abbreviation'], how='left').merge(
    pc.rename(columns={'team_abbreviation': 'opponent_team_abbreviation', 'pace_ew': 'opp_pace'}).drop(columns='pace_lg'), on=['game_id', 'opponent_team_abbreviation'], how='left')
pl['pace_f'] = ((pl.pace_ew + pl.opp_pace) / 2 / pl.pace_lg).fillna(1)
# team: who else is out (rotation minutes missing vs the team's last game), a cheap version of the injury bump
keep = ['game_id', 'athlete_id', 'athlete_display_name', 'team_abbreviation', 'opponent_team_abbreviation', 'season', 't', 'day_et', 'pos1', 'min', 'starter_f'] + STATS + [
    c for c in pl.columns if c.startswith(('min_', 'minr_', 'started', 'n_', 'rest', 'b2b', 'prev_')) or any(c.startswith(k + '_') for k in STATS) or c in ('pace_f',)]
pl = pl[list(dict.fromkeys(keep))]
pl.to_pickle(f'{WORK}/nba_feat.pkl')
print('rows', len(pl), 'seasons', pl.groupby('season').size().to_dict(), 'last', pl.t.max())
