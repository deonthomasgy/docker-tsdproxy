#!/usr/bin/env python3
"""Run the bounded host operation sequentially and retain sanitized results."""
import json
import os
from pathlib import Path
import subprocess
import sys

os.umask(0o077)
mode=sys.argv[1]
selected=set(sys.argv[2:])
records=json.loads(Path('reports/fleet/discovery.json').read_text())
source=Path('scripts/fleet-host.py').read_text()
for record in records:
 if not record.get('instances'):continue
 host=record['host'];name=host.split('.')[0]
 if selected and name not in selected:continue
 if name=='orion-fs-host-1':continue
 if mode=='deploy' and Path(f'reports/fleet/deploy-{name}.json').exists():
  prior=json.loads(Path(f'reports/fleet/deploy-{name}.json').read_text())
  if prior.get('status')=='deployed':
   print(mode,name,'already deployed',flush=True);continue
 actual='alpha-old.sphinx-butterfly.ts.net' if host=='localhost' else host
 command=['python3','-',mode,actual] if host=='localhost' else ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8',host,'python3','-',mode,actual]
 print(mode,name,'starting',flush=True)
 result=subprocess.run(command,input=source,text=True,capture_output=True,timeout=600)
 Path(f'reports/fleet/{mode}-{name}.log').write_text(result.stdout+result.stderr)
 if result.returncode:
  print(mode,name,'FAILED (see private log)',flush=True)
  if mode=='deploy':break
  continue
 try:
  data=json.loads(result.stdout.strip().splitlines()[-1]);Path(f'reports/fleet/{mode}-{name}.json').write_text(json.dumps(data,indent=2)+'\n')
  print(mode,name,data['status'],'routes',len(data.get('routes',[])),flush=True)
 except (ValueError,KeyError):print(mode,name,'unparsed result',flush=True);break
