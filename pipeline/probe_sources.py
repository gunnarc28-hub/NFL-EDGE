"""Research probe (GitHub Actions only): ask DraftKings' comments service for two shared posts the way its social pages do,
and record whether another site could make the same request from a browser (CORS). Writes probe_out/raw/."""
import os, re, json, urllib.request, urllib.error
OUT = 'probe_out/raw'; os.makedirs(OUT, exist_ok=True)
POSTS = ['6ad98993-fa8f-4113-a07b-5cdc3afb0c47', 'a1f8cfd8-b786-47dc-b0f6-cf4e1c97e584']
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'
ORIGIN = 'https://gunnarc28-hub.github.io'
log = []


def req(url, method='GET', body=None, origin=None):
    h = {'User-Agent': UA, 'Accept': 'application/json, text/plain, */*', 'Accept-Language': 'en-US,en;q=0.9'}
    if origin:
        h['Origin'] = origin; h['Referer'] = origin + '/'
    else:
        h['Origin'] = 'https://sportsbook.draftkings.com'; h['Referer'] = 'https://sportsbook.draftkings.com/social'
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h['Content-Type'] = 'application/json'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        try:
            b = e.read()
        except Exception:
            b = b''
        return e.code, dict(e.headers or {}), b
    except Exception as e:
        return 0, {}, repr(e).encode()[:200]


# how the social app calls getPostDetails / postPublic
st, h, b = req('https://sportsbook.draftkings.com/social-assets/app.js')
js = b.decode('utf8', 'replace')
ctx = []
for key in ('getPostDetails(', 'getPostDetails)', '.getPostDetails', 'postPublic(', '.postPublic', 'post/public.json', 'postKey:'):
    for m in list(re.finditer(re.escape(key), js))[:3]:
        ctx.append(f'== {key}\n' + js[max(0, m.start() - 700): m.start() + 500])
open(f'{OUT}/calls.txt', 'w').write('\n\n'.join(ctx))
hosts = ['https://api.draftkings.com/comments/v1', 'https://api.draftkings.com/comments', 'https://sportsbook.draftkings.com/comments/v1']
for pid in POSTS:
    for host in hosts:
        for path, method, body in [(f'/feed/post/details.json?postKey={pid}', 'GET', None), ('/feed/post/details.json', 'POST', {'postKey': pid}),
                                   (f'/post/public.json?postKey={pid}', 'GET', None), ('/post/public.json', 'POST', {'postKey': pid})]:
            for origin in (None, ORIGIN):
                st, h, b = req(host + path, method, body, origin)
                acao = h.get('Access-Control-Allow-Origin') or h.get('access-control-allow-origin')
                ct = h.get('Content-Type') or h.get('content-type') or ''
                log.append(f'{st} {method} {host}{path} origin={"site" if origin else "dk"} acao={acao} {ct} {len(b)}')
                if st == 200 and b[:1] in (b'{', b'['):
                    fn = f'{OUT}/{pid[:8]}_{len(log):03d}.json'; open(fn, 'wb').write(b)
open(f'{OUT}/log.txt', 'w').write('\n'.join(log))
print('\n'.join(log))
