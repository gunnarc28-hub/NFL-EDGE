"""Read a bet from a DraftKings share link and hand it to the Sports Edge page that asked, encrypted so only that phone
can open it (the repository is public). Run by .github/workflows/dk-import.yml when the page's "Add from a link" gets a
DraftKings link.

DraftKings' share page draws the bet in the browser from its comments service; that service answers a request that
looks like it came from DraftKings' own pages. The bet (betJSON) lists every leg with the book's names and odds. Each leg
is matched to the site's games and players through the live site's grade files (ESPN ids for the NBA, the NHL's ids,
nflverse ids for the NFL); a leg that can't be matched comes back as an "other" leg carrying DraftKings' own result.

env: POST (the share link), KEY (the page's RSA public key, base64 SPKI), NONCE (the page's request id).
Writes out/<NONCE>.json: {"k": wrapped AES key, "iv", "ct"} holding {"bets": [...], "notes": [...]} or {"error": "..."}."""
import os, re, json, base64, time, datetime as dt, urllib.request, urllib.error
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'
LIVE = os.environ.get('LIVE', 'https://gunnarc28-hub.github.io/NFL-EDGE/')
UNIT = 10.0                                            # dollars per unit
NICK = {
    'nba': {'Hawks': 'ATL', 'Celtics': 'BOS', 'Nets': 'BKN', 'Hornets': 'CHA', 'Bulls': 'CHI', 'Cavaliers': 'CLE', 'Mavericks': 'DAL',
            'Nuggets': 'DEN', 'Pistons': 'DET', 'Warriors': 'GS', 'Rockets': 'HOU', 'Pacers': 'IND', 'Clippers': 'LAC', 'Lakers': 'LAL',
            'Grizzlies': 'MEM', 'Heat': 'MIA', 'Bucks': 'MIL', 'Timberwolves': 'MIN', 'Pelicans': 'NO', 'Knicks': 'NY', 'Thunder': 'OKC',
            'Magic': 'ORL', '76ers': 'PHI', 'Suns': 'PHX', 'Trail Blazers': 'POR', 'Kings': 'SAC', 'Spurs': 'SA', 'Raptors': 'TOR',
            'Jazz': 'UTAH', 'Wizards': 'WSH'},
    'nhl': {'Ducks': 'ANA', 'Bruins': 'BOS', 'Sabres': 'BUF', 'Flames': 'CGY', 'Hurricanes': 'CAR', 'Blackhawks': 'CHI', 'Avalanche': 'COL',
            'Blue Jackets': 'CBJ', 'Stars': 'DAL', 'Red Wings': 'DET', 'Oilers': 'EDM', 'Panthers': 'FLA', 'Kings': 'LAK', 'Wild': 'MIN',
            'Canadiens': 'MTL', 'Predators': 'NSH', 'Devils': 'NJD', 'Islanders': 'NYI', 'Rangers': 'NYR', 'Senators': 'OTT', 'Flyers': 'PHI',
            'Penguins': 'PIT', 'Sharks': 'SJS', 'Kraken': 'SEA', 'Blues': 'STL', 'Lightning': 'TBL', 'Maple Leafs': 'TOR', 'Mammoth': 'UTA',
            'Canucks': 'VAN', 'Golden Knights': 'VGK', 'Capitals': 'WSH', 'Jets': 'WPG'},
    'nfl': {'Cardinals': 'ARI', 'Falcons': 'ATL', 'Ravens': 'BAL', 'Bills': 'BUF', 'Panthers': 'CAR', 'Bears': 'CHI', 'Bengals': 'CIN',
            'Browns': 'CLE', 'Cowboys': 'DAL', 'Broncos': 'DEN', 'Lions': 'DET', 'Packers': 'GB', 'Texans': 'HOU', 'Colts': 'IND',
            'Jaguars': 'JAX', 'Chiefs': 'KC', 'Raiders': 'LV', 'Chargers': 'LAC', 'Rams': 'LA', 'Dolphins': 'MIA', 'Vikings': 'MIN',
            'Patriots': 'NE', 'Saints': 'NO', 'Giants': 'NYG', 'Jets': 'NYJ', 'Eagles': 'PHI', 'Steelers': 'PIT', '49ers': 'SF',
            'Seahawks': 'SEA', 'Buccaneers': 'TB', 'Titans': 'TEN', 'Commanders': 'WAS'}}
