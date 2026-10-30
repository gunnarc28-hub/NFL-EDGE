"""Research probe (GitHub Actions only): what a DraftKings share link (sportsbook.draftkings.com/social/post/<id>) loads
in a real browser: every network request, its status and CORS header, and the bodies of JSON responses, to find where
the bet's selections come from and whether a web page elsewhere could read them. Writes probe_out/raw/."""
import json, os, asyncio
from playwright.async_api import async_playwright
OUT = 'probe_out/raw'; os.makedirs(OUT, exist_ok=True)
POST = 'https://sportsbook.draftkings.com/social/post/e05b606f-856b-4ec8-a9e0-59c42e1e0c82?slipAdd'
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'


async def main():
    log = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(user_agent=UA, viewport={'width': 390, 'height': 844}, locale='en-US', timezone_id='America/Denver')
        pg = await ctx.new_page()

        async def on_resp(r):
            try:
                h = await r.all_headers()
            except Exception:
                h = {}
            e = {'url': r.url, 'status': r.status, 'type': r.request.resource_type, 'ctype': h.get('content-type', ''),
                 'acao': h.get('access-control-allow-origin'), 'method': r.request.method}
            if 'json' in e['ctype'] or r.request.resource_type in ('xhr', 'fetch'):
                try:
                    body = await r.text()
                    e['len'] = len(body)
                    if any(k in body.lower() for k in ('selection', 'outcome', 'leg', 'market', 'odds', 'slip', 'wager')):
                        fn = f'resp_{len(log):03d}.txt'; open(f'{OUT}/{fn}', 'w').write(body[:400000]); e['saved'] = fn
                except Exception as ex:
                    e['err'] = repr(ex)[:120]
            log.append(e)
        pg.on('response', lambda r: asyncio.ensure_future(on_resp(r)))
        try:
            await pg.goto(POST, wait_until='networkidle', timeout=60000)
        except Exception as ex:
            log.append({'goto_error': repr(ex)[:300]})
        await pg.wait_for_timeout(6000)
        open(f'{OUT}/page.html', 'w').write(await pg.content())
        await pg.screenshot(path=f'{OUT}/page.png', full_page=True)
        open(f'{OUT}/page_text.txt', 'w').write(await pg.inner_text('body') if await pg.locator('body').count() else '')
        await b.close()
    json.dump(log, open(f'{OUT}/network.json', 'w'), indent=1)
    print(len(log), 'responses;', sum(1 for e in log if e.get('saved')), 'saved')

asyncio.run(main())
