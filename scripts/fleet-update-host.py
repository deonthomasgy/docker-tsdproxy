#!/usr/bin/env python3
"""Image-only r2 update with private backups, drift checks and automatic rollback."""
import concurrent.futures
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import urllib.error
import urllib.parse
sys.path.insert(0,'/tmp/tsdproxy-yaml.zip')
import yaml

os.umask(0o077)
MODE=sys.argv[1]
EXPECTED=sys.argv[2]
IMAGE=sys.argv[3]
IMAGE_ID=sys.argv[4]
REVISION=sys.argv[5]
VERSION='3.0.0-beta.4-security-r2'
# Small pinned utility image, used only offline for consistent volume backups.
UTILITY='alpine:3.23@sha256:ff7f0c727dd796aa36787bfcd9a64bf35a6ce72a73451b3359fde849b6703d63'
ROOT=Path('/home/thomas/tsdproxy')
COMPOSE=ROOT/'docker-compose.yml'
BASE=['docker','compose','-p','tsdproxy','--project-directory',str(ROOT),'-f',str(COMPOSE)]
BACKUPS=Path('/home/thomas/tsdproxy-security-backups')
POINTER=ROOT/'.security-r2-rollout.json'


def run(args,**kw):
    r=subprocess.run(args,capture_output=True,**kw)
    if r.returncode:
        if 'backup' in globals():(backup/'last-command.stderr').write_bytes(r.stderr)
        raise RuntimeError('command failed: '+' '.join(args[:2])+'; private diagnostics retained')
    return r.stdout

def verify_image():
    image=json.loads(run(['docker','image','inspect',IMAGE]))[0]
    assert 'princeamd/tsdproxy@'+IMAGE.split('@')[1] in image['RepoDigests']
    assert image['Architecture']=='amd64'
    assert image['Config']['Labels']['org.opencontainers.image.revision']==REVISION
    assert image['Id'] in [IMAGE_ID,IMAGE.split('@')[1]]
    return image['Id']

def allcontainers():
    ids=run(['docker','ps','-aq'],text=True).split()
    return json.loads(run(['docker','inspect',*ids])) if ids else []

def inspect():return json.loads(run(['docker','inspect',NAME]))[0]

def read_container(path):
    data=run(['docker','cp',NAME+':'+path,'-'])
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        m=next(m for m in tar if m.isfile())
        return tar.extractfile(m).read()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kw):return None

def http(url,key=None,timeout=10):
    headers={'Authorization':'Bearer '+key} if key else {}
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        r=op.open(urllib.request.Request(url,headers=headers),timeout=timeout)
        return r.status,r.read(1024*1024)
    except urllib.error.HTTPError as e:return e.code,e.read(1024*1024)

def probe(url):
    try:
        code,body=http(url)
        return {'url':url,'status':code,'body_sha256':hashlib.sha256(body).hexdigest(),'tls_verified':url.startswith('https://')}
    except Exception as e:return {'url':url,'error':type(e).__name__}

def safe_url(url):
    try:
        u=urllib.parse.urlsplit(url)
        return u.scheme in ['http','https'] and u.hostname.endswith('.sphinx-butterfly.ts.net') and not u.username and not u.query
    except Exception:return False

def admin_url(c):
    ip=next(v['IPAddress'] for v in c['NetworkSettings']['Networks'].values() if v.get('IPAddress'))
    return 'http://'+ip+':8080'

def get_routes(c,cfg):
    key=cfg.get('apiKey')
    if cfg.get('apiKeyFile'):key=read_container(cfg['apiKeyFile']).decode().strip()
    url=admin_url(c)
    code,body=http(url+'/api/v1/proxies',key)
    if code==200:
        try:
            ps=json.loads(body)['proxies']
            return [{'name':p['name'],'status':p['status'],'health':p.get('health'),'url':p['url'] if safe_url(p.get('url','')) else None,'ports':p.get('ports',[]),'tailscale':p.get('tailscale')} for p in ps]
        except (ValueError,KeyError,TypeError):pass
    code,body=http(url+'/r/list',key)
    urls=sorted(set(u for u in re.findall(r'href="([^"]+)"',body.decode(errors='replace')) if safe_url(u)))
    return [{'name':None,'url':u,'status':'observed','ports':[]} for u in urls]

def stop_proxy():
    r=subprocess.run(BASE+['stop','--timeout','30',SERVICE],capture_output=True,timeout=60)
    if not r.returncode:return
    helper=Path('/tmp/tsdproxy-signal')
    if helper.exists() and b'permission denied' in r.stderr:
        run(['docker','cp',str(helper),NAME+':/security-signal'])
        run(['docker','exec',NAME,'/security-signal'])
        for _ in range(30):
            if not inspect()['State']['Running']:return
            time.sleep(1)
    (backup/'stop.stderr').write_bytes(r.stderr)
    raise RuntimeError('could not stop proxy; old container retained')

