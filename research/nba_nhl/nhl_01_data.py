"""NHL research data: games 2010-11 to now, team and goalie box scores, rest, starting goalies, closing lines.
Lines: SBR archives (most seasons 2007-08 to 2022-23) and ESPN's odds API (2022-23 on)."""
import pandas as pd, numpy as np, glob, re
RAW = 'raw'; WORK = 'work'
sch = []
for y in range(2011, 2028):
    s = pd.read_csv(f'{RAW}/nhl/schedule_{y}.csv', low_memory=False)
    s = s[s.game_type.isin(['R', 'P'])]
    sch.append(s[['game_id', 'season_full', 'game_type', 'game_date', 'game_time', 'home_team_abbr', 'away_team_abbr', 'home_score', 'away_score', 'game_state', 'venue']])
sch = pd.concat(sch).drop_duplicates('game_id').rename(columns={'game_id': 'gid', 'home_team_abbr': 'home', 'away_team_abbr': 'away', 'home_score': 'hs', 'away_score': 'as_'})
sch['season'] = sch.season_full.astype(str).str[-4:].astype(int)
sch['t'] = pd.to_datetime(sch.game_time, utc=True, format='ISO8601')
sch['day'] = sch.game_date.astype(str)
sch = sch.sort_values('t').reset_index(drop=True)
print('games', len(sch), sch.groupby('season').size().to_dict())

# ---- box scores
tb = pd.concat([pd.read_csv(f'{RAW}/nhl/team_box_{y}.csv', low_memory=False) for y in range(2011, 2028)]).drop_duplicates(['game_id', 'team_abbrev'])
tb.to_pickle(f'{WORK}/nhl_team_box.pkl')
gb = pd.concat([pd.read_csv(f'{RAW}/nhl/goalie_box_{y}.csv', low_memory=False) for y in range(2011, 2028)]).drop_duplicates(['game_id', 'player_id'])
gb.to_pickle(f'{WORK}/nhl_goalie_box.pkl')
sk = pd.concat([pd.read_csv(f'{RAW}/nhl/skater_box_{y}.csv', low_memory=False) for y in range(2011, 2028)]).drop_duplicates(['game_id', 'player_id'])
sk.to_pickle(f'{WORK}/nhl_skater_box.pkl')
print('team box', len(tb), 'goalie rows', len(gb), 'skater rows', len(sk))

# ---- SBR (moneylines, puck line, totals)
SBR = {'Anaheim': 'ANA', 'Arizona': 'ARI', 'Arizonas': 'ARI', 'Atlanta': 'ATL', 'Boston': 'BOS', 'Buffalo': 'BUF', 'Calgary': 'CGY', 'Carolina': 'CAR', 'Chicago': 'CHI',
       'Colorado': 'COL', 'Columbus': 'CBJ', 'Dallas': 'DAL', 'Detroit': 'DET', 'Edmonton': 'EDM', 'Florida': 'FLA', 'Los Angeles': 'LAK', 'LosAngeles': 'LAK', 'Minnesota': 'MIN',
       'Montreal': 'MTL', 'NY Islanders': 'NYI', 'NYIslanders': 'NYI', 'NY Rangers': 'NYR', 'NYRangers': 'NYR', 'Nashville': 'NSH', 'New Jersey': 'NJD', 'NewJersey': 'NJD',
       'Ottawa': 'OTT', 'Philadelphia': 'PHI', 'Phoenix': 'PHX', 'Pittsburgh': 'PIT', 'San Jose': 'SJS', 'SanJose': 'SJS', 'Seattle': 'SEA', 'Seattle Kraken': 'SEA',
       'SeattleKraken': 'SEA', 'St. Louis': 'STL', 'St.Louis': 'STL', 'Tampa': 'TBL', 'Tampa Bay': 'TBL', 'TampaBay': 'TBL', 'Toronto': 'TOR', 'Vancouver': 'VAN', 'Vegas': 'VGK',
       'Washington': 'WSH', 'Winnipeg': 'WPG', 'WinnipegJets': 'WPG'}
def num(v):
    v = str(v).strip().lower()
    if v in ('pk', 'even', 'ev'): return 100.0
    try: return float(v)
    except ValueError: return np.nan
