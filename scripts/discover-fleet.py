#!/usr/bin/env python3
"""Read-only TSDProxy inventory; print selected metadata, never credentials."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess

os.umask(0o077)
REMOTE = r'''
import subprocess,json,io,tarfile,os
try:import yaml
except ImportError:yaml=None
prefix=['docker']
r=subprocess.run(prefix+['ps','-aq'],capture_output=True,text=True)
if r.returncode:
 prefix=['sudo','-n','docker'];r=subprocess.run(prefix+['ps','-aq'],capture_output=True,text=True)
if r.returncode:
 print(json.dumps({'docker_access':False}));raise SystemExit
ids=r.stdout.split()
cs=json.loads(subprocess.check_output(prefix+['inspect',*ids])) if ids else []
result={'docker_access':True,'docker_prefix':prefix,'architecture':os.uname().machine,'container_count':len(cs),'instances':[]}
for c in cs:
 if 'tsdproxy' not in (c['Config']['Image']+' '+c['Name']).lower():continue
 labels=c['Config'].get('Labels') or {}
 x={'name':c['Name'].lstrip('/'),'id':c['Id'],'image':c['Config']['Image'],'image_id':c['Image'],'running':c['State']['Running'],'status':c['State']['Status'],'health':c['State'].get('Health',{}).get('Status'),'version':labels.get('org.opencontainers.image.version'),'compose':{k:labels.get('com.docker.compose.'+k) for k in ['project','service','project.config_files','project.working_dir']},'mounts':[{k:m.get(k) for k in ['Type','Name','Source','Destination','RW']} for m in c['Mounts']],'networks':list(c['NetworkSettings']['Networks']),'network_mode':c['HostConfig']['NetworkMode'],'published_ports':c['HostConfig'].get('PortBindings'),'environment_names':[v.split('=',1)[0] for v in c['Config'].get('Env',[])],'command':c['Config'].get('Cmd')}
 path='/config/tsdproxy.yaml'
 cmd=c['Config'].get('Cmd') or []
 if '-config' in cmd:path=cmd[cmd.index('-config')+1]
 for arg in cmd:
  if arg.startswith('-config='):path=arg.split('=',1)[1]
 # Do not return arbitrary command arguments that could contain credentials.
 x['command_present']=bool(cmd);x.pop('command',None);x['config_path']=path
 r=subprocess.run(prefix+['cp',c['Id']+':'+path,'-'],capture_output=True)
 if r.returncode==0 and yaml:
  try:
   tar=tarfile.open(fileobj=io.BytesIO(r.stdout));f=next(v for v in tar if v.isfile());cfg=yaml.safe_load(tar.extractfile(f));x['config_keys']=list(cfg)
   d=cfg.get('docker') or {};x['docker_providers']={k:{'host':v.get('host'),'target_hostname':v.get('targethostname',v.get('targetHostname')),'keys':list(v)} for k,v in d.items()}
   ts=cfg.get('tailscale') or {};x['data_dir']=ts.get('datadir',ts.get('dataDir'));x['tailscale_providers']={k:{'keys':list(v),'shared':v.get('shared',False),'services':v.get('services',False),'auth_configured':bool(v.get('authkey') or v.get('authKey') or v.get('authkeyfile') or v.get('authKeyFile') or v.get('clientId'))} for k,v in (ts.get('providers') or {}).items()}
   x['file_providers']=list((cfg.get('files') or {}).keys());x['list_providers']=list((cfg.get('lists') or {}).keys());x['http']=cfg.get('http');x['admins_configured']=bool(cfg.get('admins'))
  except Exception as e:x['config_error']=type(e).__name__
 else:x['config_readable']=False
 x['enabled_containers']=[{'name':z['Name'].lstrip('/'),'labels':{k:v for k,v in (z['Config'].get('Labels') or {}).items() if k in ['tsdproxy.enable','tsdproxy.name','tsdproxy.container_port','tsdproxy.scheme','tsdproxy.funnel','tsdproxy.autodetect','tsdproxy.ephemeral','tsdproxy.proxyprovider'] or k.startswith('tsdproxy.port.')}} for z in cs if (z['Config'].get('Labels') or {}).get('tsdproxy.enable')=='true']
 result['instances'].append(x)
print(json.dumps(result))
'''
s=json.loads(Path('/tmp/tsdproxy-fleet-tailnet.json').read_text())
hosts=[(p.get('DNSName','').rstrip('.'),p.get('Online',False)) for p in s.get('Peer',{}).values() if p.get('OS')=='linux' and p.get('DNSName')]

def discover(item):
 host,online=item
 try:
  r=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','-o','StrictHostKeyChecking=accept-new',host,'python3','-'],input=REMOTE,text=True,capture_output=True,timeout=18)
  if r.returncode==0:
   d=json.loads(r.stdout);d.update(host=host,online=online)
  else:d={'host':host,'online':online,'error':r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'SSH command failed'}
 except Exception as e:d={'host':host,'online':online,'error':type(e).__name__}
 return d
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
 for r in pool.map(discover,hosts):
  results.append(r)
  if r.get('instances'):print(r['host'],[(x['name'],x['version'],x['running'],len(x['enabled_containers'])) for x in r['instances']],flush=True)
local=subprocess.run(['python3','-'],input=REMOTE,text=True,capture_output=True)
if local.returncode==0:
 d=json.loads(local.stdout);d.update(host='localhost',online=True);results.append(d)
 if d.get('instances'):print('localhost',[(x['name'],x['version'],x['running']) for x in d['instances']],flush=True)
Path('reports/fleet/discovery.json').write_text(json.dumps(results,indent=2)+'\n')
print('Summary:',json.dumps({'attempted':len(results),'docker_access':sum(r.get('docker_access',False) for r in results),'instances':sum(len(r.get('instances',[])) for r in results),'unreachable':[r['host'] for r in results if 'error'in r]}),flush=True)
