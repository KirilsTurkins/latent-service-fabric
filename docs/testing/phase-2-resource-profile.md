# Phase 2 resource profile

`phase2-dormant-32-r1` is a fixed Linux resource experiment for gate #158.
A profile definition
is not a passing result. The gate remains pending until its retained evidence
has been reviewed alongside the other Phase 2 checks.

The runner starts an actual `latentd`, uses actual authenticated `latent`
commands, and owns every process through exit and reap. It does not build,
install, contact a registry, start a benchmark service, or retry failed
mutations. The separate [operator workflow](../phase-2-operator-workflows.md)
covers registry transfer and rollout operations. This profile measures dormant
catalog growth and reclaimed execution ownership.

## Frozen workload and limits

These values are fixed in `tools/phase2_gate_resource_profile.py::PROFILE`
before execution. Changing one creates a new profile revision; a failing
observation does not authorize raising a limit.

| Input or owner | Fixed value |
| --- | --- |
| Signed component/package identities | 32 |
| Simultaneously stored deployments | 16, one tenant and service |
| Releases referenced by deployments | Exactly the first two; the other 30 receive no Invoke |
| Preparation | Portable Wasmtime path, cache 2 entries, 1 concurrent preparation |
| Actual Invokes | Exactly 32 on a passing run: 2 warm calls, then 30 cohort calls |
| Control commands | At most 256, charged before spawning a caller |
| Work deadline | 300 seconds including identity/fixture reads and work; passing total including shutdown and final validation at most 310 seconds |
| OS samples | Exactly 12: 3 per phase, with 50 ms between observations |
| Quiescence | At most 10 inventory observations per sample, 100 ms between unsuccessful observations |
| Execution topology | One runtime worker, one control worker, one standard cell, cell queue 2 |
| Catalog ceilings | 64 releases, 32 deployments |
| Audit | One durable owner: 512 records, 8 MiB disk, queue 8, query owners 2 |
| Rollouts | One shared coordinator: active 2, retained 8, stages 4, receipts 32, metadata 1 MiB, queue 2 / 256 KiB, response owners 2 |
| Canary | Windows 2, starts/window 32, total starts 64, live samples 4, snapshot owners 2; no active plan in this experiment |
| Receipt | At most 256 KiB, new file only |
| Fixture inventory | At most 2,048 visited entries / 8 MiB of ordinary files |
| Process observation | At most 256 tasks / 4,096 descriptors; each sample at most 2 seconds / 4 MiB of proc data |
| Network tables | At most 1 MiB and 8,192 rows each, bounded to the node's socket inodes |

The node has explicit finite fuel, memory, wall time, log, terminal-history,
clock-lease and shutdown limits. The receipt retains the exact public config
and a digest of the complete config. Credentials are excluded from the receipt.
The fixed test credential is supplied only to temporary node/client config files.

The deadline is checked during bounded hash/inventory loops and before owned
work. Signal cancellation is installed before identity reads and remains active
through final receipt publication. Local filesystem syscalls cannot be forcibly
preempted by Python; these are cooperative deadlines on trusted local inputs,
not a guarantee against a stalled filesystem. Failed child work retains the
existing process owner's separate five-second cleanup deadline through actual
reap. A late cleanup never produces a passing 310-second receipt.

All 32 components come from the same tiny validated fixture with a distinct,
inert custom section. The exporter regenerates the SBOM and signs each exact
package with fresh publisher and builder keys, then verifies it against the
fresh joint policy before writing it. No private signing key is exported.
The signed observation is **synthetic test evidence**, not a claim that an
observed production build produced the fixture.

## Schedule and acceptance

1. Publish the first two packages. Deploy and Invoke each independently through
   the same deployment ID. This warms the two images and fixed helpers.
   Take three **baseline** samples.
2. Publish the remaining 30 packages. Add 15 deployment IDs, alternating the
   first two releases, for 16 total. Verify exact release/deployment counts and
   associations. Make no Invoke during this growth. Take three **dormant** samples.
3. Make 30 sequential real Invokes with fixed unique activation IDs. Validate
   the concrete result `[7]`, exact component membership and unchanged route
   generation for every success. There is no random-until-coverage loop.
   Take three **reclaimed** samples.
4. Delete all 16 deployments with exact object and catalog state preconditions.
   Look up each durable delete receipt, verify no routes remain, and verify
   that all 32 admitted release records remain. Take three **unrouted** samples.
5. Send SIGTERM while the owner still reserves the unreaped node PID. Validate
   the bounded `stopped.report`, observe zero exit status, and finish/reap the
   maintained process-group owner. Remove temporary outputs.

