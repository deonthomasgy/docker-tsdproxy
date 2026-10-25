# Security build — 2026-10-25

The last 1.x release is 1.4.7; it has no patched upstream 1.x image.
The owner authorized migration to 3.x. The selected upstream release is
3.0.0-beta.4 (2026-09-30), still a beta despite the GitHub release metadata.

## Package provenance and fixes

Both reported findings originate in Go modules linked into `tsdproxyd`, not
OS packages. The original 1.4.7 image also has a separate `healthcheck` binary
with vulnerable Go standard-library code. v3 uses one binary for both roles.

| Component | Deployed 1.4.7 | Upstream beta.4 | Our image |
|---|---|---|---|
| Go compiler / stdlib | 1.24.0 | 1.26.7 | 1.26.10 |
| golang.org/x/net | 0.37.0 | 0.59.0 | 0.60.0 |
| golang.org/x/crypto | 0.36.0 | 0.57.0 | 0.57.0 |

CVE-2026-25681 is an HTML-parser XSS flaw (fixed since x/net 0.55.0).
CVE-2026-39832 concerns SSH-agent key constraints (fixed since x/crypto
0.52.0). These advisory descriptions alone do not demonstrate arbitrary
server-side code execution. The deployed Docker connection is a local Unix
socket, not SSH. Both vulnerable versions are eliminated regardless of
reachability. Go 1.26.10 and x/net 0.60.0 also fix the additional HTTP/2,
TLS, certificate-validation and other findings in the full upstream scan.

The runtime is scratch, with a static Go binary and CA bundle copied from the
pinned Go builder. Bun, templ, Go, C tooling and package managers are absent
from the final image. Build images are pinned by digest, templ matches the
application's exact dependency version, and lockfiles are respected.

An additional regression test demonstrates that upstream Docker startup
silently changed `adminAllowLocalhost: false` to true. The test failed before
our fix and passes afterwards. Our build preserves this explicit access
policy, requiring authentication unless the operator deliberately opts in.

## Verification

Full unsuppressed Trivy JSON, critical/high table, build logs, regression logs
and govulncheck output are retained locally under `reports/` (gitignored).
The published release summary is `release.json`.

The first race-enabled run exposed unsynchronized authorization-header capture
in the upstream Proxmox mock HTTP server. A mutex now protects this test helper;
production Proxmox behavior is unchanged.

The Dockerfile test target runs `go mod verify`, `go test -race -count=1 ./...`
and `go vet ./...`. Container smoke tests check readiness, embedded assets,
unauthenticated denial, API-key access and healthcheck behavior without
production credentials, Docker socket access or Tailscale registration.
The upstream real-tailnet e2e suite is not run against production.

## Rebuild and publication

```sh
docker build --target test --progress=plain .
docker build --build-arg GIT_COMMIT="$(git rev-parse HEAD)" -t princeamd/tsdproxy:3.0.0-beta.4-security-r1 .
trivy image --scanners vuln --format json --output reports/after.json princeamd/tsdproxy:3.0.0-beta.4-security-r1
trivy image --severity CRITICAL,HIGH --exit-code 1 princeamd/tsdproxy:3.0.0-beta.4-security-r1
# Publish only after tests, runtime checks and scan review succeed:
docker push princeamd/tsdproxy:3.0.0-beta.4-security-r1
```

No production deployment is performed by the build or CI workflow. Publishing
uses an explicit beta version tag rather than moving `latest`.