LEAGUE = {'NBA': 'nba', 'NHL': 'nhl', 'NFL': 'nfl'}
# the book's market words -> the site's market (longest first). Scorer markets name the player in the outcome instead.
MK = {'nba': [('Points + Rebounds + Assists', 'pra'), ('Pts + Reb + Ast', 'pra'), ('Points + Rebounds', 'pr'), ('Pts + Reb', 'pr'),
              ('Points + Assists', 'pa'), ('Pts + Ast', 'pa'), ('Rebounds + Assists', 'ra'), ('Reb + Ast', 'ra'), ('Steals + Blocks', 'sb'),
              ('Three Pointers Made', 'fg3m'), ('3-Pointers Made', 'fg3m'), ('Threes', 'fg3m'), ('Points', 'pts'), ('Rebounds', 'reb'),
              ('Assists', 'ast'), ('Steals', 'stl'), ('Blocks', 'blk'), ('Turnovers', 'tov'), ('Double-Double', 'dd'), ('Double Double', 'dd'),
              ('Triple-Double', 'td3'), ('Triple Double', 'td3')],
      'nhl': [('Shots on Goal', 'sog'), ('Blocked Shots', 'blocks'), ('Points', 'points'), ('Assists', 'assists'), ('Saves', 'saves'),
              ('Goals', 'goals')],
      'nfl': [('Rush + Rec Yards', 'rush_rec'), ('Rushing + Receiving Yards', 'rush_rec'), ('Receiving Yards', 'rec_yds'), ('Rushing Yards', 'rush_yds'),
              ('Passing Yards', 'pass_yds'), ('Passing Touchdowns', 'pass_td'), ('Passing TDs', 'pass_td'), ('Pass Completions', 'completions'),
              ('Completions', 'completions'), ('Pass Attempts', 'pass_att'), ('Interceptions Thrown', 'ints'), ('Rushing Attempts', 'carries'),
              ('Receptions', 'receptions')]}
SCORER = {'Anytime TD Scorer': ('nfl', 'any_td'), 'First TD Scorer': ('nfl', 'first_td'), '2+ TDs': ('nfl', 'td2'), 'Anytime Goalscorer': ('nhl', 'atg'),
          'First Goalscorer': ('nhl', 'first_goal'), 'First Basket': ('nba', 'first_basket')}
PARTW = {'1st Quarter': 'q1', '2nd Quarter': 'q2', '3rd Quarter': 'q3', '4th Quarter': 'q4', '1st Half': 'h1', '2nd Half': 'h2',
         '1st Period': 'p1', '2nd Period': 'p2', '3rd Period': 'p3'}
norm = lambda s: re.sub(r'[^a-z0-9]', '', str(s).lower())
KNOWN = {'nfl': {'pass_yds', 'pass_td', 'completions', 'pass_att', 'ints', 'rush_yds', 'carries', 'rec_yds', 'receptions', 'rush_rec',
                 'q1_pass_yds', 'q1_rush_yds', 'q1_rec_yds', 'q1_receptions', 'h1_pass_yds', 'h1_rush_yds', 'h1_rec_yds', 'h1_receptions'},
         'nba': {'pts', 'reb', 'ast', 'fg3m', 'pra', 'pr', 'pa', 'ra', 'stl', 'blk', 'sb', 'tov', 'dd', 'td3', 'q1_pts', 'q1_reb', 'q1_ast',
                 'h1_pts', 'h1_reb', 'h1_ast'},
         'nhl': {'sog', 'blocks', 'points', 'assists', 'saves', 'goals'}}
PARTS = {'nfl': ('q1', 'q2', 'q3', 'q4', 'h1', 'h2'), 'nba': ('q1', 'q2', 'q3', 'q4', 'h1', 'h2'), 'nhl': ('p1', 'p2', 'p3')}
RES = {'won': 'W', 'lost': 'L', 'void': 'V', 'push': 'P', 'cancelled': 'V'}


