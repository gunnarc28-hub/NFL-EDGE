"""NBA research data: games 2011-12 to now with scores, team box scores, rest, and closing lines.
Lines: SBR archives (2007-08 to 2022-23) and ESPN's odds API (2022-23 on)."""
import pandas as pd, numpy as np, glob, os, re
RAW = 'raw'; WORK = 'work'

# ---------------- schedule + scores (ESPN ids via hoopR)
sch = []
for y in range(2012, 2028):
    s = pd.read_csv(f'{RAW}/nba/schedule_{y}.csv', low_memory=False)
    s = s[s.season_type.isin([2, 3])]
    sch.append(s[['id', 'date', 'season', 'season_type', 'neutral_site', 'home_abbreviation', 'away_abbreviation', 'home_score', 'away_score', 'status_type_completed', 'venue_address_city', 'venue_address_state']])
sch = pd.concat(sch).drop_duplicates('id')
sch = sch.rename(columns={'id': 'gid', 'home_abbreviation': 'home', 'away_abbreviation': 'away', 'home_score': 'hs', 'away_score': 'as_'})
sch['t'] = pd.to_datetime(sch.date, utc=True)
sch['day'] = sch.t.dt.tz_convert('America/New_York').dt.date.astype(str)
sch = sch.sort_values('t').reset_index(drop=True)
print('games', len(sch), sch.groupby('season').size().to_dict())

# ---------------- team box: possessions and four factors
tb = []
for y in range(2012, 2028):
    t = pd.read_csv(f'{RAW}/nba/team_box_{y}.csv', low_memory=False)
    tb.append(t[['game_id', 'team_abbreviation', 'team_home_away', 'team_score', 'field_goals_made', 'field_goals_attempted', 'three_point_field_goals_made',
                 'three_point_field_goals_attempted', 'free_throws_made', 'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds', 'total_rebounds',
                 'assists', 'steals', 'blocks', 'turnovers', 'total_turnovers', 'fouls']])
tb = pd.concat(tb).drop_duplicates(['game_id', 'team_abbreviation'])
tb['tov'] = tb.total_turnovers.fillna(tb.turnovers)
tb['poss'] = tb.field_goals_attempted - tb.offensive_rebounds + tb.tov + 0.44 * tb.free_throws_attempted
tb.to_pickle(f'{WORK}/nba_team_box.pkl')

# ---------------- SBR closing lines
SBR_AB = {'Atlanta': 'ATL', 'Boston': 'BOS', 'Brooklyn': 'BKN', 'Charlotte': 'CHA', 'Chicago': 'CHI', 'Cleveland': 'CLE', 'Dallas': 'DAL', 'Denver': 'DEN',
          'Detroit': 'DET', 'GoldenState': 'GS', 'Golden State': 'GS', 'Houston': 'HOU', 'Indiana': 'IND', 'LAClippers': 'LAC', 'LA Clippers': 'LAC', 'LALakers': 'LAL',
          'Memphis': 'MEM', 'Miami': 'MIA', 'Milwaukee': 'MIL', 'Minnesota': 'MIN', 'NewJersey': 'NJ', 'NewOrleans': 'NO', 'NewYork': 'NY', 'OklahomaCity': 'OKC',
          'Oklahoma City': 'OKC', 'Orlando': 'ORL', 'Philadelphia': 'PHI', 'Phoenix': 'PHX', 'Portland': 'POR', 'Sacramento': 'SAC', 'SanAntonio': 'SA', 'Seattle': 'SEA',
          'Toronto': 'TOR', 'Utah': 'UTAH', 'Washington': 'WSH'}
def num(v):
    v = str(v).strip().lower()
    if v in ('pk', 'p', "pk'"): return 0.0
    try: return float(v)
    except ValueError: return np.nan
