# Proposed migration — not deployed

## Observed production deployment (2026-10-25)

Host: `orion-fs-host-1`. Compose project `tsdproxy`, service
`tailscale-docker-proxy`, container `tsdproxy-tailscale-docker-proxy-1`.
Image declaration: `/home/thomas/tsdproxy/docker-compose.yml:9`.

Current image is `almeidapaulopt/tsdproxy:latest`, resolving to the old 1.4.7
image ID `sha256:d26348ccb57ed41aa5fe37b6b1e2cb468c08c08ce02e18ba4720e74214020bc3`.
Rollback image: `almeidapaulopt/tsdproxy@sha256:6c04c1a2061fbc1a3939a1c880999c29d667bd91277c1320920c4bb259895395`.
The Compose file SHA256 observed was
`df86945a4852d30f673793e729620cfc132ea6631db9db5f5adac1f4e3ece23b`.
Recheck for drift before applying any changes.

The Docker socket is mounted at `/var/run/docker.sock`; named volume
`tsdproxy_datadir` is mounted at `/data`. No ports are published. Configuration
currently lives in the container's writable `/config/tsdproxy.yaml`, not a
persistent mount. It contains a secret and must be backed up privately.
Legacy environment names are `DOCKER_HOST`, `TSDPROXY_AUTHKEY`, and
`TSDPROXY_HOSTNAME`. These remain supported by beta.4's config generator.

There is one Docker provider (`local`, local Unix socket) and one Tailscale
provider (`default`, standard control server); static `files` is empty.
No `tsdproxy.*` labels were present on the 22 inspected containers at discovery.
This does not establish whether the service is unused elsewhere or whether
labels will be added later.

## Compatibility changes

Reviewed upstream [v1→v2](https://almeidapaulopt.github.io/tsdproxy/docs/upgrading/from-v1/),
[v2→v3](https://almeidapaulopt.github.io/tsdproxy/docs/v3/upgrading/from-v2/),
and [beta.4 release](https://github.com/almeidapaulopt/tsdproxy/releases/tag/v3.0.0-beta.4)
notes against the tagged source.

- `files` becomes `lists` with a different list schema. This host has no lists
  to convert. Remove the empty legacy `files` field during config migration.
- Legacy Docker port labels are deprecated; beta.4 still implements them in
  `internal/targetproviders/docker/legacy.go`. Use `tsdproxy.port.N` for new
  labels. Reinventory labels before deployment.
- Dashboard/API access now requires an API key or authenticated Tailscale
  identity. Configure a specific `admins` allowlist. Keep
  `adminAllowLocalhost: false`; our build fixes the Docker override that
  silently enabled this bypass. No public dashboard port is needed here.
- Funnel and disabled upstream TLS verification require explicit provider
  opt-ins. None was observed on this host; keep the secure defaults.
- Shared nodes, VIP Services, Incus and Proxmox support are optional. Preserve
  existing per-proxy Tailscale mode, provider names and state; do not enable
  VIP Services or automatic ACL/device management as part of this upgrade.
- Dashboard UI is now htmx/templ; old custom JavaScript/CSS needs review.
- Automatic icon download requires GitHub access. Set `icons.download: false`
  if this is unwanted, and preseed icons if needed.

## Deployment procedure after owner authorization

1. Recheck the Compose file, running image, provider configuration and labels.
   Confirm the intended administrator's Tailscale identity and retain the
   current credentials privately. Do not commit keys or state to this repo.
2. Pull the immutable replacement image from `release.json`. Save the old
   Compose file and extract `/config/tsdproxy.yaml` to a root/user-only backup
   **before** recreating the old container. Stop only the proxy and take a
   consistent backup of `tsdproxy_datadir` before v3 writes to it.
3. Convert the config to current keys (`files`→`lists`), preserve `local` and
   `default` provider names, Docker host/target hostname, `/data/`, control URL
   and authentication. Explicitly keep `shared: false`, `services: false`,
   `adminAllowLocalhost: false`. Mount the converted private config directory
   at `/config`, while retaining the same `/data` volume and Docker socket.
4. Change only this service's image to the version plus digest from
   `release.json`, add its `/config` mount, and validate Compose. Do not replace
   the existing Compose project with the generic upstream example.
5. Recreate only `tailscale-docker-proxy` with `--no-deps`. Check readiness,
   authentication enforcement, Docker discovery, expected Tailscale node
   identities and actual routed HTTP/TLS traffic from an authorized client.
   Confirm no new `-1` duplicate node names or unintended Funnel exposure.
6. On failure, stop v3, restore the old private config and the **pre-upgrade**
   data-volume backup, restore the old Compose definition with the pinned
   rollback image, and recreate only this service. Do not start v1 on state
   modified by v3 without restoring the backup.

Real tailnet registration, certificate issuance and application routing must
be validated during the authorized canary; local tests use no production
credentials or Tailscale state.
