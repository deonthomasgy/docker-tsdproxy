#!/usr/bin/env python3
"""Remove the disposable route and verify recreation of the authorized canary."""
import datetime
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import time
import urllib.request
import urllib.error

BACKUP=Path('/home/thomas/tsdproxy-security-backups/20261025T181353Z')
ROOT=Path('/home/thomas/tsdproxy')
NAME='tsdproxy-tailscale-docker-proxy-1'
UTILITY='sha256:fdbe5de10f44760345c5c4e9b58d8479bc73915322c3882f7c14004f23d71d9b'
IMAGE_ID='sha256:f908bfef102160be0ca7171fb4bc03a5bd9e4bec30f05e27a1b407bd0ebd9dab'

def run(args,**kw):
    r=subprocess.run(args,capture_output=True,**kw)
    if r.returncode:
        (BACKUP/'finalize.stderr').write_bytes(r.stderr)
        raise RuntimeError('verification command failed; private diagnostics saved')
    return r.stdout

def inspect():return json.loads(run(['docker','inspect',NAME]))[0]

def proxies():
    c=inspect();ip=c['NetworkSettings']['Networks']['isolated_nw']['IPAddress']
    key=(ROOT/'config/api-key').read_text().strip()
    r=urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urllib.request.Request('http://'+ip+':8080/api/v1/proxies',headers={'Authorization':'Bearer '+key}),timeout=5)
    return json.load(r)['proxies']

assert json.loads(run(['tailscale','status','--json']))['Self']['DNSName']=='orion-fs-host-1.sphinx-butterfly.ts.net.'
assert inspect()['Image']==IMAGE_ID
ids=run(['docker','ps','-q'],text=True).split()
before={c['Name']:c['Id'] for c in json.loads(run(['docker','inspect',*ids])) if c['Name'] not in ['/'+NAME,'/tsdproxy-security-canary']}
run(['docker','rm','-f','tsdproxy-security-canary'])
for _ in range(20):
    if not proxies():break
    time.sleep(1)
else:raise RuntimeError('canary route did not disappear')
print('Temporary route removed',flush=True)
old_id=inspect()['Id']
run(['docker','compose','-p','tsdproxy','--project-directory',str(ROOT),'-f',str(ROOT/'docker-compose.yml'),'up','-d','--no-deps','--force-recreate','tailscale-docker-proxy'],timeout=120)
for _ in range(40):
    c=inspect()
    assert c['State']['Running'], 'proxy exited after recreation'
    if c['State'].get('Health',{}).get('Status')=='healthy':break
    time.sleep(2)
else:raise RuntimeError('Docker health did not become healthy')
assert c['Id']!=old_id and c['Image']==IMAGE_ID
assert c['RestartCount']==0
assert not proxies()
ip=c['NetworkSettings']['Networks']['isolated_nw']['IPAddress']
key=(ROOT/'config/api-key').read_text().strip()
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for path,auth,expected in [('/health/ready/',False,200),('/',False,403),('/api/version',False,403),('/api/version',True,200),('/',True,200)]:
    try:
        r=opener.open(urllib.request.Request('http://'+ip+':8080'+path,headers={'Authorization':'Bearer '+key} if auth else {}),timeout=5)
        code=r.status
        if path=='/api/version' and auth:assert json.load(r)['version']=='3.0.0-beta.4-security-r1'
    except urllib.error.HTTPError as e:code=e.code
    assert code==expected, 'HTTP check failed after recreation'
assert any(m['Destination']=='/config' and m['Source']==str(ROOT/'config') and not m['RW'] for m in c['Mounts'])
assert any(m['Destination']=='/data' and m.get('Name')=='tsdproxy_datadir' for m in c['Mounts'])
assert not c['HostConfig']['PortBindings']
ids=run(['docker','ps','-q'],text=True).split()
after={x['Name']:x['Id'] for x in json.loads(run(['docker','inspect',*ids]))}
assert all(after.get(n)==i for n,i in before.items())
assert '/tsdproxy-security-canary' not in after

def contents(data):
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        return {m.name:hashlib.sha256(tar.extractfile(m).read()).hexdigest() for m in tar if m.isfile()}
original=contents((BACKUP/'data.tar').read_bytes())
current=contents(run(['docker','run','--rm','--network','none','-v','tsdproxy_datadir:/data:ro','--entrypoint','tar',UTILITY,'-cpf','-','-C','/data','.'],timeout=60))
changed=[p for p,h in original.items() if current.get(p)!=h]
assert not changed, 'pre-existing state files changed: '+repr(changed)
assert not any('tsdproxy-canary-orion-20261025' in p for p in current), 'canary state was not removed'
r=json.loads((BACKUP/'deployment-result.json').read_text())
r.update(verified_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),docker_health=c['State']['Health']['Status'],restart_count=c['RestartCount'],container_recreation_verified=True,authentication_after_recreation=True,temporary_route_removed=True,temporary_state_removed=True,original_state_files_unchanged=len(original),other_running_containers_unchanged=True,published_ports=[],routing_verification='HTTP and HTTPS 200 with matching nonce from separate Tailscale workstation; TLS verification enabled; no Funnel')
(BACKUP/'deployment-result.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r),flush=True)