rows = []
for f in sorted(glob.glob(f'{RAW}/sbr/nhl_*.csv')):
    y0 = int(re.search(r'(\d{4})-', f).group(1))
    d = pd.read_csv(f); cols = list(d.columns)
    has_pl = 'PuckLine' in cols
    ou_c = cols.index('CloseOU'); ou_o = cols.index('OpenOU')
    d = d[d.VH.isin(['V', 'H', 'N'])].reset_index(drop=True)
    for i in range(0, len(d) - 1, 2):
        v, h = d.iloc[i], d.iloc[i + 1]
        md = int(v.Date); mo, da = md // 100, md % 100
        yr = y0 if mo >= 8 else y0 + 1
        try: day = pd.Timestamp(year=yr, month=mo, day=da).date().isoformat()
        except ValueError: continue
        rows.append({'day': day, 'away': SBR.get(str(v.Team).strip()), 'home': SBR.get(str(h.Team).strip()), 'ml_a': num(v.Close), 'ml_h': num(h.Close),
                     'mlo_a': num(v.Open), 'mlo_h': num(h.Open), 'tl_close': num(v.iloc[ou_c]), 'over_c': num(v.iloc[ou_c + 1]), 'under_c': num(h.iloc[ou_c + 1]),
                     'tl_open': num(v.iloc[ou_o]), 'pl_h': num(h.PuckLine) if has_pl else np.nan, 'pl_h_odds': num(h.iloc[cols.index('PuckLine') + 1]) if has_pl else np.nan,
                     'pl_a_odds': num(v.iloc[cols.index('PuckLine') + 1]) if has_pl else np.nan, 'sbr_hs': num(h.Final), 'sbr_as': num(v.Final)})
sbr = pd.DataFrame(rows)
print('sbr', len(sbr), 'unmapped', sbr.home.isna().sum() + sbr.away.isna().sum())

# ---- ESPN odds API
ESPN = {'NJ': 'NJD', 'SJ': 'SJS', 'TB': 'TBL', 'LA': 'LAK', 'UTAH': 'UTA'}
od = pd.read_csv(f'{RAW}/odds/nhl_odds.csv'); ev = pd.read_csv(f'{RAW}/odds/nhl_events.csv')
ev['home'] = ev.home.replace(ESPN); ev['away'] = ev.away.replace(ESPN)
ev['day'] = pd.to_datetime(ev.date, utc=True).dt.tz_convert('America/New_York').dt.date.astype(str)
pref = ['ESPN BET', 'Draft Kings', 'DraftKings', 'Caesars Sportsbook (Colorado)', 'MGM', 'Bet365']
od['rank'] = od.provider.map({p: i for i, p in enumerate(pref)}).fillna(99)
def pick(col_close, col_now, lo, hi):
    x = od.copy(); c = x[col_close].where(x[col_close].between(lo, hi)); n = x[col_now].where(x[col_now].between(lo, hi)) if col_now else np.nan
    x['v'] = c.fillna(n) if col_now else c
    x = x[x.v.notna()].sort_values(['event', 'rank'])
    return x.groupby('event').v.first()
ML = (-5000, 5000)
esp = pd.DataFrame({'e_mlh': pick('h_ml_close', 'h_ml', *ML), 'e_mla': pick('a_ml_close', 'a_ml', *ML), 'e_tl': pick('total_close', 'over_under', 3, 9),
                    'e_mlh_o': pick('h_ml_open', None, *ML), 'e_mla_o': pick('a_ml_open', None, *ML),
                    'e_over': pick('over_close_odds', 'over_odds', *ML), 'e_under': pick('under_close_odds', 'under_odds', *ML)}).reset_index()
esp = esp.merge(ev[['event', 'day', 'home', 'away']], on='event')
g = sch.merge(esp, on=['day', 'home', 'away'], how='left').merge(sbr, on=['day', 'home', 'away'], how='left')
both = g[g.e_mlh.notna() & g.ml_h.notna()]
print('overlap', len(both), 'same favorite', (np.sign(both.e_mlh) == np.sign(both.ml_h)).mean().round(3), 'total agree', (both.e_tl == both.tl_close).mean().round(3))
g['ml_home'] = g.e_mlh.where(g.e_mlh.notna(), g.ml_h); g['ml_away'] = g.e_mla.where(g.e_mla.notna(), g.ml_a)
g['total'] = g.e_tl.where(g.e_tl.notna(), g.tl_close)
g['over_odds'] = g.e_over.where(g.e_over.notna(), g.over_c); g['under_odds'] = g.e_under.where(g.e_under.notna(), g.under_c)
# the schedule's scores are wrong for several seasons; rebuild finals from the box scores (a shootout winner gets one goal, as books count it)
goals = sk.groupby(['game_id', 'team_abbrev']).goals.sum()
dec = gb[gb.decision == 'W'].drop_duplicates('game_id').set_index('game_id').team_abbrev
g['bh'] = [goals.get((r.gid, r.home), np.nan) for r in g.itertuples()]; g['ba'] = [goals.get((r.gid, r.away), np.nan) for r in g.itertuples()]
g['winner'] = g.gid.map(dec)
g['so'] = (g.bh == g.ba) & g.winner.notna()
ok = g.bh.notna() & g.winner.notna()
g.loc[ok, 'hs'] = g.bh + ((g.so) & (g.winner == g.home)).astype(int); g.loc[ok, 'as_'] = g.ba + ((g.so) & (g.winner == g.away)).astype(int)
g.loc[~ok & (g.game_state.isin(['OFF', 'FINAL'])), ['hs', 'as_']] = np.nan
g['margin'] = g.hs - g.as_
print(g.groupby('season').agg(n=('gid', 'size'), ml=('ml_home', 'count'), total=('total', 'count')).T)
g.to_pickle(f'{WORK}/nhl_games.pkl')