def amer(s):
    try:
        return int(str(s).replace('−', '-').replace('+', '').strip())
    except (TypeError, ValueError):
        return None


def get(url, body=None, dk=False):
    h = {'User-Agent': UA, 'Accept': 'application/json, text/plain, */*', 'Accept-Language': 'en-US,en;q=0.9'}
    if dk:
        h.update({'Origin': 'https://sportsbook.draftkings.com', 'Referer': 'https://sportsbook.draftkings.com/social'})
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h['Content-Type'] = 'application/json'
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=40) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404, 422):
                return None
        except Exception:
            pass
        time.sleep(2 * (i + 1))
    return None


class Ids:
    """the site's games and players, from the live grade files, ESPN's NBA scoreboards and the NHL schedule"""
    def __init__(self, days):
        stamp = int(time.time())
        self.grade = {sp: get(f'{LIVE}{sp}/data/grade.json?t={stamp}') or {'games': {}, 'players': {}} for sp in ('nba', 'nhl', 'nfl')}
        self.extra = {'nba': {}, 'nhl': {}}
        for d in sorted(days):
            for dd in (d - dt.timedelta(days=1), d, d + dt.timedelta(days=1)):
                j = get(f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={dd:%Y%m%d}') or {}
                for e in j.get('events') or []:
                    c = {x['homeAway']: x['team']['abbreviation'] for x in e['competitions'][0]['competitors']}
                    self.extra['nba'][(c['away'], c['home'], e['date'][:10])] = e['id']
            j = get(f'https://api-web.nhle.com/v1/schedule/{d:%Y-%m-%d}') or {}
            for wk in j.get('gameWeek') or []:
                for g in wk.get('games') or []:
                    self.extra['nhl'][(g['awayTeam']['abbrev'], g['homeTeam']['abbrev'], str(g.get('startTimeUTC', ''))[:10])] = str(g['id'])

    def game(self, sp, away, home, start):
        t = dt.datetime.fromisoformat(start.replace('Z', '+00:00')) if start else None
        for gid, g in self.grade[sp]['games'].items():
            if g.get('a') == away and g.get('h') == home:
                k = g.get('k')
                if not t or not k or abs((dt.datetime.fromisoformat(k.replace('Z', '+00:00')) - t).total_seconds()) < 36 * 3600:
                    return gid
        if sp in self.extra and t:
            for dd in (t.date(), t.date() + dt.timedelta(days=1), t.date() - dt.timedelta(days=1)):
                gid = self.extra[sp].get((away, home, dd.isoformat()))
                if gid:
                    return gid
        return None

    def player(self, sp, name, teams):
        P = self.grade[sp]['players']; want = norm(name)
        parts = [w for w in name.replace('.', ' ').split() if w.rstrip('.') not in ('Jr', 'Sr', 'II', 'III', 'IV')]
        last, first = norm(parts[-1]) if parts else '', norm(name)[:1]
        hits = [pid for pid, p in P.items() if norm(p['n']) == want and (not teams or p.get('t') in teams)]
        if not hits:                                       # "Alex Sarr" for "Alexandre Sarr", "K. Connor" for "Kyle Connor"
            def ln(n):
                w = [x for x in str(n).replace('.', ' ').split() if x.rstrip('.') not in ('Jr', 'Sr', 'II', 'III', 'IV')]
                return norm(w[-1]) if w else ''
            hits = [pid for pid, p in P.items() if ln(p['n']) == last and norm(p['n'])[:1] == first and (not teams or p.get('t') in teams)]
        return hits[0] if len(set(hits)) == 1 else None


def team_of(sp, label):
    for nick, ab in sorted(NICK.get(sp, {}).items(), key=lambda kv: -len(kv[0])):
        if label.endswith(nick):
            return ab
    return None


def leg_of(ids, s, sp, gid, away, home):
    off, out = (s.get('offerLabel') or '').strip(), (s.get('outcomeLabel') or '').strip()
    base = {'sport': sp, 'game': gid or '', 'odds': amer(s.get('playedOddsAmerican'))}
    other = dict(base, market='other', label=f'{off}: {out}' if off else out)
    if s.get('status') in RES:
        other['manual'] = RES[s['status']]
    if not gid:
        return other, 'game not found'
    ou = re.match(r'^(Over|Under)\s+([\d.]+)$', out)
    part = None
    for w, p in PARTW.items():
        if w in off:
            part = p
            off = off.replace(f' - {w}', '').replace(f'{w} ', '').replace(w, '').strip()
    off = re.sub(r'\s+O/U$', '', off)
    if part and part not in PARTS[sp] and not any(off.endswith(w) for w, _ in MK.get(sp, [])):
        return other, 'market not on the site'
    head = off.lower()
    if head in ('moneyline', 'money line', 'moneyline 3-way', 'moneyline (3-way)'):
        tm = team_of(sp, out)
        if out.lower() in ('draw', 'tie'):
            return (dict(base, market=f'{part}_ml', side='D', team='') if part else other), None
        return (dict(base, market=f'{part}_ml' if part else 'ml', team=tm) if tm else other), None if tm else 'team not found'
    if head.startswith('total') and ou:
        return dict(base, market=f'{part}_total' if part else 'total', side='O' if ou.group(1) == 'Over' else 'U', line=float(ou.group(2))), None
    sp_ = re.match(r'^(.+?)\s+([+-]\d+(?:\.\d+)?)$', out)
    if (head.startswith('spread') or head.startswith('alternate spread') or head.startswith('puck line') or head.startswith('run line')) and sp_:
        tm = team_of(sp, sp_.group(1))
        return (dict(base, market=f'{part}_spread' if part else 'spread', team=tm, line=float(sp_.group(2))) if tm else other), None if tm else 'team not found'
    for words, (ssp, key) in SCORER.items():                # "Anytime TD Scorer" + "Josh Allen", or "Josh Allen Anytime TD Scorer" + "Yes"
        if ssp == sp and off.endswith(words):
            name = off[: -len(words)].strip() or out
            if out.lower() in ('no', 'not to score'):
                return other, 'a "no" scorer line'
            pid = ids.player(sp, name, {away, home})
            if not pid:
                return other, 'player not found'
            return dict(base, market=key, player=pid, player_name=name, side='Y'), None
    for words, key in MK.get(sp, []):
        if off.endswith(words):
            name = off[: -len(words)].strip()
            pid = ids.player(sp, name, {away, home})
            if not pid:
                return other, 'player not found'
            if part:
                key = f'{part}_{key}'
            if key not in KNOWN[sp]:
                return other, 'market not on the site'
            leg = dict(base, market=key, player=pid, player_name=name)
            if ou:
                leg.update(side='O' if ou.group(1) == 'Over' else 'U', line=float(ou.group(2)))
            elif re.match(r'^\d+\+$', out):
                n = int(out[:-1])
                if key in ('dd', 'td3'):
                    leg['side'] = 'Y'
                else:
                    leg.update(side='O', line=n - 0.5)
            else:
                return other, 'line not read'
            return leg, None
    return other, 'market not known'


def convert(b, ids):
    ev = {e['eventId']: e for e in b.get('events') or []}
    legs, notes = [], []
    for o in b.get('combinationOutcomes') or []:
        e = ev.get(o.get('eventId'), {}); sp = LEAGUE.get(e.get('leagueName'))
        away = team_of(sp, o.get('awayTeamName') or '') if sp else None
        home = team_of(sp, o.get('homeTeamName') or '') if sp else None
        gid = ids.game(sp, away, home, e.get('startDate')) if sp and away and home else None
        for s in (o.get('nestedSGPSelections') or [o]):
            if sp:
                leg, why = leg_of(ids, s, sp, gid, away, home)
            else:
                leg, why = {'sport': 'nfl', 'game': '', 'market': 'other', 'label': f"{s.get('offerLabel', '')}: {s.get('outcomeLabel', '')}",
                            'odds': amer(s.get('playedOddsAmerican'))}, f"{e.get('leagueName') or 'this sport'} isn't on the site"
                if s.get('status') in RES:
                    leg['manual'] = RES[s['status']]
            leg['id'] = f"dk{b['betId']}_{len(legs) + 1}"
            legs.append({k: v for k, v in leg.items() if v is not None})
            if why:
                notes.append(f"{s.get('offerLabel', '')} {s.get('outcomeLabel', '')}".strip() + f' ({why}; marked with DraftKings\' result)')
    kind = {'sgpx': 'SGPx', 'sgp': 'SGP', 'parlay': 'parlay', 'single': 'single', 'straight': 'single'}.get(str(b.get('type')).lower(), str(b.get('type')))
    odds = amer(b.get('originalDisplayOdds')) or amer(((b.get('combinations') or [{}])[0]).get('totalEnterpriseDisplayOdds'))
    boost = [r for r in b.get('rewards') or []]
    usd = float(b.get('stake') or 0)
    bet = {'kind': 'bet', 'id': f"dk{b['betId']}", 'created': str(b.get('placedDate', ''))[:19] + 'Z', 'type': 'parlay' if len(legs) > 1 else 'single',
           'stake': round(usd / UNIT, 3) or 1, 'odds': odds, 'legs': legs,
           'note': f"DraftKings {kind}, ${usd:.2f} ({usd / UNIT:g}u)" + (' with a boost' if boost else '')}
    if len(legs) == 1 and odds is not None:
        legs[0]['odds'] = odds
    return bet, notes


def main():
    post, key, nonce = os.environ.get('POST', ''), os.environ.get('KEY', ''), os.environ.get('NONCE', '')
    assert re.fullmatch(r'[0-9a-f]{20,40}', nonce), 'bad request id'
    result = {}
    UUID = r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
    m = re.search(UUID, post, re.I)
    u = re.search(r'https?://[^\s"<>]+', post)
    if not m and u:                                     # a short share link: follow it to the post
        try:
            with urllib.request.urlopen(urllib.request.Request(u.group(0), headers={'User-Agent': UA}), timeout=30) as r:
                m = re.search(UUID, r.geturl(), re.I) or re.search(r'social/post/' + UUID, r.read(400000).decode('utf-8', 'replace'), re.I)
        except Exception as e:
            print('short link', type(e).__name__)
    if not m:
        result = {'error': "That isn't a DraftKings share link."}
    else:
        d = get('https://api.draftkings.com/comments/feed/post/details.json', {'postKey': m.group(m.lastindex).lower()}, dk=True)
        bets_dk = []
        for pe in ((d or {}).get('post') or {}).get('postEntries') or []:
            props = (pe.get('metadataProperties') or {}).get('properties') or {}
            if props.get('name') == 'betJSON':
                v = props['value']; bets_dk.append(json.loads(base64.b64decode(v + '=' * (-len(v) % 4))))
        if not bets_dk:
            result = {'error': "DraftKings didn't return a bet for that link. It may have been deleted, or DraftKings turned the request away; try again in a minute."}
        else:
            days = {dt.datetime.fromisoformat(e['startDate'].replace('Z', '+00:00')).date() for b in bets_dk for e in b.get('events') or [] if e.get('startDate')}
            ids = Ids(days)
            out, notes = [], []
            for b in bets_dk:
                bet, n = convert(b, ids); out.append(bet); notes += n
            result = {'bets': out, 'notes': notes}
            print('bets', [(b['id'], len(b['legs'])) for b in out], '| unmatched legs', len(notes))
    pub = serialization.load_der_public_key(base64.b64decode(key))
    k = AESGCM.generate_key(256); iv = os.urandom(12)
    ct = AESGCM(k).encrypt(iv, json.dumps(result, separators=(',', ':')).encode(), None)
    wk = pub.encrypt(k, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    os.makedirs('out', exist_ok=True)
    json.dump({'k': base64.b64encode(wk).decode(), 'iv': base64.b64encode(iv).decode(), 'ct': base64.b64encode(ct).decode()}, open(f'out/{nonce}.json', 'w'))
    print('answer written' + (' (error)' if 'error' in result else ''))


if __name__ == '__main__':
    main()