def state_archive(write=False):
    data=run(['docker','run','--rm','--network','none','-v','tsdproxy_datadir:/data:ro','--entrypoint','tar',UTILITY,'-cpf','-','-C','/data','.'],timeout=120)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:assert tar.getmembers()
    if write:
        (backup/'data.tar').write_bytes(data)
        (backup/'data.tar.sha256').write_text(hashlib.sha256(data).hexdigest()+'\n')
    return data


def rollback():
    current=subprocess.run(['docker','inspect',NAME],capture_output=True)
    if current.returncode==0 and json.loads(current.stdout)[0]['State']['Running']:
        stop_proxy()
        assert not inspect()['State']['Running'], 'refuse to restore state while proxy runs'
    if (backup/'data.tar').exists():
        run(['docker','run','--rm','-i','--network','none','-v','tsdproxy_datadir:/data','--entrypoint','sh',UTILITY,'-c','find /data -mindepth 1 -delete && tar -xpf - -C /data'],input=(backup/'data.tar').read_bytes(),timeout=120)
    COMPOSE.write_bytes((backup/'docker-compose.yml').read_bytes())
    # Existing bind-mounted configuration was never modified.
    run(BASE+['up','--no-start','--no-deps','--force-recreate',SERVICE],timeout=120)
    if not info['existing_config_mount']:
        run(['docker','cp',str(backup/'config'),NAME+':/'])
    run(BASE+['start',SERVICE],timeout=60)
    assert inspect()['Image']==info['old_image_id']
    print(json.dumps({'host':EXPECTED,'status':'rolled_back','backup':str(backup)}),flush=True)

# Verify the target by the authenticated tailnet identity, including localhost.
status=json.loads(run(['tailscale','status','--json']))
assert status['Self']['DNSName'].rstrip('.')==EXPECTED, 'wrong host'
cs=allcontainers()
xs=[c for c in cs if 'tsdproxy' in c['Config']['Image'].lower()]
assert len(xs)==1,'expected one proxy instance'
old=xs[0];NAME=old['Name'].lstrip('/')
labels=old['Config'].get('Labels') or {};SERVICE=labels['com.docker.compose.service']
assert labels['com.docker.compose.project.config_files']==str(COMPOSE)
assert old['State']['Running']
assert os.uname().machine=='x86_64'
assert any(m.get('Name')=='tsdproxy_datadir' and m['Destination']=='/data' for m in old['Mounts'])
assert not old['HostConfig'].get('PortBindings'),'review published management ports before upgrade'
for p in ['/AGENTS.md','/home/AGENTS.md','/home/thomas/AGENTS.md',str(ROOT/'AGENTS.md')]:
    if Path(p).exists():raise RuntimeError('Read host instructions before rollout: '+p)

assert any(m['Destination'] in ['/config','/config/tsdproxy.yaml'] for m in old['Mounts']), 'persistent config required'
original=read_container('/config/tsdproxy.yaml')
cfg=yaml.safe_load(original)
assert cfg.get('adminAllowLocalhost') is False
key=cfg.get('apiKey') or read_container(cfg['apiKeyFile']).decode().strip()

if MODE=='prepare':
    assert old['Config']['Image']!=IMAGE, 'already current; audit instead'
    if POINTER.exists():
        backup=Path(json.loads(POINTER.read_text())['backup'])
        info=json.loads((backup/'plan.json').read_text())
        assert old['Id']==info['old_container_id'], 'container changed since preparation'
        assert info['image']==IMAGE, 'prepared for different image'
    else:
        backup=BACKUPS/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-r2')
        backup.mkdir(parents=True,mode=0o700)
        (backup/'config').mkdir(mode=0o700)
        shutil.copy2(COMPOSE,backup/'docker-compose.yml');os.chmod(backup/'docker-compose.yml',0o600)
        (backup/'container-inspect.json').write_text(json.dumps(old))
        (backup/'config/tsdproxy.yaml').write_bytes(original)
        routes=get_routes(old,cfg)
        code,body=http(admin_url(old)+'/api/v1/proxies',key)
        assert code==200, 'authenticated baseline API unavailable'
        assert json.loads(body)['total']==len(routes) if 'total' in json.loads(body) else True
        urls=sorted({r['url'] for r in routes if r.get('url')})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:checks=list(pool.map(probe,urls))
        old_text=COMPOSE.read_text()
        candidate=yaml.safe_load(old_text)
        assert candidate['services'][SERVICE]['image']==old['Config']['Image'], 'Compose/image drift'
        # Replace only the unique image value and prove the YAML diff is scoped.
        pattern=r'(?m)^(\s*image:\s*)([\"\']?)'+re.escape(old['Config']['Image'])+r'\2(\s*(?:#.*)?)$'
        new_text,count=re.subn(pattern,lambda m:m[1]+m[2]+IMAGE+m[2]+m[3],old_text)
        assert count==1, 'image value must occur exactly once'
        candidate['services'][SERVICE]['image']=IMAGE
        assert yaml.safe_load(new_text)==candidate, 'unexpected Compose change'
        (backup/'candidate-compose.yml').write_text(new_text)
        run(['docker','compose','-p','tsdproxy','--project-directory',str(ROOT),'-f',str(backup/'candidate-compose.yml'),'config','--quiet'])
        info={'host':EXPECTED,'backup':str(backup),'image':IMAGE,'old_image_id':old['Image'],'old_version':labels.get('org.opencontainers.image.version'),'old_container_id':old['Id'],'compose_sha256':hashlib.sha256(COMPOSE.read_bytes()).hexdigest(),'config_sha256':hashlib.sha256(original).hexdigest(),'existing_config_mount':True,'routes':routes,'baseline_checks':checks,'other_containers':{c['Name']:c['Id'] for c in cs if c['State']['Running'] and c['Id']!=old['Id']}}
        (backup/'plan.json').write_text(json.dumps(info,indent=2)+'\n')
        POINTER.write_text(json.dumps({'backup':str(backup)}))
    run(['docker','pull',IMAGE],timeout=240);verify_image()
    run(['docker','pull',UTILITY],timeout=180)
    print(json.dumps({k:info[k] for k in ['host','backup','old_version','routes','baseline_checks']}|{'status':'prepared'}),flush=True)
