# Native LSF bundle

Experimental standalone software, not production or hostile-multitenancy
certification. A bundle is usable only after its publisher identity, exact
source, signatures and release-specific acceptance evidence are approved.
The historical `0.1.0-alpha.3` release is source-only; this tooling does not
retroactively turn it into a verified binary release.

## Prerequisites and independent bootstrap trust

The initial candidate targets **Ubuntu Server 24.04, Linux x86_64, kernel 6.8
or newer, glibc 2.39 or newer, SSE2, Python 3.12 or newer**, local POSIX
filesystems with descriptor/xattr inspection, exclusive file locks and directory
fsync, and readable `/proc/pressure/cpu` and `/proc/pressure/memory`.
Install OS packages `python3`, `openssl`, `libc6`, `libgcc-s1`, `coreutils` and,
for a persistent server, `systemd` and `passwd` using your trusted OS provisioning
process. `ldd` comes from `libc-bin`. Isolated compilation additionally requires
working Landlock ABI 3 and seccomp; the real compiler probe, not a kernel version
comparison, decides availability. No Rust, guest compiler, Docker, Podman,
Kubernetes, registry, application provider, or external orchestrator is needed
to install and run the native binaries. Other distributions, ARM64 and musl are
not declared supported by this first candidate.

Before executing **any downloaded Python or shell code**, independently provision
OpenSSL and a publisher-approved Ed25519 public key. Obtain the exact expected
SHA-256 fingerprint of its DER SubjectPublicKeyInfo through a separately trusted
operator channel. A key or checksum downloaded beside the bundle is not trust.
The project must approve a real publisher fingerprint before release; no key,
fixture identity, default trust policy or private signing key is supplied here.

Provision these five release files into a private staging directory owned by
the identity that will execute the installer:

- `lsf-<version>-x86_64-unknown-linux-gnu.tar.gz`
- `lsf-install.pyz`
- `release.json`
- `SHA256SUMS`
- `SHA256SUMS.sig`, a raw Ed25519 signature of the exact `SHA256SUMS` bytes

For privileged installation, verify in a **root-owned 0700 directory**, not in
another user's writable downloads directory. Use an initial local SSH session
and `sudo -i`; copy the five fixed files into that directory with ordinary OS
tools, then change into it. Public trust material must have root-owned,
non-writable ancestors. For rootless evaluation, use a private user-owned staging
directory and a root-owned or same-user protected trust path.

Set `VERSION`, `PUBLISHER_KEY` and `EXPECTED_PUBLISHER_SPKI_SHA256` to the exact
independently approved release inputs. These are deliberately not moving URLs,
auto-discovered keys or invented fingerprints. Then run the following using
only independently installed OS tools:

```bash
set -eu
umask 077
actual=$(openssl pkey -pubin -in "$PUBLISHER_KEY" -outform DER | sha256sum)
test "${actual%% *}" = "$EXPECTED_PUBLISHER_SPKI_SHA256"
openssl pkeyutl -verify -pubin -inkey "$PUBLISHER_KEY" -rawin \
  -in SHA256SUMS -sigfile SHA256SUMS.sig
sha256sum --check --strict SHA256SUMS
python3 -I ./lsf-install.pyz verify --version "$VERSION" \
  --release-directory "$PWD" --publisher-key "$PUBLISHER_KEY"
```

Only now may the authenticated bootstrap run. It repeats signature verification,
binds version/source/target/toolchain/engine to the manifest, hashes the opened
archive descriptor, and accepts only bounded manifest-listed regular USTAR
files. There is no network access, toolchain download or `curl | sudo sh` path.
The entire process works disconnected after OS and verification prerequisites
and release files have been provisioned.

## Rootless evaluation

Run as an ordinary user. This explicitly selects controlled local workloads and
does not establish external publisher admission or compiler isolation:

```bash
python3 -I ./lsf-install.pyz install --directory "$HOME/lsf-evaluation" \
  --version "$VERSION" --release-directory "$PWD" --publisher-key "$PUBLISHER_KEY" \
  --profile local-experimental-v1 --acknowledge-experimental --port 50051
python3 -I ./lsf-install.pyz run-local --directory "$HOME/lsf-evaluation"
```

The second command stays in the foreground and replaces the helper with
`latentd`. Keep that terminal open; use another local terminal for administration.
Ctrl-C initiates bounded drain. This path does not create an account, change
`/etc`, install a service or invoke systemd. Use the generated private
`$HOME/lsf-evaluation/config/client/client.json` with the packaged CLI. The
foreground command holds one installation-local lock; stop it before changing
or removing that evaluation. Running the executable directly bypasses this
installer coordination and is not the documented lifecycle path.

## Persistent server

