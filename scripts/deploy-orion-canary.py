#!/usr/bin/env python3
"""One-host 1.4.7 migration. Run on orion-fs-host-1; secrets remain on that host."""
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import time
import urllib.request
import urllib.error
import yaml

os.umask(0o077)
ROOT = Path('/home/thomas/tsdproxy')
COMPOSE = ROOT / 'docker-compose.yml'
NAME = 'tsdproxy-tailscale-docker-proxy-1'
SERVICE = 'tailscale-docker-proxy'
IMAGE = 'princeamd/tsdproxy:3.0.0-beta.4-security-r1@sha256:f841dec2e77b51f70969d59fdcf80c4efb85254a6b6007b223e03631c8a174c4'
IMAGE_ID = 'sha256:f908bfef102160be0ca7171fb4bc03a5bd9e4bec30f05e27a1b407bd0ebd9dab'
OLD_ID = 'sha256:d26348ccb57ed41aa5fe37b6b1e2cb468c08c08ce02e18ba4720e74214020bc3'
UTILITY = 'sha256:fdbe5de10f44760345c5c4e9b58d8479bc73915322c3882f7c14004f23d71d9b'
VOLUME = 'tsdproxy_datadir'
BASE = ['docker', 'compose', '-p', 'tsdproxy', '--project-directory', str(ROOT), '-f', str(COMPOSE)]


def run(args, **kwargs):
    r = subprocess.run(args, capture_output=True, **kwargs)
    if r.returncode:
        # Commands and stderr can contain config or credentials. Save diagnostics privately.
        if 'backup' in globals():
            (backup / 'last-command.stderr').write_bytes(r.stderr)
        raise RuntimeError('command failed: ' + ' '.join(args[:2]) + '; private diagnostics retained')
    return r.stdout


def inspect(name=NAME):
    return json.loads(run(['docker', 'inspect', name]))[0]


def request(ip, path, token=None):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = opener.open(urllib.request.Request('http://' + ip + ':8080' + path, headers=headers), timeout=5)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


assert json.loads(run(['tailscale','status','--json']))['Self']['DNSName'] == 'orion-fs-host-1.sphinx-butterfly.ts.net.', 'wrong tailnet host'
assert hashlib.sha256(COMPOSE.read_bytes()).hexdigest() == 'df86945a4852d30f673793e729620cfc132ea6631db9db5f5adac1f4e3ece23b', 'Compose changed'
old = inspect()
assert old['Image'] == OLD_ID and old['State']['Running'], 'running image changed'
assert old['NetworkSettings']['Networks'].keys() == {'isolated_nw'}, 'network changed'
assert not (ROOT / 'config').exists(), 'config mount already exists; inspect before migration'
ids = run(['docker', 'ps', '-q'], text=True).split()
before = {c['Name']: c['Id'] for c in json.loads(run(['docker', 'inspect', *ids]))}
status = json.loads(run(['tailscale', 'status', '--json']))
owner = status['Self']['UserID']
assert status['BackendState'] == 'Running' and owner, 'host tailnet not ready'
backup = Path('/home/thomas/tsdproxy-security-backups') / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup.mkdir(parents=True, mode=0o700)
(backup / 'config').mkdir(mode=0o700)
shutil.copy2(COMPOSE, backup / 'docker-compose.yml')
os.chmod(backup / 'docker-compose.yml', 0o600)
(backup / 'container-inspect.json').write_text(json.dumps(old))
archive = tarfile.open(fileobj=io.BytesIO(run(['docker', 'cp', NAME + ':/config/tsdproxy.yaml', '-'])))
member = next(x for x in archive if x.isfile())
original = archive.extractfile(member).read()
(backup / 'config/tsdproxy.yaml').write_bytes(original)
config = yaml.safe_load(original)
assert not config.get('files'), 'static list conversion needs review'
assert set(config['docker']) == {'local'} and set(config['tailscale']['providers']) == {'default'}, 'provider configuration changed'
assert set(config).issubset({'defaultproxyprovider','docker','files','tailscale','http','log','proxyaccesslog'}), 'unexpected config'
keys = {'defaultproxyprovider':'defaultProxyProvider', 'proxyaccesslog':'proxyAccessLog', 'targethostname':'targetHostname', 'authkey':'authKey', 'controlurl':'controlUrl', 'datadir':'dataDir'}
def convert(x):
    if isinstance(x, dict):
        return {keys.get(k,k):convert(v) for k,v in x.items()}
    return x
