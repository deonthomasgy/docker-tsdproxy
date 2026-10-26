# TSDProxy security build

Our maintained image of TSDProxy **3.0.0-beta.4**, published as
[`princeamd/tsdproxy`](https://hub.docker.com/r/princeamd/tsdproxy).
Source: [deonthomasgy/docker-tsdproxy](https://github.com/deonthomasgy/docker-tsdproxy).

The current source build uses Go 1.27.3, Tailscale 1.104.2,
`golang.org/x/net` 0.60.0 and
`golang.org/x/crypto` 0.57.0. The final scratch image contains only the static
server and CA certificates; compilers, package managers and frontend build
dependencies stay in build stages. Docker startup preserves
`adminAllowLocalhost: false`; authenticated dashboard access is the default.

- [Build, tests and security findings](SECURITY-BUILD.md)
- [Migration, rollback and fleet rollout](MIGRATION.md)
- [Verified fleet: 17 healthy instances](security/fleet-rollout-2026-10-25.json)
- [Upstream provenance](UPSTREAM.md)
- [Original upstream README](UPSTREAM-README.md)

Published image: `princeamd/tsdproxy:3.0.0-beta.4-security-r1`.
The TS-2026-013 fix is in source revision `3.0.0-beta.4-security-r2`;
it requires rebuilding and redeploying. `release.json` and the fleet report
still describe the previously published r1 image.
3.x remains a beta. Publishing this image does not deploy it.

## Build and verify

```sh
docker build --target test --progress=plain .
docker build --build-arg GIT_COMMIT="$(git rev-parse HEAD)" -t princeamd/tsdproxy:3.0.0-beta.4-security-r2 .
trivy image --severity CRITICAL,HIGH princeamd/tsdproxy:3.0.0-beta.4-security-r2
```

The test target runs all regular Go tests with the race detector, verifies
module checksums, and runs `go vet`. The upstream `e2e` build-tag suite needs
an isolated test tailnet and is separate from these tests.