At every sample, the current node inventory must be complete and available.
Guest stores, host states, component instances, temporary buffers, cancellation
probes, cell leases, instance reservations, preparation reservations, queue and
quota usage must be zero. No rollout command, canary window/sample owner or
cleanup slot may remain active. The inventory's own connection, RPC and control
observation may each occupy at most one slot; these are reported explicitly.

OS sampling occurs after the inventory caller has exited and been reaped.
The node PID, start ticks, group/session and executable identity must still
match. Task children must be absent. There must be exactly one listening TCP
socket. Threads, tasks, descriptor count, socket count, listener count and
descendant count must match the warm baseline across all twelve samples.
No missing observation is converted to zero. A raced, inaccessible or
oversized proc observation fails the experiment instead of extending its bounds.

The configured topology and all non-observation active owner counts must also
match the warm baseline. Preparation-cache misses must not increase after
warming the two images. RSS, kernel high-water RSS, CPU ticks and I/O bytes
are retained as observations. **RSS is neither a logical allocation counter
nor required to fall**: retained catalog data, prepared images, audit history,
allocator behavior and page residency remain relevant after invocation cleanup.

Shutdown additionally requires actual audit/coordinator joins, no live compiler
workers/jobs/waiters or ready reservations, a joined cleanup driver, zero live
guest objects and zero accepted work. A successful signal send is insufficient.
If cleanup fails, the receipt cannot pass. Failed runs retain the bounded phase,
failure category and any observations completed before failure.

## Running and retaining evidence

Use already-built Linux binaries and Python 3.13 or newer. The orchestrator
runs builds and this explicit ignored test; ordinary unit tests emit no fixture:

```sh
LSF_PHASE2_RESOURCE_FIXTURE_ROOT=/absolute/new-fixture \
  cargo test -p latent-policy export_phase2_resource_fixture -- --ignored
```

The output root must not exist. Run within the first five minutes of export:
publisher/builder proof age is 600 seconds, and the runner requires at least
300 seconds of remaining proof freshness. These clocks are not extended by
the experiment.

The build owner supplies a closed identity file describing the actual supplied
binaries, using lowercase SHA-256 values with the `sha256:` prefix:

```json
{
  "schemaVersion": "latent.phase2.resource-build.v1",
  "sourceRevision": "<40 lowercase hexadecimal Git revision>",
  "cargoLockSha256": "sha256:<64 lowercase hexadecimal digits>",
  "rustcVersion": "rustc <actual compiler version>",
  "buildProfile": "debug",
  "cliSha256": "sha256:<actual latent binary digest>",
  "nodeSha256": "sha256:<actual latentd binary digest>"
}
```

```sh
python3 tools/phase2_gate_resource.py \
  --cli /absolute/latent --node /absolute/latentd \
  --fixture-root /absolute/new-fixture \
  --build-identity /absolute/build-identity.json \
  --output /absolute/new-resource-receipt.json
python3 tools/phase2_gate_resource.py \
  --validate /absolute/new-resource-receipt.json
```

The runner verifies the actual binary and Cargo.lock bytes, hashes its collector,
shared owner helpers and profile sources, hashes the complete bounded fixture,
and retains package/component/manifest, policy-file, config and build identities.
The source revision/compiler association is the build owner's assertion and
must be tied to its retained build log/CI artifact; this JSON alone does not
prove how the binary was built. Successful execution also verifies the live
node executable's bytes and inode against the supplied binary.

The receipt includes no raw logs, credential contents, private keys or temporary
filesystem paths. Full fixture paths are represented only by an inventory digest.
All potentially large counters are preserved without floating-point conversion.
The validator rejects missing samples, changed profiles, missing identities,
resource growth, extra preparation, incomplete cleanup, incorrect catalog counts
and invocation associations. Keep unsuccessful receipts alongside the eventual
reviewed result; do not overwrite a failed result with a later attempt.

## Scope of the result

This is a 32-release / 16-deployment dormant profile, not a 100k claim, throughput
target, soak guarantee or proof of arbitrary hostile-process containment.
Only two distinct runtime images are warmed. Process ownership assumes trusted
test executables without deliberate session escape; it does not adopt unrelated
PIDs or promise cleanup after supervisor SIGKILL.

Native image mapping leases, compiler sandbox/child limits, persistent-cache
authentication and final-start trust expiry remain separate focused tests.
Their logical counters must not be inferred from this portable profile's RSS.
The profile retains authoritative release/audit history after route removal:
reclaimed execution objects and intentionally retained control data are distinct.
Phase 3 provider and web capabilities are outside this gate experiment.