rows = []
for f in sorted(glob.glob(f'{RAW}/sbr/nba_*.csv')):
    y0 = int(re.search(r'(\d{4})-', f).group(1))
    d = pd.read_csv(f)
    d = d[d.VH.isin(['V', 'H', 'N'])].reset_index(drop=True)
    for i in range(0, len(d) - 1, 2):
        v, h = d.iloc[i], d.iloc[i + 1]
        md = int(v.Date); mo, da = md // 100, md % 100
        yr = y0 if mo >= 8 else y0 + 1
        try: day = pd.Timestamp(year=yr, month=mo, day=da).date().isoformat()
        except ValueError: continue
        vo, vc, ho, hc = num(v.Open), num(v.Close), num(h.Open), num(h.Close)
        def split(a, b):   # returns (home_line, total) from the visitor's and home team's numbers
            if np.isnan(a) or np.isnan(b): return np.nan, np.nan
            if a > 100 and b < 100: return -b, a          # home row holds the spread: home favored by b
            if b > 100 and a < 100: return a, b           # visitor row holds the spread: visitor favored by a -> home +a
            return np.nan, np.nan
        sp_o, tl_o = split(vo, ho); sp_c, tl_c = split(vc, hc)
        rows.append({'day': day, 'away': SBR_AB.get(str(v.Team).strip()), 'home': SBR_AB.get(str(h.Team).strip()), 'sbr_as': num(v.Final), 'sbr_hs': num(h.Final),
                     'sp_open': sp_o, 'sp_close': sp_c, 'tl_open': tl_o, 'tl_close': tl_c, 'ml_a': num(v.ML), 'ml_h': num(h.ML), 'neutral': v.VH == 'N'})
sbr = pd.DataFrame(rows)
print('sbr games', len(sbr), 'missing teams', sbr.home.isna().sum() + sbr.away.isna().sum(), 'no close spread', sbr.sp_close.isna().sum())

# ---------------- ESPN odds API (event id = game id)
od = pd.read_csv(f'{RAW}/odds/nba_odds.csv'); ev = pd.read_csv(f'{RAW}/odds/nba_events.csv')
pref = ['ESPN BET', 'Draft Kings', 'DraftKings', 'Caesars Sportsbook (Colorado)', 'MGM', 'consensus']
od['rank'] = od.provider.map({p: i for i, p in enumerate(pref)}).fillna(99)
def pick(col_close, col_now, lo, hi):
    # ESPN's 2022-23 'close' records hold prices where the line should be, so a value outside the line's range falls back to the last line
    x = od.copy(); c = x[col_close].where(x[col_close].between(lo, hi)); n = x[col_now].where(x[col_now].between(lo, hi))
    x['v'] = c.fillna(n)
    x = x[x.v.notna()].sort_values(['event', 'rank'])
    return x.groupby('event').v.first()
ML = (-20000, 20000)
esp = pd.DataFrame({'e_sp': pick('h_line_close', 'spread', -30, 30), 'e_tl': pick('total_close', 'over_under', 150, 300), 'e_mlh': pick('h_ml_close', 'h_ml', *ML), 'e_mla': pick('a_ml_close', 'a_ml', *ML),
                    'e_sp_open': pick('h_line_open', 'spread', -30, 30), 'e_tl_open': pick('total_open', 'over_under', 150, 300)}).reset_index().rename(columns={'event': 'gid'})
print('espn odds events', len(esp))

g = sch.merge(esp, on='gid', how='left')
g = g.merge(sbr, on=['day', 'home', 'away'], how='left', suffixes=('', '_sbr'))
# agreement check where both exist
both = g[g.e_sp.notna() & g.sp_close.notna()]
print('overlap', len(both), 'spread agree within 1.5:', (abs(both.e_sp - both.sp_close) <= 1.5).mean().round(3), 'sign agree', (np.sign(both.e_sp) == np.sign(both.sp_close)).mean().round(3))
g['line'] = g.e_sp.where(g.e_sp.notna(), g.sp_close)          # home line, negative = home favored
g['total'] = g.e_tl.where(g.e_tl.notna(), g.tl_close)
g['ml_home'] = g.e_mlh.where(g.e_mlh.notna(), g.ml_h); g['ml_away'] = g.e_mla.where(g.e_mla.notna(), g.ml_a)
g['line_open'] = g.e_sp_open.where(g.e_sp_open.notna(), g.sp_open); g['total_open'] = g.e_tl_open.where(g.e_tl_open.notna(), g.tl_open)
g['margin'] = g.hs - g.as_
print(g.groupby('season').agg(n=('gid', 'size'), line=('line', 'count'), total=('total', 'count'), ml=('ml_home', 'count')))
g.to_pickle(f'{WORK}/nba_games.pkl')