else:
    backup=Path(json.loads(POINTER.read_text())['backup']);info=json.loads((backup/'plan.json').read_text())
    if MODE=='rollback':rollback();raise SystemExit
    assert MODE=='deploy'
    assert old['Id']==info['old_container_id'] and old['Image']==info['old_image_id'], 'container drift'
    assert hashlib.sha256(COMPOSE.read_bytes()).hexdigest()==info['compose_sha256'], 'Compose drift'
    assert hashlib.sha256(original).hexdigest()==info['config_sha256'], 'configuration drift'
    verify_image()
    # Compare with the live pre-stop snapshot; preparation may precede an
    # independent application deployment by several minutes.
    other_before={c['Name']:c['Id'] for c in cs if c['State']['Running'] and c['Id']!=old['Id']}
    stopped=False
    try:
        stop_proxy();stopped=True
        state_archive(write=True)
        COMPOSE.write_bytes((backup/'candidate-compose.yml').read_bytes())
        run(BASE+['up','-d','--no-deps',SERVICE],timeout=120)
        for _ in range(60):
            c=inspect();assert c['State']['Running'], 'replacement exited'
            try:
                code,body=http(admin_url(c)+'/api/v1/proxies',key,5)
                ps=json.loads(body)['proxies'] if code==200 else []
                if code==200 and len(ps)>=len(info['routes']) and all(p['status'].lower()=='running' for p in ps):break
            except (ValueError,OSError,urllib.error.URLError):pass
            time.sleep(2)
        else:raise RuntimeError('proxy readiness timeout')
        assert c['Image']==verify_image()
        run(['docker','exec',NAME,'/tsdproxyd','healthcheck'],timeout=10)
        for path,auth,expected in [('/health/ready/',False,200),('/',False,403),('/api/version',False,403),('/api/version',True,200),('/',True,200)]:
            code,body=http(admin_url(c)+path,key if auth else None)
            assert code==expected, 'management endpoint status mismatch'
            if path=='/api/version' and auth:assert json.loads(body)['version']==VERSION
        assert read_container('/config/tsdproxy.yaml')==original, 'configuration changed'
        after_routes=get_routes(c,cfg)
        old_urls={r['url'] for r in info['routes'] if r.get('url')}
        new_urls={r['url'] for r in after_routes if r.get('url')}
        assert old_urls==new_urls, 'route hostname set changed'
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:checks=list(pool.map(probe,sorted(new_urls)))
        baseline={p['url']:p for p in info['baseline_checks']}
        for check in checks:
            previous=baseline.get(check['url'],{})
            if previous.get('status',500)<500:
                assert check.get('status')==previous['status'], 'route response regressed: '+check['url']
        other={c['Name']:c['Id'] for c in allcontainers() if c['State']['Running']}
        assert all(other.get(n)==i for n,i in other_before.items()), 'unrelated container changed during proxy update'
        result={'host':EXPECTED,'status':'deployed','image':IMAGE,'image_id':c['Image'],'backup':str(backup),'old_version':info['old_version'],'routes':after_routes,'checks':checks,'baseline_checks':info['baseline_checks'],'authentication_verified':True,'configuration_unchanged':True,'other_containers_unchanged':True,'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
        (backup/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    except BaseException:
        if stopped:rollback()
        raise
