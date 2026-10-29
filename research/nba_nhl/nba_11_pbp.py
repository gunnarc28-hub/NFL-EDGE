"""NBA play-by-play (hoopR / ESPN, raw/pbp/nba/play_by_play_<year>.csv, 2020-21 to now) reduced to what the quarter, half
and first-basket research needs. -> work/
  nba_qscores.pkl  one row per game: points by quarter for each team, overtime, the jump ball and the first scores
  nba_pq.pkl       one row per player per game: points, rebounds, assists and shots in the 1st quarter and 1st half
A season is labeled by the year it ends; regular season and playoffs only."""
import numpy as np, pandas as pd
RAW, WORK = '/home/claude/sports/raw/pbp/nba', '/home/claude/sports/work'
COLS = ['game_id', 'season', 'season_type', 'game_play_number', 'sequence_number', 'type_text', 'text', 'period_number', 'clock_display_value',
        'scoring_play', 'score_value', 'shooting_play', 'team_id', 'athlete_id_1', 'athlete_id_2', 'athlete_id_3', 'home_score', 'away_score',
        'home_team_id', 'away_team_id', 'home_team_abbrev', 'away_team_abbrev']
Q, P = [], []
for yr in range(2021, 2028):
    d = pd.read_csv(f'{RAW}/play_by_play_{yr}.csv', usecols=COLS, low_memory=False)
    d = d[d.season_type.isin([2, 3])].copy()
    d['seq'] = pd.to_numeric(d.sequence_number, errors='coerce')
    d = d.sort_values(['game_id', 'period_number', 'game_play_number', 'seq'])
    d['scoring_play'] = d.scoring_play.astype(str).str.lower().eq('true')
    d['ft'] = d.type_text.astype(str).str.contains('Free Throw')
    d['fg_made'] = d.scoring_play & ~d.ft & d.score_value.isin([2, 3])
    # ---- per game: points by period from the running score
    end = d.groupby(['game_id', 'period_number'])[['home_score', 'away_score']].max().reset_index().sort_values(['game_id', 'period_number'])
    end[['ph', 'pa']] = end.groupby('game_id')[['home_score', 'away_score']].diff().fillna(end[['home_score', 'away_score']])
    meta = d.groupby('game_id').agg(season=('season', 'first'), season_type=('season_type', 'first'), home_id=('home_team_id', 'first'),
                                    away_id=('away_team_id', 'first'), home=('home_team_abbrev', 'first'), away=('away_team_abbrev', 'first'))
    wide = {}
    for r in end.itertuples():
        w = wide.setdefault(r.game_id, {'ot_h': 0.0, 'ot_a': 0.0, 'n_per': 0})
        p = int(r.period_number)
        if p <= 4:
            w[f'q{p}h'], w[f'q{p}a'] = float(r.ph), float(r.pa)
        else:
            w['ot_h'] += float(r.ph); w['ot_a'] += float(r.pa)
        w['n_per'] = max(w['n_per'], p)
    qs = meta.join(pd.DataFrame.from_dict(wide, orient='index'))
    # ---- firsts: the opening jump ball, the first points of any kind, the first field goal
    jb = d[(d.period_number == 1) & d.type_text.astype(str).str.startswith('Jump')].groupby('game_id').first()
    qs['jb_team'] = jb.team_id; qs['jb_p1'] = jb.athlete_id_1; qs['jb_p2'] = jb.athlete_id_2; qs['jb_poss'] = jb.athlete_id_3
    fs = d[d.scoring_play].groupby('game_id').first()
    qs['first_pts_team'] = fs.team_id; qs['first_pts_ft'] = fs.ft
    ff = d[d.fg_made].groupby('game_id').first()
    qs['first_fg_team'] = ff.team_id; qs['first_fg_player'] = ff.athlete_id_1; qs['first_fg_period'] = ff.period_number; qs['first_fg_clock'] = ff.clock_display_value
    for side in ('home', 'away'):                      # each team's first field goal
        tf = d[d.fg_made & (d.team_id == d[f'{side}_team_id'])].groupby('game_id').first()
        qs[f'first_fg_{side}_player'] = tf.athlete_id_1
    Q.append(qs.reset_index().rename(columns={'index': 'game_id'}))
    # ---- per player: 1st quarter and 1st half
    for nm, per in (('q1', [1]), ('h1', [1, 2])):
        x = d[d.period_number.isin(per)]
        pts = x[x.scoring_play].groupby(['game_id', 'athlete_id_1']).score_value.sum().rename(f'{nm}_pts')
        reb = x[x.type_text.isin(['Offensive Rebound', 'Defensive Rebound'])].groupby(['game_id', 'athlete_id_1']).size().rename(f'{nm}_reb')
        ast = x[x.fg_made & x.athlete_id_2.notna() & x.text.astype(str).str.contains('assist')].groupby(['game_id', 'athlete_id_2']).size().rename(f'{nm}_ast')
        ast.index = ast.index.set_names(['game_id', 'athlete_id_1'])
        fga = x[x.shooting_play.astype(str).str.lower().eq('true') & ~x.ft].groupby(['game_id', 'athlete_id_1']).size().rename(f'{nm}_fga')
        P.append(pd.concat([pts, reb, ast, fga], axis=1).reset_index().rename(columns={'athlete_id_1': 'athlete_id'}).assign(part=nm))
    print(yr, 'games', len(qs), 'with 4 quarters', int(qs.q4h.notna().sum()), 'jump balls', int(qs.jb_team.notna().sum()), flush=True)
QS = pd.concat(Q, ignore_index=True)
QS.to_pickle(f'{WORK}/nba_qscores.pkl')
PQ = pd.concat(P, ignore_index=True).drop(columns='part').groupby(['game_id', 'athlete_id']).sum(min_count=1).fillna(0).reset_index()
PQ.to_pickle(f'{WORK}/nba_pq.pkl')
print('games', len(QS), 'player rows', len(PQ))
