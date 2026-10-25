# Migration and rollout verification

## Deployment before the canary (2026-10-25)

Host: `orion-fs-host-1`. Compose project `tsdproxy`, service
`tailscale-docker-proxy`, container `tsdproxy-tailscale-docker-proxy-1`.
Image declaration: `/home/thomas/tsdproxy/docker-compose.yml:9`.

The pre-upgrade image was `almeidapaulopt/tsdproxy:latest`, resolving to the old 1.4.7
image ID `sha256:d26348ccb57ed41aa5fe37b6b1e2cb468c08c08ce02e18ba4720e74214020bc3`.
Rollback image: `almeidapaulopt/tsdproxy@sha256:6c04c1a2061fbc1a3939a1c880999c29d667bd91277c1320920c4bb259895395`.
The Compose file SHA256 observed was
`df86945a4852d30f673793e729620cfc132ea6631db9db5f5adac1f4e3ece23b`.
Recheck for drift before applying any changes.

The Docker socket is mounted at `/var/run/docker.sock`; named volume
`tsdproxy_datadir` is mounted at `/data`. No ports are published. Configuration
previously lived in the container's writable `/config/tsdproxy.yaml`, not a
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

## Procedure for additional hosts after owner authorization

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

## Completed canary: orion-fs-host-1

The owner first authorized a one-host rollout on 2026-10-25. Orion ran the
immutable image in `release.json` before the fleet rollout below. The full
sanitized record is [security/canary-orion-2026-10-25.json](security/canary-orion-2026-10-25.json).

- Private rollback backup: `/home/thomas/tsdproxy-security-backups/20261025T181353Z`.
  Contains the original Compose file, original private configuration, container
  inspection, and a stopped-volume `data.tar` with SHA256 checksum.
- Persistent configuration: `/home/thomas/tsdproxy/config/tsdproxy.yaml`, mounted
  read-only at `/config`. The generated administrator API key remains only in
  `/home/thomas/tsdproxy/config/api-key` (private file). Administrator access is
  restricted to the host owner's Tailscale user ID or that API key.
- `adminAllowLocalhost: false`, Funnel disabled, TLS verification enforced,
  existing provider names and data volume retained. No ports published.
- The image passed GitHub CI before canary verification completed.
- There were no enabled application routes on this host. Verification used a
  disposable Nginx backend and an ephemeral Tailscale node. Docker discovery,
  HTTP routing and certificate-verified HTTPS routing passed from a separate
  Tailscale workstation, with exact response matching and no hostname suffix.
- This host's existing default resolves explicitly declared ports through its
  target hostname. The temporary backend used `tsdproxy.autodetect=true` to
  select its private Docker IP; no host-wide routing defaults were changed.
- The temporary backend, proxy route, ephemeral state and tailnet node were
  removed. The proxy was then recreated through Compose and verified healthy
  with authenticated API/dashboard access and anonymous 403 responses.
- All 14 pre-existing state files matched the backup after recreation. Other
  running containers retained their IDs. No unexpected restarts occurred.

This verifies a real synthetic route, not migration of active application
routes: none were enabled on this host. The subsequent fleet rollout inventoried each additional host before updating it. The upstream tagged e2e
suite for all provider modes was not run against the production tailnet.

## Completed reachable fleet rollout (2026-10-25)

Following authorization to roll out everywhere, all **17 discovered TSDProxy
instances** now use the pinned image in `release.json`: 16 servers plus the
local workstation (`alpha-old`). Sixteen were upgraded in this phase; Orion
was already running the verified canary. All 17 passed Docker health and
authentication checks, with no unexpected restarts. Every Compose file pins
the same digest and mounts persistent private configuration.

See [the full fleet record](security/fleet-rollout-2026-10-25.json) for host
names, backup paths, route results and identity comparisons.

The inventory inspected Docker on 27 hosts. Ten had no TSDProxy container.
All online SSH-inaccessible tailnet endpoints matched known proxied
applications. Six **offline** hosts could not be inventoried:
`deployer`, `twingate-asl-1`, `kvm`, `client-sites-1`, `financial`, and `helpdesk`.
No claim is made about containers on those unavailable hosts.

### Compatibility handled

- For 1.4.7 hosts with routes, `tryDockerInternalNetwork: true` explicitly
  preserves v1's default auto-detection. Existing 3.x routing defaults were
  retained. This matters where a copied target hostname points at another host.
- 1.x defaulted unlabeled nodes to ephemeral; v3 defaults to persistent.
  Eleven legacy node IDs/IPs changed during replacement, with every existing
  route DNS name retained. The two other legacy route identities survived.
  All 25 route identities on previously running 3.x instances were preserved.
  Consumers should continue using the stable DNS names.
- Existing effective Funnel and TLS-validation exceptions were retained;
  ignored Funnel labels were not newly enabled. In particular, the existing
  `open-webui` Funnel route remains enabled on `lazy-ai`.
- `adminAllowLocalhost` is false throughout. Existing API keys were preserved;
  where none existed, a private key was generated in the mounted configuration.
  Do not print or commit these configurations or rollback archives.
- Docker installations expose either manifest IDs or image configuration IDs.
  Both were validated against the exact registry digest, architecture and source
  revision; all hosts run the same image artifact.

### Live verification and existing failures

All **31 previously working HTTPS routes** retained their successful response
or expected redirect, verified again from a separate tailnet client. There
were **zero new route regressions**. Seven failures were already present in
the baseline and remain outside this image rollout:

| Host | Routes | Existing result |
|---|---|---|
| `mintage-host-10` | `weasyprint-p7-mh7-3`, `weasyprint-p8-mh7-3` | HTTP 502 |
| `mintage-host-9` | `weasyprint-p7-mh9-1`, `weasyprint-p8-mh9-1` | Timeout |
| `mintage-sbm-test-1` | `weasyprint-p7-sbm`, `weasyprint-p8-sbm` | Timeout |
| `alpha-old` | `ws-orion` | Timeout |

Every upgraded host retains a private original Compose/config backup and a
consistent stopped-volume archive under `/home/thomas/tsdproxy-security-backups/`.
The exact directory is in the fleet record. Existing running application
containers retained their IDs. The deployment scripts under `scripts/fleet-*`
are specific to this release and these observed configurations; they check for
drift before changing a service and restore the old service/state on a failed
upgrade check. Baseline artifacts and detailed logs remain in local `reports/fleet/`.
