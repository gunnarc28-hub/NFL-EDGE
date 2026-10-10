"""Aggregate nflverse play-by-play into one row per team per game (offense + defense allowed),
plus per-player red-zone (inside the 10) opportunities per game."""
import sys, numpy as np, pandas as pd

USE = ['game_id','season','week','season_type','posteam','defteam','home_team','away_team','play_type','pass','rush',
       'epa','success','yards_gained','sack','interception','fumble_lost','down','third_down_converted','third_down_failed',
       'yardline_100','fixed_drive','fixed_drive_result','drive_time_of_possession','wp','half_seconds_remaining','qtr',
       'pass_oe','cpoe','qb_scramble','pass_touchdown','two_point_attempt','penalty_team','penalty_yards',
       'home_score','away_score','spread_line','total_line','roof','div_game','rusher_player_id','receiver_player_id',
       'game_date','touchdown','td_team']

def mmss(s):
    try:
        m, sec = str(s).split(':'); return int(m) * 60 + int(sec)
    except Exception:
        return np.nan

def season_frames(year, path):
    p = pd.read_csv(path, usecols=USE, low_memory=False)
    p = p[p.season_type == 'REG'].copy()
    # ---------- scrimmage plays ----------
    s = p[(p.play_type.isin(['pass', 'run'])) & (p.two_point_attempt != 1) & p.epa.notna() & p.posteam.notna()].copy()
    s['is_pass'] = (s['pass'] == 1).astype(int)
    s['is_rush'] = ((s['rush'] == 1) & (s['pass'] != 1)).astype(int)
    s['explosive'] = (((s.is_pass == 1) & (s.yards_gained >= 20)) | ((s.is_rush == 1) & (s.yards_gained >= 10))).astype(int)
    s['early'] = s.down.isin([1, 2]).astype(int)
    s['to'] = (s.interception.fillna(0) + s.fumble_lost.fillna(0)).clip(upper=1)
    s['neutral'] = ((s.wp.between(0.2, 0.8)) & (s.half_seconds_remaining > 120)).astype(int)
    # ANY/A pieces (dropbacks without scrambles)
    db = (s.is_pass == 1) & (s.qb_scramble != 1)
    s['anya_num'] = np.where(db, s.yards_gained + 20 * s.pass_touchdown.fillna(0) - 45 * s.interception.fillna(0), 0)
    s['anya_den'] = db.astype(int)
    g = s.groupby(['game_id', 'posteam'])
    off = pd.DataFrame({
        'plays': g.size(),
        'epa_sum': g.epa.sum(),
        'succ_sum': g.success.sum(),
        'yds_sum': g.yards_gained.sum(),
        'dropbacks': g.is_pass.sum(),
        'rushes': g.is_rush.sum(),
        'explosive_n': g.explosive.sum(),
        'sacks': g.sack.sum(),
        'ints': g.interception.sum(),
        'to_n': g['to'].sum(),
        'anya_num': g.anya_num.sum(),
        'anya_den': g.anya_den.sum(),
    })
    off['pass_epa_sum'] = s[s.is_pass == 1].groupby(['game_id', 'posteam']).epa.sum()
    off['rush_epa_sum'] = s[s.is_rush == 1].groupby(['game_id', 'posteam']).epa.sum()
    off['pass_succ_sum'] = s[s.is_pass == 1].groupby(['game_id', 'posteam']).success.sum()
    off['rush_succ_sum'] = s[s.is_rush == 1].groupby(['game_id', 'posteam']).success.sum()
    off['rush_yds'] = s[s.is_rush == 1].groupby(['game_id', 'posteam']).yards_gained.sum()
    off['early_epa_sum'] = s[s.early == 1].groupby(['game_id', 'posteam']).epa.sum()
    off['early_n'] = s[s.early == 1].groupby(['game_id', 'posteam']).size()
    nt = s[s.neutral == 1]
    off['proe'] = nt.groupby(['game_id', 'posteam']).pass_oe.mean()
    off['neutral_plays'] = nt.groupby(['game_id', 'posteam']).size()
    off['cpoe'] = s.groupby(['game_id', 'posteam']).cpoe.mean()
    # ---------- third downs (all rows incl. penalties) ----------
    t3 = p[p.posteam.notna()].groupby(['game_id', 'posteam'])
    off['third_conv'] = t3.third_down_converted.sum()
    off['third_fail'] = t3.third_down_failed.sum()
    # ---------- drives ----------
    d = p[p.posteam.notna() & p.fixed_drive.notna()].groupby(['game_id', 'posteam', 'fixed_drive']).agg(
        result=('fixed_drive_result', 'first'), minyl=('yardline_100', 'min'), top=('drive_time_of_possession', 'first'))
    d['pts'] = d.result.map({'Touchdown': 7, 'Field goal': 3}).fillna(0)
    d['rz'] = (d.minyl <= 20).astype(int)
    d['rz_td'] = ((d.minyl <= 20) & (d.result == 'Touchdown')).astype(int)
    d['top_s'] = d.top.map(mmss)
    dg = d.reset_index().groupby(['game_id', 'posteam'])
    off['drives'] = dg.size()
    off['drive_pts'] = dg.pts.sum()
    off['rz_trips'] = dg.rz.sum()
    off['rz_tds'] = dg.rz_td.sum()
    off['top_s'] = dg.top_s.sum()
    # ---------- penalties ----------
    pen = p[p.penalty_team.notna()].groupby(['game_id', 'penalty_team']).penalty_yards.sum()
    pen.index.names = ['game_id', 'posteam']
    off['pen_yds'] = pen
    off = off.fillna({'pen_yds': 0, 'pass_epa_sum': 0, 'rush_epa_sum': 0, 'pass_succ_sum': 0, 'rush_succ_sum': 0,
                      'rush_yds': 0, 'early_epa_sum': 0, 'early_n': 0})
    off = off.reset_index().rename(columns={'posteam': 'team'})
    # ---------- game info ----------
    gi = p.groupby('game_id').agg(season=('season', 'first'), week=('week', 'first'), home_team=('home_team', 'first'),
                                  away_team=('away_team', 'first'), home_score=('home_score', 'max'),
                                  away_score=('away_score', 'max'), spread_line=('spread_line', 'first'),
                                  total_line=('total_line', 'first'), roof=('roof', 'first'),
                                  div_game=('div_game', 'first'), game_date=('game_date', 'first')).reset_index()
    off = off.merge(gi, on='game_id', how='left')
    off['home'] = (off.team == off.home_team).astype(int)
    off['opp'] = np.where(off.home == 1, off.away_team, off.home_team)
    off['pf'] = np.where(off.home == 1, off.home_score, off.away_score)
    off['pa'] = np.where(off.home == 1, off.away_score, off.home_score)
    # defense allowed = opponent's offense in same game
    dcols = ['plays', 'epa_sum', 'succ_sum', 'yds_sum', 'dropbacks', 'rushes', 'explosive_n', 'sacks', 'ints', 'to_n',
             'anya_num', 'anya_den', 'pass_epa_sum', 'rush_epa_sum', 'pass_succ_sum', 'rush_succ_sum', 'rush_yds',
             'early_epa_sum', 'early_n', 'third_conv', 'third_fail', 'drives', 'drive_pts', 'rz_trips', 'rz_tds',
             'top_s', 'pen_yds', 'cpoe', 'proe']
    dd = off[['game_id', 'team'] + dcols].rename(columns={'team': 'opp', **{c: 'd_' + c for c in dcols}})
    tg = off.merge(dd, on=['game_id', 'opp'], how='left')
    # ---------- red-zone (inside 10) player opportunities ----------
    rz = s[s.yardline_100 <= 10]
    r1 = rz[rz.is_rush == 1].groupby(['game_id', 'rusher_player_id']).size().rename('rz_carries')
    r1.index.names = ['game_id', 'player_id']
    r2 = rz[(rz.is_pass == 1) & rz.receiver_player_id.notna()].groupby(['game_id', 'receiver_player_id']).size().rename('rz_targets')
    r2.index.names = ['game_id', 'player_id']
    prz = pd.concat([r1, r2], axis=1).fillna(0).reset_index()
    prz['season'] = year
    return tg, prz



QB_USE = ['game_id', 'season', 'week', 'season_type', 'posteam', 'play_type', 'epa', 'two_point_attempt', 'qb_dropback',
          'passer_player_id', 'rusher_player_id', 'passer_player_name', 'rusher_player_name']


def qb_frames(year, path):
    """Dropbacks and EPA per quarterback per game (sacks and scrambles included)."""
    p = pd.read_csv(path, usecols=QB_USE, low_memory=False)
    p = p[(p.season_type == 'REG') & p.play_type.isin(['pass', 'run']) & (p.two_point_attempt != 1) & p.epa.notna()
          & p.posteam.notna() & (p.qb_dropback == 1)].copy()
    p['qb'] = p.passer_player_id.fillna(p.rusher_player_id)
    p['qb_name'] = p.passer_player_name.fillna(p.rusher_player_name)
    q = p.groupby(['game_id', 'posteam', 'qb']).agg(db=('epa', 'size'), qb_epa=('epa', 'sum'), name=('qb_name', 'first'),
                                                     week=('week', 'first')).reset_index()
    q['season'] = year
    return q