The installer creates or strictly validates the dedicated non-login `lsf` system
account and exclusive primary group. It never runs the node as root or recursively
chowns pre-existing trees. Untracked configuration/data roots, symlinks, hard links,
extended ACLs and unexpected ownership or permissions are refused, not repaired.

For controlled local workloads, run the following as root after verification:

```bash
python3 -I ./lsf-install.pyz install --system --version "$VERSION" \
  --release-directory "$PWD" --publisher-key "$PUBLISHER_KEY" \
  --profile local-experimental-v1 --acknowledge-experimental --start --enable
```

For external capsules, independently provision a complete current admission
policy, then explicitly select the enforced profile:

```bash
python3 -I ./lsf-install.pyz install --system --version "$VERSION" \
  --release-directory "$PWD" --publisher-key "$PUBLISHER_KEY" \
  --profile external-capsule-v1 --trust-policy /root/lsf-admission-policy.json \
  --start --enable
```

This requires the **actual** `external-capsule-v1` checks: enforced admission,
protected credentials/trust, approved exact compiler, protected host key,
Landlock/seccomp readiness, compatible host ABI/runtime and authenticated native
loading. The installer creates one fresh 32-byte host key exclusively for this
profile, outside data and cache. Existing keys are never overwritten. Missing
trust or failed checks leave the transaction unactivated. Supply the missing
prerequisite and repeat the exact authenticated command with `--resume`; do not
remove the profile marker, weaken the profile, use fixture signing identities,
regenerate a key, or enable in-process compilation to get past a failure.

Omitting `--start` never starts a stopped service. Omitting `--enable` never enables
boot startup. Existing enablement is preserved on reinstall/upgrade. A start
must pass finite authenticated `latent node get` activation-readiness checks;
`active`, an open port, or successful `check-config` alone is not readiness.

### Layout and credentials

| Path | Ownership and purpose |
| --- | --- |
| `/opt/lsf/releases/<version>` | Root-owned immutable native tools, example, metadata and license texts. |
| `/opt/lsf/current` | Installer-managed relative pointer, never service-writable. |
| `/opt/lsf/installed.json` | Non-secret version, file, publisher and owned-root inventory. |
| `/etc/lsf/node.json` | Root:`lsf` 0640 credential-bearing configuration; no live reload. |
| `/etc/lsf/client/client.json` | Root-only 0600 client credential in a root-only directory. |
| `/etc/lsf/private/native-aot.key` | `lsf` 0600, private service-owned parent, external profile only. |
| `/var/lib/lsf` | `lsf` 0700 persistent catalogs, profiles, deployments and operation identities. |
| `/var/cache/lsf` | `lsf` 0700 bounded replaceable native caches; never key authority. |
| `/etc/systemd/system/lsf.service` | One root-owned service for the node, not per capsule. |

The existing protocol uses one unique random bearer credential copied into
separately protected node and client documents; these are not reusable project
defaults. Tokens and key bytes never appear in arguments or normal diagnostic
output. The service readiness helper creates a private short-lived client file
from the node's already-authorized credential and removes it after the read-only
checks. Administration stays on literal IPv4 loopback. No public bind, firewall
rule, reverse proxy, TLS bypass, cluster, or application HTTP ingress is configured.

## First retained invocation

For the local profile, in the second local terminal set `PREFIX` to `/opt/lsf`
(root administrator) or `$HOME/lsf-evaluation` (ordinary user), and `CLIENT` to the
corresponding private client path above. Create a private results directory:

```bash
umask 077
mkdir -m 700 lsf-first-invocation
cd lsf-first-invocation
CLI="$PREFIX/current/bin/latent"
EXAMPLE="$PREFIX/current/examples/echo"
"$CLI" --config "$CLIENT" --output json release publish \
  --manifest "$EXAMPLE/capsule.json" --component "$EXAMPLE/echo-capsule.wasm" \
  --contracts "$EXAMPLE/contracts.json" --operation-id native-example-publish \
  --expected-generation 0 > published.json
python3 - "$EXAMPLE/deployment.json" <<'PY'
import json, sys
with open(sys.argv[1]) as source:
    deployment = json.load(source)
with open("published.json") as source:
    release = json.load(source)["data"]["release"]
deployment["spec"]["release"] = release["digest"]
deployment["spec"]["publication"] = release["publication"]["id"]
with open("deployment.json", "x") as target:
    json.dump(deployment, target)
PY
"$CLI" --config "$CLIENT" --output json deployment apply deployment.json \
  --expected-generation 0 --expected-state-version 0 --operation-id native-example-deploy
"$CLI" --config "$CLIENT" --output json invoke --service examples/echo \
  --contract examples:echo/api@0.1.0 --function echo --input "$EXAMPLE/input.json" \
  --activation-id native-example-first --wall-time-ms 5000 --rpc-timeout-ms 5000
```

