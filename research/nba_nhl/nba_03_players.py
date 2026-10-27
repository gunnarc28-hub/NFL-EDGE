"""Who's missing: value of the rotation players who sat each game, from box scores. Does it close the gap to the line?"""
import os, pandas as pd, numpy as np, json, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
RAW = 'raw'; WORK = 'work'
cols = ['game_id', 'season', 'season_type', 'game_date_time', 'athlete_id', 'athlete_display_name', 'team_abbreviation', 'minutes', 'field_goals_made', 'field_goals_attempted',
        'three_point_field_goals_made', 'three_point_field_goals_attempted', 'free_throws_made', 'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds', 'rebounds',
        'assists', 'steals', 'blocks', 'turnovers', 'fouls', 'plus_minus', 'points', 'starter', 'did_not_play', 'reason', 'athlete_position_abbreviation', 'home_away',
        'opponent_team_abbreviation', 'team_score', 'opponent_team_score']
P = pd.concat([pd.read_csv(f'{RAW}/nba/player_box_{y}.csv', low_memory=False, usecols=lambda c: c in cols) for y in range(2012, 2028)])
P = P[P.season_type.isin([2, 3])].drop_duplicates(['game_id', 'athlete_id'])
P['t'] = pd.to_datetime(P.game_date_time, utc=True, format='ISO8601')
P['min'] = P.minutes.fillna(0)
P['played'] = (P['min'] > 0) & (~P.did_not_play.fillna(False).astype(bool))
for c in ['field_goals_made', 'field_goals_attempted', 'free_throws_made', 'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds', 'steals', 'assists', 'blocks',
          'fouls', 'turnovers', 'points', 'rebounds', 'three_point_field_goals_made', 'plus_minus']:
    P[c] = P[c].fillna(0)
P['gmsc'] = (P.points + 0.4 * P.field_goals_made - 0.7 * P.field_goals_attempted - 0.4 * (P.free_throws_attempted - P.free_throws_made) + 0.7 * P.offensive_rebounds
             + 0.3 * P.defensive_rebounds + P.steals + 0.7 * P.assists + 0.7 * P.blocks - 0.4 * P.fouls - P.turnovers)
P.to_pickle(f'{WORK}/nba_player_box.pkl')
print('player rows', len(P))

H = 12; a = 0.5 ** (1 / H)
REPL = 0.18          # game score per minute of a replacement-level player (tuned below)
rows = []
for team, d in P.sort_values('t').groupby('team_abbreviation'):
    st = {}            # athlete -> [ew_minutes_when_played, ew_gmsc_per_min, last_team_game_index_played, n_games]
    games = d.groupby('game_id', sort=False)
    for i, (gid, x) in enumerate(games):
        played = set(x[x.played].athlete_id)
        # rotation players expected: played recently (within the last 10 team games) with real minutes
        miss_v = 0.0; miss_m = 0.0; avail_v = 0.0; n_miss = 0; top_missing = []
        for pid, s in st.items():
            if i - s[2] > 10 or s[0] < 12: continue
            v = (s[1] - REPL) * s[0]
            if pid in played: avail_v += v
            else:
                miss_v += v; miss_m += s[0]; n_miss += 1
        rows.append({'gid': gid, 'team': team, 'miss_v': miss_v, 'miss_m': miss_m, 'avail_v': avail_v, 'n_miss': n_miss})
        for r in x[x.played].itertuples():
            s = st.get(r.athlete_id)
            gpm = r.gmsc / max(r.min, 1)
            if s is None: st[r.athlete_id] = [r.min, gpm, i, 1]
            else:
                w = min(a, 1 - 1 / (s[3] + 1))           # early games weigh more until a few games are in
                s[0] = w * s[0] + (1 - w) * r.min; s[1] = w * s[1] + (1 - w) * gpm; s[2] = i; s[3] += 1
M = pd.DataFrame(rows)
M.to_pickle(f'{WORK}/nba_missing.pkl')
print(M.describe().round(2))
