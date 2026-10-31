"""Research probe (GitHub Actions only): a DraftKings share page fetched as Safari would, its scripts, and every address
in them that looks like the social API, to find where a shared bet's legs come from. Writes probe_out/raw/."""
import os, re, json, urllib.request, urllib.error
OUT = 'probe_out/raw'; os.makedirs(OUT, exist_ok=True)
POST_ID = '6ad98993-fa8f-4113-a07b-5cdc3afb0c47'
PAGE = f'https://sportsbook.draftkings.com/social/post/{POST_ID}?slipAdd'
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'
H = {'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.9'}
log = []


def get(url, accept=None):
    h = dict(H)
    if accept:
        h['Accept'] = accept
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
            return r.status, r.headers.get('content-type', ''), r.read()
    except urllib.error.HTTPError as e:
        return e.code, '', b''
    except Exception as e:
        return 0, repr(e)[:120], b''


st, ct, body = get(PAGE)
log.append(f'page {st} {ct} {len(body)}')
html = body.decode('utf8', 'replace')
open(f'{OUT}/page.html', 'w').write(html)
srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
log.append('scripts: ' + json.dumps(srcs))
found = set()
for s in srcs[:40]:
    u = s if s.startswith('http') else 'https://sportsbook.draftkings.com' + (s if s.startswith('/') else '/' + s)
    st, ct, b = get(u, accept='*/*')
    js = b.decode('utf8', 'replace')
    log.append(f'script {st} {len(b)} {u[:140]}')
    for m in re.finditer(r'["\'`]((?:https?:)?//[a-z0-9.\-]*draftkings[a-z0-9.\-]*\.com[^"\'`\s]{0,160}|/[a-z0-9\-_/{}.$]*(?:social|post|bet|slip|share)[a-z0-9\-_/{}.$]*)["\'`]', js, re.I):
        v = m.group(1)
        if any(k in v.lower() for k in ('social', 'post', 'share', 'slip')):
            found.add(v)
open(f'{OUT}/endpoints.txt', 'w').write('\n'.join(sorted(found)))
# try the obvious shapes of a post API
for u in [f'https://sportsbook.draftkings.com/social/api/posts/{POST_ID}', f'https://sportsbook.draftkings.com/api/social/v1/posts/{POST_ID}',
          f'https://social.draftkings.com/api/v1/posts/{POST_ID}', f'https://api.draftkings.com/social/v1/posts/{POST_ID}',
          f'https://sportsbook-nash.draftkings.com/api/social/v1/posts/{POST_ID}']:
    st, ct, b = get(u, accept='application/json')
    log.append(f'try {st} {ct} {len(b)} {u}')
    if st == 200 and b:
        open(f'{OUT}/post_{len(log)}.json', 'wb').write(b)
open(f'{OUT}/log.txt', 'w').write('\n'.join(log))
print('\n'.join(log)); print(len(found), 'candidate endpoints')
