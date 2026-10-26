# Security build — 2026-10-26 (r2 source update)

[Tailscale TS-2026-013](https://tailscale.com/security-bulletins#ts-2026-013)
requires rejecting compromised eMudhra intermediate certificates even when
the host CA store still trusts them. Update the embedded Tailscale module
from 1.102.5 to 1.104.2 and require Go 1.27.3 in `go.mod`, the digest-pinned
production builder and the development builder. This is a Go `crypto/x509`
fix, so updating only the module or its displayed version is insufficient.
The Docker Tailscale version stamp is updated to match the actual dependency.

[Go 1.26.10](https://go.dev/doc/devel/release#go1.26.10), used by the r1 Docker
builder, already contains the distrust backport. The previous `go.mod` still
permitted unpatched Go 1.26.7 source builds. Raising the minimum closes that
gap and satisfies Tailscale 1.104.2's
Go 1.27.3 requirement; the old version declarations alone do not establish
that the published r1 image was vulnerable to this bulletin.

The preceding Services, Serve/Funnel and 4via6 bulletins were already covered
by 1.102.5. TS-2026-012 concerns the separate C `libtailscale` bindings;
TSDProxy uses Go `tailscale.com/tsnet`, not those bindings.

`TestSecurityBuild_TS2026013_BUG` failed before the upgrade on the dependency,
module Go requirement and both Docker builders. It guards these minimum
versions, the actual test compiler and consistency of the Docker version
stamp; it does not simulate a forged certificate.

The new build revision is `3.0.0-beta.4-security-r2`. The existing
`release.json`, committed scans and fleet report remain historical r1
evidence; this source update does not publish or deploy r2.

Validation of the local amd64 r2 image:

- All 26 packages with tests passed with `-race -count=1`; module checksum
  verification and `go vet ./...` passed in the Docker test target.
- Offline smoke checks passed: ten HTTP checks, binary healthcheck and clean
  SIGTERM shutdown. Real-tailnet E2E tests were not run.
- Trivy confirmed embedded Go 1.27.3 and Tailscale 1.104.2, with zero critical,
  high, medium or low findings. The existing unfixed `GO-2026-5932` OpenPGP
  module advisory remains visible at unknown severity; the updated server's
  dependency list contains no OpenPGP packages.
- Logs, the unsuppressed scan and server import list are retained locally
  under `reports/ts2026013/` (gitignored).

## Previous release verification — 2026-10-25 (r1)

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
The published release summary is `release.json`; the full final report and
critical/high output are committed under `security/`.

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

## Scan result and remaining advisory

All 25 packages with tests passed with the race detector; module verification
and vet passed. The container passed 10 HTTP checks, its healthcheck and clean
shutdown. The published amd64 manifest matches the locally tested image.

Full Trivy comparison (package/advisory occurrences, no suppression):

| Severity | Deployed 1.4.7 | Upstream beta.4 | Our image |
|---|---:|---:|---:|
| Critical | 2 | 0 | 0 |
| High | 74 | 5 | 0 |
| Medium | 94 | 13 | 0 |
| Low | 7 | 1 | 0 |
| Unknown | 2 | 1 | 1 |

The sole remaining report is `GO-2026-5932`, covering deprecated
`golang.org/x/crypto/openpgp` (no fixed version). `go list -deps ./cmd/server`
contains no OpenPGP package; `go mod why golang.org/x/crypto/openpgp` reports
that this module does not need the package. Source-mode govulncheck 1.9.0
reports it at module level only, with no imported package or call trace.
Binary-mode govulncheck conservatively reports the advisory's wildcard package
symbols, so that output alone is not evidence of a reachable call path.

Disposition: retained module advisory, no reachable OpenPGP code in this
server build. The rest of x/crypto is needed by Tailscale/SSH; removing the
whole module would break those features. Keep this advisory visible and
recheck imports on dependency updates. No Trivy ignore or VEX suppression
was added. There are zero findings with an available fixed version.

Run the offline container checks with:

```sh
python3 scripts/smoke.py princeamd/tsdproxy:3.0.0-beta.4-security-r1
```

This runs with `--network none`, ephemeral data, a disposable test API key,
and no production mounts. It also checks clean SIGTERM shutdown.
