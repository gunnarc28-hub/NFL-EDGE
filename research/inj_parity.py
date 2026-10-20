"""Checks that the page's live injury merge (site/index.html, between the inj-merge markers) gives exactly the same
answers as the build's (pipeline/injuries.py), on real feeds and on made-up timings that exercise every rule.

    python research/inj_parity.py ESPN_JSON NFLCOM_HTML [DATA_JSON]

ESPN_JSON    a saved copy of https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries
NFLCOM_HTML  a saved NFL.com weekly injury report page (https://www.nfl.com/injuries/league/<season>/REG<week>)
DATA_JSON    the built site/data/data.json (default), for team contexts
Needs Node.js. Exits non-zero on any difference."""
import json, os, random, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))
import injuries as injm          # noqa: E402
from teams import TEAMS           # noqa: E402

espn_path, page_path = sys.argv[1], sys.argv[2]
data = json.load(open(sys.argv[3] if len(sys.argv) > 3 else os.path.join(ROOT, 'site', 'data', 'data.json')))
raw = json.load(open(espn_path))
nick2ab = {nick: ab for ab, (city, nick, *_r) in TEAMS.items()}
m = re.search(r'Injuries\s*-\s*WEEK\s*(\d+)', open(page_path).read())
rep_week = int(m.group(1))
report = injm.nflcom_report(int(data['meta']['season']), rep_week, nick2ab, path=page_path) or {}
items = injm.parse_espn(raw)
by_team = {}
for e in items:
    by_team.setdefault(e['team'], []).append(e)

# scenarios: the real contexts, then the same teams with an official report in place (as filed, and stripped back to a
# midweek report with no game statuses), kickoffs moved around the ESPN timestamps, and some ESPN entries flipped,
# so the game-day, final-report, downgrade and new-injury rules all fire
rng = random.Random(7)
H = 3600 * 1000
cases = []
for t, ctx in sorted(data['inj_ctx'].items()):
    cases.append({'team': t, 'ctx': ctx, 'now': injm.ms(data['meta']['asof']), 'items': by_team.get(t, [])})
    dates = sorted(x for x in (injm.ms(e['date']) for e in by_team.get(t, [])) if x)
    for i in range(6):
        c = dict(ctx)
        base = report.get(t)
        c['rep'] = base if i in (0, 1) else ([dict(r, gs=None) for r in base] if base and i in (2, 3) else ctx['rep'])
        its = [dict(e) for e in by_team.get(t, [])]
        if i % 2:
            for e in its:
                if rng.random() < 0.3:
                    e['fs'], e['es'] = rng.choice([('OUT', 'Out'), ('INACTIVE', 'Out'), ('DOUBTFUL', 'Doubtful'), ('', 'Out'), ('', 'Active')])
        if dates:
            pivot = dates[rng.randrange(len(dates))]
            k = pivot + rng.choice([-1, 1, 2, 30, 50, 80]) * H
            c['k'], c['t0'], c['t1'] = k, k - rng.choice([70, 94]) * H, k - rng.choice([22, 46, 52]) * H
            c['wk'] = rng.choice([ctx['wk'], ctx['wk'] - 1, ctx['wk'] + 1])
        now = (c['t1'] or 0) + (rng.choice([-30, -10]) if i in (2, 3) else rng.choice([-5, 1, 3])) * H
        cases.append({'team': t, 'ctx': c, 'now': now, 'items': its})

py = [injm.merge_team(c['ctx'], c['items'], c['now']) for c in cases]
names = sorted({e['name'] for e in items} | {r['name'] for rows in report.values() for r in rows} |
               {r[0] for ctx in data['inj_ctx'].values() for r in ctx['res']} |
               {'Patrick Mahomes II', 'Marvin Harrison Jr.', 'Kenneth Walker III', 'Andrés Borregales', "D'Andre Swift", 'A.J. Brown', 'Odell Beckham Jr', 'Iisakki Ii'})
py_norm = [[injm.norm(n), injm.alt_key(n)] for n in names]

html = open(os.path.join(ROOT, 'site', 'index.html')).read()
block = html[html.index('/* inj-merge:start */'):html.index('/* inj-merge:end */')]
name2ab = {f"{v['city']} {v['nick']}": k for k, v in data['teams'].items()}
with tempfile.TemporaryDirectory() as td:
    inp = os.path.join(td, 'in.json')
    json.dump({'raw': raw, 'cases': cases, 'names': names, 'name2ab': name2ab, 'valid': sorted(TEAMS)}, open(inp, 'w'))
    js = os.path.join(td, 'run.js')
    open(js, 'w').write(block + """
const fs = require('fs');
const I = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const valid = new Set(I.valid);
const items = parseEspnInj(I.raw, I.name2ab, {WSH: 'WAS', LAR: 'LA', JAC: 'JAX'}, ab => valid.has(ab));
process.stdout.write(JSON.stringify({items, out: I.cases.map(c => mergeTeamInj(c.ctx, c.items, c.now)),
  norm: I.names.map(n => [injNorm(n), injAlt(n)])}));
""")
    res = json.loads(subprocess.run(['node', js, inp], capture_output=True, text=True, check=True).stdout)

bad = 0
if res['items'] != items:
    bad += 1
    print('ESPN parsing differs:', next((a, b) for a, b in zip(items, res['items']) if a != b) if len(items) == len(res['items']) else (len(items), len(res['items'])))
for n, a, b in zip(names, py_norm, res['norm']):
    if a != b:
        bad += 1
        print('name key differs:', n, a, b)
for c, a, b in zip(cases, py, res['out']):
    if a != b:
        bad += 1
        if bad <= 5:
            print('merge differs for', c['team'], json.dumps(c['ctx'])[:200])
            for x, y in zip(a, b):
                if x != y:
                    print('  py', x, '\n  js', y)
                    break
            if len(a) != len(b):
                print('  lengths', len(a), len(b))
levels, rules = {}, {}
for lst in py:
    for x in lst:
        levels[x['level']] = levels.get(x['level'], 0) + 1
        r = re.sub(r'\d+', 'N', x['outlook'])
        rules[r] = rules.get(r, 0) + 1
print(f'{len(cases)} scenarios, {len(items)} ESPN entries, {len(names)} names, levels {levels}')
print('rules hit:', '; '.join(f'{k} ({v})' for k, v in sorted(rules.items(), key=lambda kv: -kv[1])))
print('parity OK' if not bad else f'{bad} differences')
sys.exit(1 if bad else 0)