config = convert(config)
config.pop('files', None)
config['lists'] = {}
config['adminAllowLocalhost'] = False
config['admins'] = ['userid:' + str(owner)]
config['apiKeyFile'] = '/config/api-key'
config['tailscale']['providers']['default'].update(shared=False, services=False)
config['docker']['local'].update(allowContainerFunnel=False, allowTlsValidateDisable=False)
configdir = ROOT / 'config'
configdir.mkdir(mode=0o700)
token = secrets.token_urlsafe(48)
(configdir / 'api-key').write_text(token + '\n')
(configdir / 'tsdproxy.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
candidate = yaml.safe_load(COMPOSE.read_text())
candidate['services'][SERVICE]['image'] = IMAGE
candidate['services'][SERVICE]['volumes'].append(str(configdir) + ':/config:ro')
(backup / 'candidate-compose.yml').write_text(yaml.safe_dump(candidate, sort_keys=False))
run(['docker','compose','-p','tsdproxy','--project-directory',str(ROOT),'-f',str(backup / 'candidate-compose.yml'),'config','--quiet'])
print('Preflight passed; private backup:', backup, flush=True)
run(['docker','pull',IMAGE], timeout=240)
assert json.loads(run(['docker','image','inspect',IMAGE]))[0]['Id'] == IMAGE_ID
print('Verified replacement image pulled', flush=True)
stopped = False
volume_saved = False
try:
    run(BASE + ['stop','--timeout','30',SERVICE], timeout=60)
    stopped = True
    assert not inspect()['State']['Running']
    data = run(['docker','run','--rm','--network','none','-v',VOLUME+':/data:ro','--entrypoint','tar',UTILITY,'-cpf','-','-C','/data','.'], timeout=120)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members = tar.getmembers()
        assert members, 'empty archive'
    (backup / 'data.tar').write_bytes(data)
    (backup / 'data.tar.sha256').write_text(hashlib.sha256(data).hexdigest()+'\n')
    volume_saved = True
    print('Stopped old proxy; data backup verified:', len(data), 'bytes', flush=True)
    COMPOSE.write_bytes((backup / 'candidate-compose.yml').read_bytes())
    run(BASE + ['up','-d','--no-deps',SERVICE], timeout=120)
    for _ in range(30):
        c = inspect()
        if not c['State']['Running']:
            raise RuntimeError('replacement exited')
        h = subprocess.run(['docker','exec',NAME,'/tsdproxyd','healthcheck'], capture_output=True)
        if h.returncode == 0:
            break
        time.sleep(2)
    else:
        raise RuntimeError('readiness timeout')
    assert c['Image'] == IMAGE_ID
    ip = c['NetworkSettings']['Networks']['isolated_nw']['IPAddress']
    checks = []
    for path, auth, expected in [('/health/ready/',False,200),('/',False,403),('/api/version',False,403),('/api/v1/proxies',False,403),('/api/version',True,200),('/api/v1/proxies',True,200),('/',True,200)]:
        code, body = request(ip,path,token if auth else None)
        assert code == expected, 'unexpected HTTP status at '+path
        if path == '/api/version' and auth:
            assert json.loads(body)['version'] == '3.0.0-beta.4-security-r1'
        checks.append({'path':path,'authenticated':auth,'status':code})
    code, body = request(ip,'/api/v1/proxies',token)
    proxies = json.loads(body)['proxies']
    assert not proxies, 'unexpected proxy discovered'
    ids = run(['docker','ps','-q'],text=True).split()
    after = {c['Name']:c['Id'] for c in json.loads(run(['docker','inspect',*ids]))}
    assert all(after.get(n)==i for n,i in before.items() if n!='/'+NAME), 'unrelated container changed'
    result = {'host':'orion-fs-host-1','image':IMAGE,'image_id':IMAGE_ID,'backup':str(backup),'config_persisted':True,'checks':checks,'baseline_routes':len(proxies),'other_running_containers_unchanged':True,'routing_verification':'pending'}
    (backup / 'deployment-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
except BaseException:
    print('Deployment check failed; restoring old service',flush=True)
    if stopped:
        subprocess.run(BASE + ['stop','--timeout','30',SERVICE],capture_output=True)
        if volume_saved:
            run(['docker','run','--rm','-i','--network','none','-v',VOLUME+':/data','--entrypoint','sh',UTILITY,'-c','find /data -mindepth 1 -delete && tar -xpf - -C /data'],input=(backup/'data.tar').read_bytes(),timeout=120)
        COMPOSE.write_bytes((backup/'docker-compose.yml').read_bytes())
        run(BASE + ['up','--no-start','--force-recreate','--no-deps',SERVICE],timeout=120)
        run(['docker','cp',str(backup/'config'),NAME+':/'])
        run(BASE + ['start',SERVICE],timeout=60)
        print('Original image and state restored; inspect private backup diagnostics',flush=True)
    raise
