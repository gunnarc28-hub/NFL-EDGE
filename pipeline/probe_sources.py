"""Look at full ESPN BET prop items to find which side each one is."""
import json, os, urllib.request
os.makedirs('probe_out/props_raw', exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (sports-edge research)'}
def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r: return r.read()
    except Exception as e: return None
for lg, path, evs in (('nba', 'basketball/leagues/nba', ['401704627', '401705127', '401584923']), ('nhl', 'hockey/leagues/nhl', ['401688304', '401559700'])):
    for ev in evs:
        b = get(f'https://sports.core.api.espn.com/v2/sports/{path}/events/{ev}/competitions/{ev}/odds/58/propBets?limit=1000')
        if b: open(f'probe_out/props_raw/{lg}_{ev}_58.json', 'wb').write(b)
        b = get(f'https://sports.core.api.espn.com/v2/sports/{path}/events/{ev}/competitions/{ev}/odds/58')
        if b: open(f'probe_out/props_raw/{lg}_{ev}_58_odds.json', 'wb').write(b)
        print(f'::notice title={lg} {ev}::{len(b) if b else 0}')
