"""ESPN's public JSON feeds: league-wide injuries (status + expected return) and the live scoreboard.
Every function fails soft: on any network or shape problem it returns an empty result and the build carries on."""
import json, re, urllib.request
from teams import TEAMS

UA = {'User-Agent': 'Mozilla/5.0 (nfl-edge data refresh)'}
NAME_TO_ABBR = {f'{city} {nick}': abbr for abbr, (city, nick, *_rest) in TEAMS.items()}
ESPN_ABBR = {'WSH': 'WAS', 'LAR': 'LA', 'JAC': 'JAX'}


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def team_abbr(obj):
    """Map an ESPN team object (or display name) to nflverse abbreviations."""
    if isinstance(obj, str):
        return NAME_TO_ABBR.get(obj)
    if not isinstance(obj, dict):
        return None
    name = obj.get('displayName') or ''
    if name in NAME_TO_ABBR:
        return NAME_TO_ABBR[name]
    ab = obj.get('abbreviation')
    if ab:
        ab = ESPN_ABBR.get(ab, ab)
        return ab if ab in TEAMS else None
    return None


def norm(n):
    return re.sub(r'[^a-z]', '', str(n).lower().replace(' jr.', '').replace(' sr.', '').replace(' iii', '').replace(' ii', ''))


def injuries():
    """{'TEAM|normname': {'status','return_date','injury','pos','name'}} for players not listed as Active."""
    out = {}
    try:
        data = _get('https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries')
    except Exception as e:
        print('ESPN injuries unavailable:', e)
        return out
    for team in data.get('injuries', []) or []:
        t = team_abbr(team.get('displayName', '')) or team_abbr(team)
        for it in team.get('injuries', []) or []:
            try:
                ath = it.get('athlete') or {}
                name = ath.get('displayName') or ath.get('fullName')
                if not name:
                    continue
                tt = t or team_abbr(ath.get('team') or {})
                if not tt:
                    continue
                status = it.get('status') or ((it.get('type') or {}).get('description') or '')
                if str(status).lower() == 'active':
                    continue
                det = it.get('details') or {}
                out[tt + '|' + norm(name)] = {
                    'name': name, 'team': tt,
                    'pos': ((ath.get('position') or {}).get('abbreviation')),
                    'status': str(status).title() if status else None,
                    'injury': det.get('type'),
                    'return_date': det.get('returnDate'),
                    'date': it.get('date'),
                }
            except Exception:
                continue
    print('ESPN injuries:', len(out))
    return out


def scoreboard():
    """Current-week games keyed by (away, home): state pre/in/post, scores, clock text, current odds."""
    out = {}
    try:
        data = _get('https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard')
    except Exception as e:
        print('ESPN scoreboard unavailable:', e)
        return out
    for ev in data.get('events', []) or []:
        try:
            comp = (ev.get('competitions') or [{}])[0]
            teams = {c.get('homeAway'): c for c in comp.get('competitors', [])}
            h, a = teams.get('home'), teams.get('away')
            if not h or not a:
                continue
            ha, aa = team_abbr(h.get('team') or {}), team_abbr(a.get('team') or {})
            if not ha or not aa:
                continue
            st = ((comp.get('status') or ev.get('status') or {}).get('type') or {})
            odds = (comp.get('odds') or [{}])[0] if comp.get('odds') else {}
            def score(c):
                try:
                    return int(float(c.get('score')))
                except Exception:
                    return None
            out[(aa, ha)] = {'state': st.get('state'), 'completed': bool(st.get('completed')),
                             'detail': st.get('shortDetail') or st.get('detail'),
                             'home_score': score(h), 'away_score': score(a),
                             'odds_detail': odds.get('details'), 'over_under': odds.get('overUnder')}
        except Exception:
            continue
    print('ESPN scoreboard games:', len(out))
    return out
