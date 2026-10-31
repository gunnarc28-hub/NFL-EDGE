"""Research probe (GitHub Actions only): the pictures DraftKings attaches to shared bets (og:image), fetched the way link
previews fetch them, to see whether a bet can be read from its share link. Writes probe_out/raw/."""
import os, urllib.request, urllib.error
OUT = 'probe_out/raw'; os.makedirs(OUT, exist_ok=True)
IMGS = {'post_6ad98993': 'https://sportsbook.draftkings.com/comments/seo/assets/05acb19e-6743-4107-bbcb-c3119307096d.639290567258937979.1.png',
        'post_a1f8cfd8': 'https://sportsbook.draftkings.com/comments/seo/assets/05acb19e-6743-4107-bbcb-c3119307096d.639290567790744832.1.png'}
UAS = {'twitter': 'Twitterbot/1.0', 'facebook': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
       'slack': 'Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)', 'imessage': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1 facebookexternalhit/1.1 Facebot Twitterbot/1.0',
       'safari': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'}
log = []
for name, url in IMGS.items():
    for ua_name, ua in UAS.items():
        try:
            req = urllib.request.Request(url, headers={'User-Agent': ua, 'Accept': 'image/avif,image/webp,image/png,image/*;q=0.8,*/*;q=0.5'})
            with urllib.request.urlopen(req, timeout=30) as r:
                b = r.read()
                ok = b[:8] == b'\x89PNG\r\n\x1a\n' or b[:3] == b'\xff\xd8\xff' or b[:4] == b'RIFF'
                log.append(f'{name} {ua_name} {r.status} {r.headers.get("content-type")} {len(b)} bytes image={ok}')
                if ok:
                    open(f'{OUT}/{name}.png', 'wb').write(b)
                    break
        except urllib.error.HTTPError as e:
            log.append(f'{name} {ua_name} HTTP {e.code}')
        except Exception as e:
            log.append(f'{name} {ua_name} error {e!r}'[:200])
open(f'{OUT}/log.txt', 'w').write('\n'.join(log))
print('\n'.join(log))
