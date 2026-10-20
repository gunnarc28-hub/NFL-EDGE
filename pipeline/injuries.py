"""Injury status for each team's NEXT game.

Sources, freshest first:
  espn      ESPN's injury feed. Each entry carries ESPN's current status, its outlook for the coming game
            ("fantasy status"), an expected return date and when the entry last changed. It moves within minutes of
            news: IR moves, coach updates, players hurt in a game, game-day inactives.
  official  The NFL's injury report for that game (practice participation, then the game status once the final
            report is out), read from NFL.com on every build. nflverse's copy (updated about once a day) is the fallback.
  roster    nflverse weekly rosters, for reserve-list players neither source mentions.

merge_team() turns one team's context plus its ESPN entries into the list the site shows. The site runs the same
merge in the browser against ESPN's live feed every few minutes (mergeTeamInj in site/index.html), so any change
to the rules here has to be made there too. The two are checked against each other by research/inj_parity.py.
"""
import datetime as dt, html, json, os, re, unicodedata, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (nfl-edge data refresh)'}
PRAC = {'Did Not Participate In Practice': 'DNP', 'Limited Participation in Practice': 'LP', 'Full Participation in Practice': 'FP'}
ESPN_ABBR = {'WSH': 'WAS', 'LAR': 'LA', 'JAC': 'JAX'}
ORDER = {'out': 0, 'doubt': 1, 'risk': 2, 'gtd': 3, 'likely': 4, 'ir': 5, 'ok': 6}
HOUR = 3600 * 1000
_SUFFIX = re.compile(r'\s+(jr|sr|ii|iii|iv|v)\.?$')


def norm(n):
    """Name key shared by every source: accents and suffixes dropped, letters only."""
    s = unicodedata.normalize('NFKD', str(n or '')).encode('ascii', 'ignore').decode().lower().strip()
    return re.sub(r'[^a-z]', '', _SUFFIX.sub('', s))


def alt_key(n):
    """Looser key for nickname mismatches (Gabe/Gabriel Davis): last name + first initial."""
    parts = [p for p in re.split(r'\s+', _SUFFIX.sub('', unicodedata.normalize('NFKD', str(n or '')).encode('ascii', 'ignore').decode().lower().strip())) if p]
    if len(parts) < 2:
        return None
    return re.sub(r'[^a-z]', '', parts[-1]) + '|' + parts[0][:1]


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def ms(iso):
    """Epoch milliseconds for an ISO time (ESPN writes '2026-10-19T23:21Z')."""
    if not iso:
        return None
    try:
        s = str(iso).replace('Z', '+00:00')
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp() * 1000)
    except Exception:
        return None


# ------------------------------------------------------------------ sources
def espn_items(path=None):
    """Every ESPN injury entry, Active ones included (they tell us a player has been cleared).
    [{'team','name','pos','es','fs','ret','date','injury'}]; [] if the feed can't be read."""
    try:
        if path:
            data = json.load(open(path))
        else:
            data = json.loads(_get('https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries'))
    except Exception as e:
        print('ESPN injuries unavailable:', e)
        return []
    return parse_espn(data)


def parse_espn(data, name_to_abbr=None):
    from teams import TEAMS
    n2a = name_to_abbr or {f'{city} {nick}': ab for ab, (city, nick, *_r) in TEAMS.items()}
    out = []
    for team in (data or {}).get('injuries', []) or []:
        t = n2a.get(team.get('displayName') or '')
        for it in team.get('injuries', []) or []:
            try:
                ath = it.get('athlete') or {}
                name = ath.get('displayName') or ath.get('fullName')
                tt = t
                if not tt:
                    ab = (ath.get('team') or {}).get('abbreviation')
                    ab = ESPN_ABBR.get(ab, ab)
                    tt = ab if ab in TEAMS else None
                if not name or not tt:
                    continue
                det = it.get('details') or {}
                out.append({'team': tt, 'name': name, 'pos': (ath.get('position') or {}).get('abbreviation'),
                            'es': str(it.get('status') or ((it.get('type') or {}).get('description') or '')).strip(),
                            'fs': str(((det.get('fantasyStatus') or {}).get('abbreviation')) or '').upper(),
                            'ret': det.get('returnDate'), 'date': it.get('date'),
                            'injury': det.get('type') if det.get('type') not in (None, 'Not Specified', 'Undisclosed', 'Inactive') else None})
            except Exception:
                continue
    return out


