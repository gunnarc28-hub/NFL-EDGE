"""NFL play-by-play (nflverse, play_by_play_<year>.csv.gz, 2016-2026) reduced to what the quarter and half research
needs. -> work/
  nfl_qscores.pkl  one row per game: points by quarter for each team, overtime
  nfl_pq.pkl       one row per player per game: passing, rushing and receiving yards, catches and touchdowns in the
                   1st quarter and the 1st half (2-point tries and kneels left out, as the box score does)"""
import pandas as pd
RAW, WORK = '/home/claude/sports/raw/pbp/nfl', '/home/claude/nfl/work'
COLS = ['game_id', 'season', 'season_type', 'week', 'home_team', 'away_team', 'qtr', 'total_home_score', 'total_away_score', 'posteam', 'play_type',
        'two_point_attempt', 'passer_player_id', 'passing_yards', 'rusher_player_id', 'rushing_yards', 'receiver_player_id', 'receiving_yards',
        'complete_pass', 'td_player_id', 'touchdown']
Q, P = [], []
for yr in range(2016, 2027):
    d = pd.read_csv(f'{RAW}/play_by_play_{yr}.csv.gz', usecols=COLS, low_memory=False)
    end = d.groupby(['game_id', 'qtr'])[['total_home_score', 'total_away_score']].max().reset_index().sort_values(['game_id', 'qtr'])
    end[['ph', 'pa']] = end.groupby('game_id')[['total_home_score', 'total_away_score']].diff().fillna(end[['total_home_score', 'total_away_score']])
    meta = d.groupby('game_id').agg(season=('season', 'first'), season_type=('season_type', 'first'), week=('week', 'first'),
                                    home=('home_team', 'first'), away=('away_team', 'first'))
    wide = {}
    for r in end.itertuples():
        w = wide.setdefault(r.game_id, {'ot_h': 0.0, 'ot_a': 0.0})
        q = int(r.qtr)
        if q <= 4:
            w[f'q{q}h'], w[f'q{q}a'] = float(r.ph), float(r.pa)
        else:
            w['ot_h'] += float(r.ph); w['ot_a'] += float(r.pa)
    Q.append(meta.join(pd.DataFrame.from_dict(wide, orient='index')).reset_index().rename(columns={'index': 'game_id'}))
    x = d[(d.two_point_attempt != 1)]
    for nm, qs in (('q1', [1]), ('h1', [1, 2])):
        z = x[x.qtr.isin(qs)]
        parts = [z.groupby(['game_id', 'passer_player_id']).passing_yards.sum().rename(f'{nm}_pass_yds'),
                 z.groupby(['game_id', 'rusher_player_id']).rushing_yards.sum().rename(f'{nm}_rush_yds'),
                 z.groupby(['game_id', 'receiver_player_id']).receiving_yards.sum().rename(f'{nm}_rec_yds'),
                 z[z.complete_pass == 1].groupby(['game_id', 'receiver_player_id']).size().rename(f'{nm}_receptions'),
                 z[z.touchdown == 1].groupby(['game_id', 'td_player_id']).size().rename(f'{nm}_td')]
        for s in parts:
            s.index = s.index.set_names(['game_id', 'player_id'])
        P.append(pd.concat(parts, axis=1).reset_index())
    print(yr, 'games', len(wide), flush=True)
QS = pd.concat(Q, ignore_index=True); QS.to_pickle(f'{WORK}/nfl_qscores.pkl')
PQ = pd.concat(P, ignore_index=True).groupby(['game_id', 'player_id']).sum(min_count=1).fillna(0).reset_index(); PQ.to_pickle(f'{WORK}/nfl_pq.pkl')
print('games', len(QS), 'player rows', len(PQ))
