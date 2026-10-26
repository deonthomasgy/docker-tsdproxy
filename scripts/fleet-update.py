#!/usr/bin/env python3
"""Run image-only updates sequentially using a fresh release-specific inventory."""
import json
import os
from pathlib import Path
import subprocess
import sys

os.umask(0o077)
mode = sys.argv[1]
assert mode in ('prepare', 'deploy')
selected = set(sys.argv[2:])
root = Path('reports/ts2026013/fleet')
release = json.loads((root / 'release.json').read_text())
records = json.loads((root / 'discovery.json').read_text())
source = Path('scripts/fleet-update-host.py').read_text()
records.sort(key=lambda r: (r['host'] == 'localhost', not r['host'].startswith('orion-fs-host-1'), r['host']))
for record in records:
    if not record.get('instances'):
        continue
    host = record['host']
    name = host.split('.')[0]
    if selected and name not in selected:
        continue
    destination = root / f'{mode}-{name}.json'
    deployed = root / f'deploy-{name}.json'
    if deployed.exists():
        prior = json.loads(deployed.read_text())
        if prior.get('status') == 'deployed' and prior.get('image') == release['image']:
            print(name, 'already deployed', flush=True)
            continue
    expected = 'alpha-old.sphinx-butterfly.ts.net' if host == 'localhost' else host
    command = ['python3', '-', mode, expected, release['image'], release['image_id'], release['source_revision']]
    if host != 'localhost':
        command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', host] + command
    print(mode, name, 'starting', flush=True)
    result = subprocess.run(command, input=source, text=True, capture_output=True, timeout=600)
    (root / f'{mode}-{name}.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        print(mode, name, 'FAILED; rollout stopped, see private log', flush=True)
        raise SystemExit(1)
    data = json.loads(result.stdout.strip().splitlines()[-1])
    destination.write_text(json.dumps(data, indent=2) + '\n')
    print(mode, name, data['status'], 'routes', len(data.get('routes', [])), flush=True)
