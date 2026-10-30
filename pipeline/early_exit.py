"""Who left an NFL game hurt in the 1st half and never came back (DraftKings' "Early Exit": full-game player props on
that player are settled as void, and a parlay drops the leg), from the injury notes in the play-by-play.

The official play-by-play marks injuries as "CAR-18-J.Coker was injured during the play." and returns as
"** Injury Update: CAR-18-J.Coker has returned to the game." A player counts as an early exit when he was hurt in the
1st or 2nd quarter, no return was noted, he isn't named in any later play, and his snap count for the game is no more
than his team's plays up to the injury (so a quiet return can't pass for an exit). Without snap counts for a game there
is no verdict yet."""
import re
import pandas as pd

HURT = re.compile(r'(?<![A-Za-z])([A-Z]{2,3})-(\d{1,2})-([A-Z][^ ]*\.[A-Za-z][^(;,]*?) was injured during the play')
BACK = re.compile(r'Injury Update: ([A-Z]{2,3})-(\d{1,2})-([A-Z][^ ]*\.[A-Za-z][^(;,]*?) has returned to the game')
OFF, ST = {'run', 'pass', 'qb_kneel', 'qb_spike', 'no_play'}, {'punt', 'kickoff', 'field_goal', 'extra_point'}   # a team's snaps: its plays, every kick
COLS = ['play_id', 'game_id', 'week', 'qtr', 'game_seconds_remaining', 'desc', 'posteam', 'defteam', 'play_type', 'touchdown', 'td_player_id']


def _last(nm):
    """'J.Coker' -> 'coker', 'A.St. Brown' -> 'stbrown', 'M.Harrison Jr.' -> 'harrison'"""
    s = str(nm).split('.', 1)[-1]
    s = re.sub(r'\b(Jr|Sr|II|III|IV|V)\.?$', '', s.strip())
    return re.sub(r'[^a-z]', '', s.lower())


def _elapsed(r):
    """seconds into the game (overtime past 3600)"""
    g = r.game_seconds_remaining
    return None if pd.isna(g) else int(round(3600 - g)) if r.qtr <= 4 else int(round(3600 + (600 - (g if g <= 600 else 600))))


def first_half_exits(pbp_path, roster, snaps, games=None):
    """{game_id: {gsis_id: seconds into the game when he left}} for games with snap counts.
    roster: nflverse weekly rosters (team, week, jersey_number, gsis_id, pfr_id, last_name);
    snaps: nflverse snap counts (game_id, pfr_player_id, offense_snaps, st_snaps)."""
    p = pd.read_csv(pbp_path, usecols=COLS, low_memory=False)
    if games is not None:
        p = p[p.game_id.isin(set(games))]
    p = p.sort_values(['game_id', 'play_id']).reset_index(drop=True)
    have_snaps = set(snaps.game_id)
    snap_of = {(r.game_id, r.pfr_player_id): int(sum(x for x in (r.offense_snaps, r.st_snaps) if pd.notna(x))) for r in snaps.itertuples()}
    ro = roster.dropna(subset=['gsis_id', 'jersey_number'])
    by_num = {}
    for r in ro.itertuples():
        try:
            by_num.setdefault((r.team, int(r.week), int(r.jersey_number)), []).append(r)
        except (TypeError, ValueError):
            continue
    out = {}
    for gid, g in p.groupby('game_id', sort=False):
        if gid not in have_snaps:
            continue
        desc = g.desc.fillna('').tolist(); qtr = g.qtr.tolist(); wk = int(g.week.iloc[0])
        pt = g.play_type.fillna('').tolist(); pos = g.posteam.fillna('').tolist()
        hurt = [(i, m) for i, d in enumerate(desc) for m in HURT.finditer(d)]
        if not hurt:
            continue
        backs = [(i, (m.group(1), int(m.group(2)))) for i, d in enumerate(desc) for m in BACK.finditer(d)]
        for i, m in hurt:
            team, num, nm = m.group(1), int(m.group(2)), m.group(3).strip()
            if qtr[i] > 2:
                continue
            if any(j > i and k == (team, num) for j, k in backs):
                continue                                                   # noted as back in the game
            seen = re.compile(r'(?<![\d\-])' + str(num) + '-' + re.escape(nm) + r'(?![A-Za-z])')
            if any(seen.search(desc[j]) for j in range(i + 1, len(desc))):
                continue                                                   # in a later play, so he came back
            want = _last(nm)
            rows = by_num.get((team, wk, num)) or by_num.get((team, wk - 1, num)) or []
            ids = {r.gsis_id for r in rows if want and want in re.sub(r'[^a-z]', '', str(r.last_name).lower())}
            if len(ids) != 1:
                continue                                                   # can't tell who it was
            pl = next(r for r in rows if r.gsis_id in ids)
            plays_before = sum(1 for j in range(i + 1) if (pos[j] == team and pt[j] in OFF) or pt[j] in ST)
            sn = snap_of.get((gid, pl.pfr_id))
            if sn is None or sn > plays_before + 2:
                continue                                                   # no snap count yet, or it says he played on
            out.setdefault(gid, {})[pl.gsis_id] = _elapsed(g.iloc[i])
    return out


def first_td_times(pbp_path, games=None):
    """{game_id: seconds into the game of its first touchdown} (games with no touchdown are left out)"""
    p = pd.read_csv(pbp_path, usecols=['play_id', 'game_id', 'qtr', 'game_seconds_remaining', 'touchdown', 'td_player_id'], low_memory=False)
    if games is not None:
        p = p[p.game_id.isin(set(games))]
    p = p[(p.touchdown == 1) & p.td_player_id.notna()].sort_values(['game_id', 'play_id'])
    return {gid: _elapsed(g.iloc[0]) for gid, g in p.groupby('game_id')}
