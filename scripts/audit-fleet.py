#!/usr/bin/env python3
"""Read-only final fleet checks and independent-client route verification."""
import concurrent.futures
import datetime
import json
from pathlib import Path
import subprocess
import urllib.request
import urllib.error
import urllib.parse

REMOTE=r'''
import json,subprocess,io,tarfile,sys,urllib.request,urllib.error
sys.path.insert(0,'/tmp/tsdproxy-yaml.zip');import yaml
ids=subprocess.check_output(['docker','ps','-aq'],text=True).split();cs=json.loads(subprocess.check_output(['docker','inspect',*ids]))
xs=[c for c in cs if 'tsdproxy' in c['Config']['Image'].lower()]
assert len(xs)==1
c=xs[0];name=c['Name'].lstrip('/')
def file(path):
 b=subprocess.check_output(['docker','cp',name+':'+path,'-']);t=tarfile.open(fileobj=io.BytesIO(b));m=next(x for x in t if x.isfile());return t.extractfile(m).read()
cfg=yaml.safe_load(file('/config/tsdproxy.yaml'));key=cfg.get('apiKey') or file(cfg['apiKeyFile']).decode().strip()
ip=next(x['IPAddress'] for x in c['NetworkSettings']['Networks'].values() if x.get('IPAddress'));url='http://'+ip+':8080'
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path,auth):
 try:
  r=op.open(urllib.request.Request(url+path,headers={'Authorization':'Bearer '+key} if auth else {}),timeout=5);return r.status,r.read()
 except urllib.error.HTTPError as e:return e.code,e.read()
checks={}
for path,auth in [('/health/ready/',False),('/',False),('/api/version',False),('/api/version',True),('/',True)]:
 code,body=get(path,auth);checks[path+(' authenticated' if auth else ' anonymous')]=code
 if path=='/api/version' and auth:version=json.loads(body)['version']
code,body=get('/api/v1/proxies',True);ps=json.loads(body)['proxies']
labels=c['Config']['Labels'];compose=labels['com.docker.compose.project.config_files'];svc=labels['com.docker.compose.service'];persisted=yaml.safe_load(open(compose))['services'][svc]['image']
print(json.dumps({'name':name,'image':c['Config']['Image'],'image_id':c['Image'],'version':version,'running':c['State']['Running'],'health':c['State'].get('Health',{}).get('Status'),'restart_count':c['RestartCount'],'compose_image':persisted,'config_mounted':any(x['Destination'].startswith('/config') for x in c['Mounts']),'admin_allow_localhost':cfg.get('adminAllowLocalhost'),'published_ports':c['HostConfig'].get('PortBindings'),'checks':checks,'routes':[{'name':p['name'],'status':p['status'],'health':p['health'],'url':p['url'] if '.sphinx-butterfly.ts.net' in p['url'] else None,'ports':p['ports']} for p in ps]}))
'''
records=json.loads(Path('reports/fleet/discovery.json').read_text())
hosts=[x['host'] for x in records if x.get('instances')]
def audit(host):
 cmd=['python3','-'] if host=='localhost' else ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8',host,'python3','-']
 r=subprocess.run(cmd,input=REMOTE,text=True,capture_output=True,timeout=30)
 if r.returncode:return {'host':host,'error':'audit failed','details':r.stderr[-400:]}
 d=json.loads(r.stdout);d['host']='alpha-old.sphinx-butterfly.ts.net' if host=='localhost' else host;return d
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(audit,hosts))
image=json.loads(Path('release.json').read_text())['image']
for r in results:
 r['passed']=not r.get('error') and r['image']==image and r['compose_image']==image and r['health']=='healthy' and r['restart_count']==0 and r['config_mounted'] and r['admin_allow_localhost'] is False and all(c==(200 if ('authenticated' in p or p.startswith('/health/')) else 403) for p,c in r['checks'].items())
 print(r['host'].split('.')[0],r.get('health'),r['passed'],'routes',len(r.get('routes',[])),flush=True)
Path('reports/fleet/final-audit.json').write_text(json.dumps(results,indent=2)+'\n')

baseline={}
for p in Path('reports/fleet').glob('prepare-*.json'):
 d=json.loads(p.read_text())
 for c in d['baseline_checks']:baseline[c['url']]=c
urls=sorted({p['url'] for r in results for p in r.get('routes',[]) if p.get('url')})
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def check(url):
 d={'url':url,'baseline':baseline.get(url,{})}
 try:
  op=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
  try:r=op.open(url,timeout=12);code=r.status;r.close()
  except urllib.error.HTTPError as e:code=e.code
  d.update(status=code,tls_verified=url.startswith('https:'))
 except Exception as e:d['error']=type(e).__name__
 b=d['baseline'];d['regression']=b.get('status',500)<500 and b.get('status')!=d.get('status')
 return d
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:checks=list(pool.map(check,urls))
old=json.loads(Path('/tmp/tsdproxy-fleet-tailnet.json').read_text());now=json.loads(subprocess.check_output(['tailscale','status','--json'],timeout=15))
om={p.get('DNSName','').rstrip('.'):p for p in old['Peer'].values()};nm={p.get('DNSName','').rstrip('.'):p for p in now['Peer'].values()}
identities=[]
for url in urls:
 dns=urllib.parse.urlsplit(url).hostname;a=om.get(dns);b=nm.get(dns)
 identities.append({'dns':dns,'present':b is not None,'node_id_preserved':a is not None and b is not None and a['ID']==b['ID'],'addresses_preserved':a is not None and b is not None and a['TailscaleIPs']==b['TailscaleIPs']})
report={'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':checks,'identities':identities,'regressions':[c['url'] for c in checks if c['regression']]}
Path('reports/fleet/external-routes.json').write_text(json.dumps(report,indent=2)+'\n')
print('External routes',len(checks),'healthy baseline preserved',sum(c['baseline'].get('status',500)<500 and not c['regression'] for c in checks),'regressions',report['regressions'],flush=True)
print('Changed node identities',[i['dns'] for i in identities if not i['node_id_preserved']],flush=True)
