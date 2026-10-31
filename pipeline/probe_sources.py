"""Research probe (GitHub Actions only): how DraftKings' social pages ask for a shared bet. Saves the code around the post
addresses in the social scripts, then tries the likely requests for two shared posts. Writes probe_out/raw/."""
import os, re, json, urllib.request, urllib.error
OUT = 'probe_out/raw'; os.makedirs(OUT, exist_ok=True)
POSTS = ['6ad98993-fa8f-4113-a07b-5cdc3afb0c47', 'a1f8cfd8-b786-47dc-b0f6-cf4e1c97e584']
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'
log = []


def get(url, accept='*/*', extra=None):
    h = {'User-Agent': UA, 'Accept': accept, 'Accept-Language': 'en-US,en;q=0.9', 'Referer': 'https://sportsbook.draftkings.com/social'}
    h.update(extra or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
            return r.status, r.headers.get('content-type', ''), r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, '', e.read()[:2000] if hasattr(e, 'read') else b'', {}
    except Exception as e:
        return 0, repr(e)[:120], b'', {}


ctx = []
for s in ('https://sportsbook.draftkings.com/assets/social.f87f492b85014e986915.js', 'https://sportsbook.draftkings.com/social-assets/app.js'):
    st, ct, b, _ = get(s)
    js = b.decode('utf8', 'replace')
    log.append(f'script {st} {len(b)} {s}')
    for key in ('details.json', 'public.json', 'lookup-bet', 'socialweb', 'social/v1', 'post.json', 'apiUrl', 'socialApiUrl', 'SOCIAL_API', 'baseURL', 'baseUrl'):
        for m in list(re.finditer(re.escape(key), js))[:4]:
            ctx.append(f'== {s.split("/")[-1]} :: {key}\n' + js[max(0, m.start() - 600): m.start() + 400])
open(f'{OUT}/contexts.txt', 'w').write('\n\n'.join(ctx))
for pid in POSTS:
    for u in [f'https://sportsbook.draftkings.com/socialweb/v1/feed/post/details.json?postId={pid}',
              f'https://sportsbook.draftkings.com/socialweb/feed/post/details.json?postId={pid}',
              f'https://api.draftkings.com/social/v1/feed/post/details.json?postId={pid}',
              f'https://api.draftkings.com/social/v1/post/public.json?postId={pid}',
              f'https://api.draftkings.com/social/v1/post.json?postId={pid}',
              f'https://sportsbook.draftkings.com/social/v1/post/public.json?postId={pid}',
              f'https://sportsbook.draftkings.com/social/v1/feed/post/details.json?postId={pid}']:
        st, ct, b, h = get(u, accept='application/json')
        log.append(f'try {st} {ct} {len(b)} acao={h.get("Access-Control-Allow-Origin") or h.get("access-control-allow-origin")} {u}')
        if st == 200 and b and 'json' in ct:
            open(f'{OUT}/{pid[:8]}_{len(log)}.json', 'wb').write(b)
open(f'{OUT}/log.txt', 'w').write('\n'.join(log))
print('\n'.join(log))