The zero deployment-state precondition is for a fresh node only. Read the current
`deployment get echo-production --operation-snapshot` state on a nonempty node;
never replace a stale precondition automatically. Each mutation is issued once.
On an uncertain response, query the exact publication/deployment operation ID
or activation ID; do not blindly replay. **Do not delete this deployment.**
After server reboot, invoke again with a new activation ID to exercise retained
publication and deployment identities, not a new publish/deploy sequence.

Raw publication is not accepted by enforced admission. For the external profile,
an authorized publisher must separately supply a signed package/evidence for
the exact bundled component and the operator's policy. Use `release publish-package`
with that evidence and retain the returned publication reference. Neither the
runtime bundle signature nor its SBOM grants capsule publication authority.
No private package-signing key or expiring synthetic trust is installed by default.

## Status, drain and hardening

```bash
systemctl status lsf.service --no-pager
journalctl -u lsf.service -n 80 --no-pager
sudo -u lsf python3 -I /opt/lsf/current/lsf-install.pyz preflight --system
sudo -u lsf python3 -I /opt/lsf/current/lsf-install.pyz readiness --system
systemctl restart lsf.service
systemctl stop lsf.service
```

SIGTERM is the drain/shutdown operation. The installer accepts node drain
intervals up to five seconds. The service allows 90 seconds for the runtime's
separate cleanup/transport/worker joins, then terminates the entire owned cgroup.
`KillMode=mixed` initially signals the main node so it can cancel and reap its
compiler children; forced killing is failure, not a clean shutdown proof. Check
the node's final `stopped` record with `clean:true`. Restart bursts are bounded.

The unit restricts privileges, writable paths and core dumps. It deliberately
does not use `MemoryDenyWriteExecute`, PID hiding, a second blanket syscall filter
or private-user remapping: Wasmtime executable mappings and the approved compiler's
proc/descriptor authentication must remain possible. Do not weaken the compiler
sandbox or run as root to accommodate a hardening failure. Service resource
limits are whole-node administrative limits, not per-activation budgets or measured
RSS. Dormant deployments allocate no additional processes, services or listeners.

## Reinstall, upgrade and recovery

Repeat the exact signed install command for idempotent same-version repair/check;
configuration, credentials, keys and catalogs remain unchanged. Conflicting
operations serialize under a descriptor lock. A failure or interruption before
commit retains `transaction.json`; retry **the same verified release and profile**
with `--resume`. There is no automatic binary rollback or profile fallback.
Corrupt journals, partial credential/key writes, unknown files or substitutions
fail closed and require a stopped-node restoration of a verified complete backup.

Different versions require `--upgrade` and a publisher-authenticated exact
predecessor entry matching version, source commit and archive digest, unchanged
engine/compiler identity, no migration and successful candidate `check-config`.
The initial compatibility policy has **no cross-version predecessors**; it
therefore rejects every cross-version upgrade/downgrade until a reviewed pair
with actual migration/retention evidence is added. A running server upgrade also
requires `--start`. Four release inventories are the hard retention ceiling.
New examples never overwrite operator configuration. Compiler approval or
publisher-key rotation is not silently performed by an upgrade.

Before a supported upgrade, stop the service, verify `MainPID=0` and an empty
owned compiler cgroup, and make a private, consistent backup of `/etc/lsf`,
`/var/lib/lsf`, the installed manifest and exact verified release. Include the
profile marker, admission generations, clock floors and operation ledgers.
Do not copy live catalogs and call that a consistent backup. Keep backups
outside caches and protect them like credentials. Restoring requires a stopped
node and its compatible original release/config/key/state set. Switching to an
old executable does not undo a storage-format migration. Runtime upgrade/recovery
is separate from capsule rollout/rollback.

## Removal and separately confirmed purge

Keep the independently verified bootstrap/release files outside the installation.
Use that bootstrap as root for system removal or as the evaluation owner for
local removal:

```bash
python3 -I ./lsf-install.pyz remove --system
python3 -I ./lsf-install.pyz status --system
python3 -I ./lsf-install.pyz purge --system --confirm-installation "$INSTALLATION_ID"
```

For a rootless installation, replace `--system` with
`--directory "$HOME/lsf-evaluation"` after stopping the foreground node.
Removal stops/disables only the installed node service, removes only verified
tracked runtime/unit files, and retains config, client credentials, keys, catalogs
and caches. Reinstall the same verified release to recover the retained deployment.
Modified binaries or units are not deleted blindly. A stopped partial removal
is resumable by repeating removal.

Purge is a separate command, requires the non-secret installation ID returned by
install/status and a completed removal, validates the original root inode/device
identities, refuses links, mounts, unexpected types and excessive walks, and
deletes only that installation's owned roots. Interrupted purge is resumable with
the same ID. The dedicated account and installer lock directory are retained to
avoid UID reuse and lock-inode races. Purge is irreversible without a backup.