def nflcom_report(season, week, nick_to_abbr, path=None):
    """The official report for one week from NFL.com: {team: [row, ...]}, only for teams with a filed report.
    NFL.com shows the latest published week when asked for one it hasn't published, so the week on the page is checked.
    Returns None when the page can't be read or is for another week."""
    try:
        page = open(path).read() if path else _get(f'https://www.nfl.com/injuries/league/{season}/REG{week}')
    except Exception as e:
        print(f'NFL.com injury report (week {week}) unavailable:', e)
        return None
    m = re.search(r'Injuries\s*-\s*WEEK\s*(\d+)', page)
    if not m or int(m.group(1)) != week:
        return None
    out = {}
    for sec in page.split('nfl-o-injury-report__unit')[1:]:
        for chunk in sec.split('d3-o-section-sub-title')[1:]:
            nm = re.search(r'<span>([^<]+)</span>', chunk)
            team = nick_to_abbr.get(html.unescape(nm.group(1)).strip()) if nm else None
            tb = re.search(r'<tbody>(.*?)</tbody>', chunk, re.S)
            if not team or not tb:
                continue
            rows = []
            for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb.group(1), re.S):
                td = [html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', x))).strip()
                      for x in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
                if len(td) < 5 or not td[0]:
                    continue
                rows.append({'name': td[0], 'pos': td[1] or None, 'injury': td[2] or None,
                             'practice': PRAC.get(td[3]) or (td[3] or None), 'gs': td[4] if td[4] in ('Out', 'Doubtful', 'Questionable') else None})
            if rows:
                out[team] = rows
    return out


def nflverse_rows(df, team, week):
    d = df[(df.team == team) & (df.week == week)]
    rows = []
    for _, r in d.iterrows():
        inj = r.practice_primary_injury if isinstance(r.practice_primary_injury, str) else (r.report_primary_injury if isinstance(r.report_primary_injury, str) else None)
        rows.append({'name': r.full_name, 'pos': r.position if isinstance(r.position, str) else None, 'injury': inj,
                     'practice': PRAC.get(r.practice_status), 'gs': r.report_status if r.report_status in ('Out', 'Doubtful', 'Questionable') else None})
    return rows


def report_times(kick_iso):
    """(first practice report, final report) for a game, as epoch ms. Reports land mid-afternoon Eastern:
    Sunday and Monday games report from four days out, the rest from three; the final report (with game statuses)
    comes two days out, or the day before for Thursday games."""
    k = dt.datetime.fromisoformat(kick_iso)
    wd = k.weekday()                       # Monday 0 ... Sunday 6
    day = k.replace(hour=15, minute=0, second=0, microsecond=0)
    first = day - dt.timedelta(days=4 if wd in (6, 0) else 3)
    final = day - dt.timedelta(days=1 if wd == 3 else 2)
    return int(first.timestamp() * 1000), int(final.timestamp() * 1000)


# ------------------------------------------------------------------ the merge (mirrored in site/index.html)
LONG_ES = ('Injured Reserve', 'Suspension', 'Physically Unable', 'Non-Football', 'Reserve')
LONG_FS = ('IR', 'PUP', 'NFI', 'RESERVE', 'SUSP')


def ret_week(ctx, date):
    if not date:
        return None
    d = str(date)[:10]
    for gd, wk in ctx['sched']:
        if gd >= d:
            return wk
    return None


def is_long(e):
    if not e:
        return False
    return any(k in e['es'] for k in LONG_ES) or e['fs'].startswith(LONG_FS)


def long_label(e):
    es, fs = (e or {}).get('es') or '', (e or {}).get('fs') or ''
    if 'Suspension' in es or 'SUS' in fs:
        return 'Suspended'
    if 'Physically Unable' in es or fs.startswith('PUP'):
        return 'On PUP'
    if 'Non-Football' in es or fs.startswith('NFI'):
        return 'On the NFI list'
    if 'Injured Reserve' in es or fs.startswith('IR'):
        return 'On IR'
    return 'On a reserve list'


def espn_cat(e, rw, W):
    """ESPN's read on the coming game: out / doubt / risk / gtd, or None when it doesn't list him as hurt."""
    if not e or e['es'] == 'Active':
        return None
    fs, es = e['fs'], e['es']
    later, soon = rw is not None and rw > W, rw is not None and rw <= W
    if fs == 'INACTIVE':
        return 'out' if later else None        # a game-day scratch, usually not an injury
    if later:
        return 'out'
    if fs == 'OUT' or (not fs and es == 'Out'):
        return 'risk' if soon else 'out'       # out now, but expected back by the game
    if fs == 'DOUBTFUL' or es == 'Doubtful':
        return 'doubt'
    return 'gtd'


def _ge(a, b):
    return a is not None and b is not None and a >= b


def _prac_text(prac, gs):
    if gs == 'Questionable':
        return {'FP': 'Questionable, practiced fully', 'LP': 'Questionable, limited in practice',
                'DNP': 'Questionable, did not practice'}.get(prac, 'Questionable')
    return {'FP': 'Full practice, expected to play', 'LP': 'Limited in practice, game-time call',
            'DNP': 'Did not practice, in doubt'}.get(prac, 'On the injury report')


def _decide(ctx, o, e, in_res, now):
    """(level, outlook) for one player, or None when he shouldn't be listed."""
    W, K, t0, t1 = ctx['wk'], ctx['k'], ctx['t0'], ctx['t1']
    es, fs = (e or {}).get('es') or '', (e or {}).get('fs') or ''
    ed = ms((e or {}).get('date'))
    rw = ret_week(ctx, (e or {}).get('ret')) if e else None
    long = is_long(e) or (e is None and in_res)
    lbl = long_label(e) if e else 'On a reserve list'

    # game day: inactives and actives are announced 90 minutes before kickoff, and ESPN posts them right away
    if _ge(ed, K - 3 * HOUR if K is not None else None) and not long:
        if es == 'Out' or fs in ('OUT', 'INACTIVE'):
            return 'out', f'Inactive for Week {W}' if fs == 'INACTIVE' else f'Ruled out for Week {W}'
        if es == 'Active' and o and o['gs'] in ('Questionable', 'Doubtful'):
            return 'ok', f'Active for Week {W}, cleared to play'

    if long:
        if o and o['practice'] in ('FP', 'LP'):
            return ('likely' if o['practice'] == 'FP' else 'gtd'), f'Back at practice from {"IR" if lbl == "On IR" else "a reserve list"} ({"full" if o["practice"] == "FP" else "limited"}), could be activated'
        if rw is not None and rw > W:
            return 'ir', f'{lbl}, expected back Week {rw}'
        if rw is not None and rw == W:
            return 'ir', f'{lbl}, could return Week {W}'
        return 'ir', lbl

    cat = espn_cat(e, rw, W)
    if o:
        prac, gs, why = o['practice'], o['gs'], (o.get('injury') or '').lower()
        rep = ctx['rep'] or []
        final_out = any(r['gs'] for r in rep) or _ge(now, t1 + 2 * HOUR if t1 is not None else None)
        if gs == 'Out':
            return 'out', f'Ruled out for Week {W}'
        if _ge(ed, t1) and es != 'Active' and (fs in ('OUT', 'INACTIVE') or (es == 'Out' and fs not in ('QUESTIONABLE', 'DOUBTFUL'))):
            return 'out', f'Downgraded to out for Week {W}'
        if gs == 'Doubtful':
            return 'doubt', f'Doubtful for Week {W}' + ({'DNP': ', did not practice', 'LP': ', limited in practice'}.get(prac, ''))
        if 'resting player' in why:
            return 'likely', 'Rest day, not injured'
        if not gs and not final_out:
            if cat == 'out' and prac not in ('FP', 'LP'):
                return 'out', f'Expected to miss Week {W}' + (f', back around Week {rw}' if rw and rw > W else '')
            if cat == 'doubt' and prac not in ('FP', 'LP'):
                return 'doubt', f'Doubtful for Week {W}'
        if 'personal matter' in why and gs != 'Questionable':
            return 'gtd', 'Personal matter'
        if not gs and final_out:
            return 'likely', 'No game status, expected to play'
        lvl = {'FP': 'likely', 'LP': 'gtd', 'DNP': 'risk'}.get(prac, 'gtd')
        return lvl, _prac_text(prac, gs)

    if cat is None:
        return None
    if ctx['rep'] is not None and not _ge(ed, t0):
        return None     # the team filed this week's report without him and ESPN has nothing newer
    if cat == 'out':
        return 'out', f'Expected to miss Week {W}' + (f', back around Week {rw}' if rw and rw > W else '')
    if cat == 'doubt':
        return 'doubt', f'Doubtful for Week {W}'
    if cat == 'risk':
        return 'risk', f'In doubt for Week {W}, could be back by then'
    return 'gtd', f'Questionable for Week {W}'


def merge_team(ctx, items, now=None):
    """The injury list for one team. ctx: wk, k, t0, t1 (epoch ms), rep (official rows for that week, or None
    before the team files one), res ([name, position] on a reserve list), key/skill (name keys), sched ([[date, week], ...]).
    items: this team's ESPN entries. now: epoch ms."""
    by_n, by_alt = {}, {}
    for e in items:
        k = norm(e['name'])
        if k in by_n and (ms(by_n[k].get('date')) or 0) >= (ms(e.get('date')) or 0):
            continue
        by_n[k] = e
    for k, e in by_n.items():
        a = alt_key(e['name'])
        if a:
            by_alt[a] = None if a in by_alt else k        # only use the loose key when it's unambiguous
    used, out = set(), []
    key, skill, res = set(ctx['key']), set(ctx['skill']), {norm(r[0]): r for r in ctx['res']}

    def emit(name, pos, injury, o, e, k):
        r = _decide(ctx, o, e, k in res, now)
        if not r:
            return
        lvl, ol = r
        rw = ret_week(ctx, e.get('ret')) if e else None
        out.append({'name': name, 'pos': pos, 'injury': injury, 'status': o['gs'] if o else None,
                    'practice': o['practice'] if o else None, 'level': lvl, 'outlook': ol, 'ret_wk': rw,
                    'key': k in key, 'skill': k in skill, 'upd': (e or {}).get('date') if e and e['es'] != 'Active' else None,
                    'src': 'report' if o else ('espn' if e else 'roster')})

    for o in ctx['rep'] or []:
        k = norm(o['name'])
        e = by_n.get(k)
        if e is None:
            ek = by_alt.get(alt_key(o['name']))      # ESPN's key for the same player under another first name
            if ek and ek not in used:
                e = by_n[ek]
                used.add(ek)
        used.add(k)
        inj = o.get('injury') or ''
        inj = re.sub(r'^Not injury related\s*-\s*', '', inj, flags=re.I) or (e or {}).get('injury')
        emit(o['name'], o.get('pos') or (e or {}).get('pos'), inj or None, o, e, k)
    for k, e in by_n.items():
        if k in used or e['es'] == 'Active':
            continue
        used.add(k)
        emit(e['name'], e.get('pos'), e.get('injury'), None, e, k)
    for k, r in res.items():
        if k in used or k in by_n:
            continue
        emit(r[0], r[1] or None, None, None, None, k)
    out.sort(key=lambda x: (not x['key'], ORDER.get(x['level'], 9), x['name']))
    return out
