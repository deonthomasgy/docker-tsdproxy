#!/usr/bin/env python3
"""Offline runtime checks; no host Docker socket, tailnet keys or state mounted."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

IMAGE = sys.argv[1] if len(sys.argv) > 1 else 'princeamd/tsdproxy:3.0.0-beta.4-security-r2'
GO_IMAGE = 'golang:1.27.3-bookworm@sha256:972b4110ba0f47539a975c31e52c64765e1ff19f2d74469ae4a595c6676e80a5'
CLIENT = r'''package main
import("fmt";"io";"net/http";"os";"strings";"syscall";"time")
func main(){
 if len(os.Args)>1 && os.Args[1]=="stop" { if err:=syscall.Kill(1,syscall.SIGTERM);err!=nil{panic(err)};return }
 c:=&http.Client{Timeout:5*time.Second}
 checks:=[]struct{path,key string; status int; contains string}{
 {"/health/ready/","",200,""},
 {"/","",403,""},
 {"/api/version","",403,""},
 {"/api/v1/proxies","",403,""},
 {"/api/version","wrong",403,""},
 {"/api/version","offline-smoke-test-only",200,"3.0.0-beta.4-security-r2"},
 {"/api/v1/proxies","offline-smoke-test-only",200,""},
 {"/","offline-smoke-test-only",200,"html"},
 {"/app.js","",200,""},
 {"/styles.css","",200,""},
 }
 for _,v:=range checks{
 r,_:=http.NewRequest("GET","http://127.0.0.1:8080"+v.path,nil)
 if v.key!=""{r.Header.Set("Authorization","Bearer "+v.key)}
 resp,err:=c.Do(r);if err!=nil{panic(err)}
 body,err:=io.ReadAll(resp.Body);resp.Body.Close();if err!=nil{panic(err)}
 if resp.StatusCode!=v.status||!strings.Contains(string(body),v.contains){panic(fmt.Sprintf("%s: status=%d, want=%d",v.path,resp.StatusCode,v.status))}
 fmt.Printf("PASS %s status=%d authenticated=%t\n",v.path,resp.StatusCode,v.key!="")
 }
}'''

def run(*args, **kw):
    return subprocess.run(args, check=True, text=True, **kw)

name = 'tsdproxy-security-smoke-' + uuid.uuid4().hex[:8]
created = False
with tempfile.TemporaryDirectory(prefix='tsdproxy-smoke-') as directory:
    root = Path(directory)
    (root / 'client.go').write_text(CLIENT)
    (root / 'targets.yaml').write_text('{}\n')
    (root / 'tsdproxy.yaml').write_text('''defaultProxyProvider: default
docker: {}
lists:
  offline:
    filename: /config/targets.yaml
tailscale:
  dataDir: /data
  providers:
    default:
      controlUrl: https://controlplane.tailscale.com
      shared: false
      services: false
http:
  hostname: 0.0.0.0
  port: 8080
adminAllowLocalhost: false
apiKey: offline-smoke-test-only
icons:
  download: false
''')
    run('docker', 'run', '--rm', '-v', f'{root}:/work', '-v', 'tsdproxy-go-build:/root/.cache/go-build', '-w', '/work', GO_IMAGE,
        'sh', '-c', 'CGO_ENABLED=0 go build -o client client.go')
    try:
        run('docker', 'run', '-d', '--name', name, '--network', 'none',
            '--tmpfs', '/data', '-v', f'{root}:/config:ro', IMAGE,
            stdout=subprocess.DEVNULL)
        created = True
        run('docker', 'cp', str(root / 'client'), name + ':/smoke-client')
        for _ in range(30):
            check = subprocess.run(['docker', 'exec', name, '/tsdproxyd', 'healthcheck'], capture_output=True)
            if check.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('readiness did not become healthy')
        print('PASS image healthcheck', flush=True)
        run('docker', 'exec', name, '/smoke-client')
        run('docker', 'exec', name, '/smoke-client', 'stop')
        exit_code = run('docker', 'wait', name, capture_output=True).stdout.strip()
        if exit_code != '0':
            raise RuntimeError('shutdown exit code ' + exit_code)
        print('PASS graceful SIGTERM shutdown', flush=True)
    finally:
        if created:
            run('docker', 'logs', name)
            state = json.loads(run('docker', 'inspect', name, capture_output=True).stdout)[0]['State']
            if state['Running']:
                subprocess.run(['docker', 'exec', name, '/smoke-client', 'stop'], capture_output=True)
            run('docker', 'rm', '-f', name, stdout=subprocess.DEVNULL)
