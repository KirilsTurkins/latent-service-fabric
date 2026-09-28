# Run a node in a Linux container

This guide builds a non-root image from an authenticated LSF release and runs the
node in the foreground. Use a Linux amd64 Docker host with a kernel of at least
6.8, readable CPU and memory pressure information, and private local storage.
The image supplies Ubuntu 24.04 and glibc; it cannot supply host kernel features.
On Windows, prepare the image in your Linux/WSL workspace.

The maintained qualification uses real local Docker containers and persistent
volumes. Azure Container Apps, Azure Files, NFS and SMB are **unqualified**. No
cloud resources or simulated cloud results are part of this profile. For a
deployment you can operate today, use a Linux host whose prerequisites you can
verify, with local durable storage and an explicitly configured ingress.

## Build from an authenticated release

Follow [Install LSF](../installation.md) to obtain the release directory, an
independently installed GitHub verifier, trusted Sigstore roots and an approved
publisher policy. These are the same trust inputs as the native installer. Keep
them outside directories writable by an application. This step checks the
publisher, exact release identities, archive contents and file modes before
creating a fresh Docker context:

```sh
python3 tools/prepare_container_runtime.py --release-directory "$ReleaseDirectory" --version "$Version" --publisher-policy "$PublisherPolicy" --trusted-root "$TrustedRoot" --verifier "$GitHubVerifier" --output "$ImageContext"
docker build --tag lsf-runtime:reviewed "$ImageContext"
```

Keep `build-inputs.json` with the resulting image ID. It records authentication
and recipe identities; it does not claim that building an image qualifies a
host. The image has root-owned executable files, UID/GID `10001:10001`, no Rust
toolchain, and a small Python preflight which becomes the native process using
`exec`. There is no shell supervisor or additional resident service.

## Prepare private configuration and storage

Use your reviewed [node configuration](../reference/standalone-node.md), private
operator client configuration and current [admission policy](../reference/publisher-trust.md).
The disposable signing keys in the qualification test are never deployment keys.
Set these container paths explicitly:

| Input | Container location | Required protection |
| --- | --- | --- |
| Node configuration | `/etc/lsf/node.json` | UID 10001, mode 0600, or root/group 10001, mode 0640; directory not writable by other users |
| Admission policy and operator client | Paths under `/etc/lsf` | Private reviewed files, read-only mount |
| Durable state | `/var/lib/lsf` | UID/GID 10001, directory mode 0700, persistent local filesystem |
| Compiler/cache files | `/var/cache/lsf` | UID/GID 10001, directory mode 0700, separate persistent writable mount |

Set `dataDirectory` to `/var/lib/lsf`, select `securityProfile` explicitly, and use
`supplyChain.mode: "enforced"` with your policy file. Configure `shutdownGraceMillis`
at most 5000 and allow at least ten seconds for container termination. Readiness
still requires a usable pressure source, private state and valid credentials
even if no capsules have been deployed.

For componentless static publications, `local-experimental-v1` avoids the isolated
compiler prerequisite. This remains the T0 local profile: it is **not** the
security boundary for untrusted guest execution. Static packaging and serving
do not activate an application Store. A privileged operator could still deploy
a capsule, so protect management and restrict its credentials accordingly.

For untrusted capsule execution, select `external-capsule-v1`. It additionally
requires an approved `/opt/lsf/release/bin/latent-aot-compiler`, its exact release
digest, a protected native AOT key and `/var/cache/lsf/native-blobs` and
`/var/cache/lsf/native-receipts`. The native check must establish the
Landlock/seccomp compiler profile. A container that lacks those capabilities
cannot silently fall back to the local profile. See
[execution security profiles](../runtime/execution-security-profiles.md).

## Check and start the node

Here `ConfigDirectory`, `DataDirectory` and `CacheDirectory` are the prepared
absolute host directories. On the Linux Docker host, run the same image and
mounts first with `check`:

```sh
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges --network host --mount "type=bind,source=$ConfigDirectory,target=/etc/lsf,readonly" --mount "type=bind,source=$DataDirectory,target=/var/lib/lsf" --mount "type=bind,source=$CacheDirectory,target=/var/cache/lsf" lsf-runtime:reviewed check
```

A successful result includes the observed kernel, libc, pressure visibility and
native security profile. It opens no serving listener. Start using those same
mount arguments, add `--name lsf-node --cpus 2 --memory 1g --pids-limit 128`, and
replace `check` with `serve`. Set log rotation in your Docker daemon policy.
Keep the management bind on literal loopback. Linux host networking lets a
reviewed local edge and operator reach that loopback endpoint; it grants no
public management access. For application traffic, configure the
[HTTP/TLS ingress](../reference/http-ingress.md) explicitly. A container's separate
loopback namespace cannot be reached merely by publishing an unrelated port.

Readiness is an authenticated operation:

```sh
docker exec lsf-node /opt/lsf/release/bin/latent --config /etc/lsf/client.json --output json node get "$NodeId"
docker stop --time 10 lsf-node
```

Require a known successful result, the expected node identity and
`data.inventory.health.ready: true`. A listening TCP port is insufficient.
SIGTERM reaches native PID 1, which owns bounded drain and orderly persistence.
Supervisors that require HTTP checks can use the optional
[private readiness adapter](readiness-probes.md), with explicit resource limits.
Retain all state and configuration together; use the
[stopped local backup and restore workflow](local-storage-recovery.md).
Wait for the configured supply-chain
clock lease before a restart; the persisted lease can reject an early restart.
Always wait for the old owner to exit before starting its replacement.
Use the [container handover procedure](container-handover.md) for overlap
rejection, interrupted replacement and explicitly eligible recovery.
Use the [private CI publishing workflow](headless-publication-ci.md) to change
publications and routes without restarting the runtime or exposing management.

## Diagnose a rejected host

| Diagnostic | Action |
| --- | --- |
| `run-as-uid-and-gid-10001` | Run the image with its declared user; correct mount ownership outside the runtime. |
| `kernel-6.8-or-newer-required` | Choose a supported host; changing the image cannot upgrade its kernel. |
| `readable-cpu-and-memory-pressure-required` | Make the required host pressure files readable through a supported deployment profile. Do not invent pressure values. |
| `private-node-storage-required` / `filesystem-lock-exclusion-unavailable` | Fix the mount or use a qualified local filesystem. A generic mount probe does not qualify remote storage. |
| `root-owned-release-executable-identity-mismatch` | Rebuild from the authenticated context; do not replace a binary in a running image. |
| `native-check-config-failed-check-profile-sandbox-and-protected-configuration` | Run the native `check-config` command privately and inspect its bounded diagnostic. Correct the policy, key or host sandbox; keep the selected profile. |

## Reproduce the maintained check

The `Native container runtime` workflow authenticates the released archive and
builds the image. Its finite drill generates fresh test identities, uses the
released CLI to sign and publish two actual sites, verifies GET/HEAD bytes and
ETags, stops and restarts the node on persistent volumes, and checks unchanged
routes and zero prepared capsules. It also verifies rejection of root startup.
Only its own labelled disposable resources are removed. Public receipts retain
the release/image identities, host preflight and measured restart duration.

This establishes the recorded local static-serving profile. It does not claim
external-capsule execution, managed-host support or power-loss durability for an
unqualified filesystem. The [architecture decision](../../adr/0053-run-authenticated-native-containers.md)
defines these support boundaries.
