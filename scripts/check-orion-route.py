#!/usr/bin/env python3
"""Start/check a disposable private canary route on the authorized canary host."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import urllib.request

os.umask(0o077)
NAME = 'tsdproxy-security-canary'
HOSTNAME = 'tsdproxy-canary-orion-20261025'
ROOT = Path('/home/thomas/tsdproxy')
BACKUP = Path('/home/thomas/tsdproxy-security-backups/20261025T181353Z')
UTILITY = 'sha256:fdbe5de10f44760345c5c4e9b58d8479bc73915322c3882f7c14004f23d71d9b'

def run(args):
    r = subprocess.run(args,capture_output=True,text=True)
    if r.returncode:
        (BACKUP/'route-command.stderr').write_text(r.stderr)
        raise RuntimeError('route command failed; private stderr saved')
    return r.stdout

assert json.loads(run(['tailscale','status','--json']))['Self']['DNSName']=='orion-fs-host-1.sphinx-butterfly.ts.net.'
c = json.loads(run(['docker','inspect','tsdproxy-tailscale-docker-proxy-1']))[0]
assert c['Image']=='sha256:f908bfef102160be0ca7171fb4bc03a5bd9e4bec30f05e27a1b407bd0ebd9dab'
existing = subprocess.run(['docker','inspect',NAME],capture_output=True)
if existing.returncode:
    nonce = 'tsdproxy-canary-' + secrets.token_hex(12)
    (BACKUP/'canary-token').write_text(nonce)
    conf = 'events {}\nhttp { server { listen 8080; location / { default_type text/plain; return 200 "'+nonce+'\\n"; } } }\n'
    (BACKUP/'canary-nginx.conf').write_text(conf)
    run(['docker','run','-d','--name',NAME,'--network','isolated_nw','--label','tsdproxy.enable=true','--label','tsdproxy.name='+HOSTNAME,'--label','tsdproxy.ephemeral=true','--label','tsdproxy.autodetect=true','--label','tsdproxy.port.443=443/https:8080/http','--label','tsdproxy.port.80=80/http:8080/http','--label','tsdproxy.funnel=false','--label','tsdproxy.runwebclient=false','--label','tsdproxy.auto_restart=false','-v',str(BACKUP/'canary-nginx.conf')+':/canary.conf:ro','--entrypoint','nginx',UTILITY,'-c','/canary.conf','-g','daemon off;'])
    print('Created temporary private route:',HOSTNAME)
ip=c['NetworkSettings']['Networks']['isolated_nw']['IPAddress']
token=(ROOT/'config/api-key').read_text().strip()
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
r=opener.open(urllib.request.Request('http://'+ip+':8080/api/v1/proxies',headers={'Authorization':'Bearer '+token}),timeout=5)
proxies=json.load(r)['proxies']
for p in proxies:
    # Do not print authentication URLs or any credentials.
    out={k:p[k] for k in ['name','status','health','targetProvider','tailscale']}
    if p['status'].lower()=='running':out.update(url=p['url'],ports=p['ports'])
    print(json.dumps(out))
print('proxy count',len(proxies))
