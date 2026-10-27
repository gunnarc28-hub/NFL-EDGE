"""Open the live site in a headless browser and click through every page and tab, the way a phone would.

Prints a GitHub Actions notice per page with what it found, and a warning for any script error or empty section.
Run after a deploy:  python pipeline/check_site.py https://gunnarc28-hub.github.io/NFL-EDGE/
"""
import sys, asyncio
from playwright.async_api import async_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'https://gunnarc28-hub.github.io/NFL-EDGE/').rstrip('/') + '/'
PAGES = {
    'home': ('', ['home', 'picks']),
    'nfl': ('nfl/', ['week', 'props', 'model', 'hc', 'ls', 'trends', 'picks', 'tips', 'matters', 'teams']),
    'nba': ('nba/', ['games', 'props', 'model', 'hc', 'ls', 'trends', 'picks', 'tips', 'matters', 'teams']),
    'nhl': ('nhl/', ['games', 'props', 'model', 'hc', 'ls', 'trends', 'picks', 'tips', 'matters', 'teams']),
}


def gh(level, title, msg):
    msg = str(msg).replace('%', '%25').replace('\r', '').replace('\n', '%0A')
    print(f'::{level} title={title}::{msg}', flush=True)


async def check(browser, name, path, tabs):
    # an iPhone's Safari, so sites that turn away headless browsers answer as they would a real visitor
    ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1'
    ctx = await browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, has_touch=True, is_mobile=True, user_agent=ua)
    pg = await ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append('error: ' + str(e)))
    pg.on('console', lambda m: errs.append('console: ' + m.text) if m.type == 'error' and 'Failed to load resource' not in m.text and 'net::' not in m.text else None)
    notes, warn = [], []
    try:
        await pg.goto(BASE + path, wait_until='networkidle', timeout=60000)
        await pg.wait_for_timeout(1500)
        for t in tabs:
            tab = pg.locator(f'.tab[data-view="{t}"]')
            if not await tab.count():
                warn.append(f'no {t} tab'); continue
            await tab.first.click(); await pg.wait_for_timeout(500)
            view = pg.locator(f'#v-{t}')
            txt = (await view.inner_text()) if await view.count() else ''
            wide = await pg.evaluate('document.documentElement.scrollWidth > document.documentElement.clientWidth + 1')
            if len(txt.strip()) < 40:
                warn.append(f'{t} looks empty')
            if wide:
                warn.append(f'{t} scrolls sideways')
            notes.append(f'{t} {len(txt)}')
        if name != 'home':
            first = 'week' if name == 'nfl' else 'games'
            await pg.locator(f'.tab[data-view="{first}"]').first.click(); await pg.wait_for_timeout(400)
            n_games = await pg.locator('.game').count()
            notes.append(f'{n_games} game cards')
            if name != 'nfl' and n_games:
                g = pg.locator('.game').first
                if await g.locator('.g-sum').count():
                    await g.locator('.g-sum').click(); await pg.wait_for_timeout(200)
                more = g.locator('[data-more]')
                if await more.count():
                    await more.click(); await pg.wait_for_timeout(300)
                    for dt in ('inj', 'props', 'trends', 'why'):
                        b = g.locator(f'[data-dtab="{dt}"]')
                        if await b.count():
                            await b.click(); await pg.wait_for_timeout(200)
            # a chart from the first high-chance card
            await pg.locator('.tab[data-view="hc"]').first.click(); await pg.wait_for_timeout(400)
            c = pg.locator('#v-hc .hc-chart, #v-hc [data-chart]').first
            if await c.count():
                await c.click(); await pg.wait_for_timeout(1500)
                sheet = pg.locator('#csheet')
                if await sheet.count() and await sheet.is_visible():
                    notes.append('chart ok' if 'Close' in (await sheet.inner_text()) else 'chart empty')
                    close = pg.locator('#cs-close, [data-cclose]').first
                    if await close.count():
                        await close.click(); await pg.wait_for_timeout(200)
    except Exception as e:  # noqa: BLE001
        warn.append(f'could not finish: {e}')
    errs = list(dict.fromkeys(errs))
    if errs:
        gh('warning', f'{name.upper()} page script errors', '\n'.join(errs[:8]))
    if warn:
        gh('warning', f'{name.upper()} page', '; '.join(warn))
    gh('notice', f'{name.upper()} page', ', '.join(notes) + (f' | {len(errs)} script errors' if errs else ' | no script errors'))
    await ctx.close()


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for name, (path, tabs) in PAGES.items():
            await check(browser, name, path, tabs)
        await browser.close()

asyncio.run(main())
