"""Trial run of the NBA and NHL builds against live data; copies their output to probe_out/."""
import subprocess, shutil, os, sys, time
os.makedirs('probe_out', exist_ok=True)
for sp in ('nba', 'nhl'):
    t0 = time.time()
    r = subprocess.run([sys.executable, f'pipeline/{sp}.py'], capture_output=True, text=True)
    log = (r.stdout + '\n' + r.stderr)
    open(f'probe_out/{sp}_build.log', 'w').write(log)
    print(f'::notice title={sp} build::exit {r.returncode} in {time.time() - t0:.0f}s | ' + ' | '.join(l for l in log.splitlines() if l.strip())[-2500:])
    if os.path.isdir(f'site/{sp}/data'):
        shutil.copytree(f'site/{sp}/data', f'probe_out/{sp}', dirs_exist_ok=True)
