# Exercise provider denial, rotation and uncertain recovery

## Outcome and supported scope

Use three real, disposable TLS services to understand why a denied operation,
a rotated credential, a lost reply and a clean local shutdown mean different
things. Run the existing S3, Vault and NATS conformance scenarios, inspect their
actual guest/provider ownership, and recognize when recovery must retain an
uncertain outcome rather than retry a mutation.

This is a Linux x86_64 **development contributor** learning path under
[#359](https://github.com/KirilsTurkins/latent-service-fabric/issues/359).
It uses the maintained Rust embedding and actual Wasmtime guest fixtures;
NATS triggers also use the real local activation manager. It is not a separate
`latentd`/SDK walkthrough or instructions to configure a production provider.
Standalone management composition remains with
[#226](https://github.com/KirilsTurkins/latent-service-fabric/issues/226).
Passing policy CRUD alone does not install an external provider.

Docker runs **only the owned external test services**. The LSF harness executes
natively on the Linux host. Docker, a provider account and a source checkout are
not prerequisites for [native LSF installation](../../packaging/linux/INSTALL.md).
No paid hosted provider, existing user container or operator credential is used.

## Prerequisites and complete source

The commands select development source
`55ba1c301518c670820d482bcc991780167e903c`, the merged base reviewed for this
documentation handoff. Start in a new, clean, private checkout at that exact
commit; do not reset an existing worktree. Use
[Rust 1.97.1 and the pinned contributor tools](../development/toolchain.md),
Python 3.13.5, OpenSSL, GNU `timeout` and a working Docker CLI/daemon. The selected
real-provider targets are Linux x86_64 gated; a Windows build with zero matching
tests is not execution evidence. Use only this checkout's Cargo target.

The [current executed receipt](../evidence/provider-guide-2026-09-21.json)
records all 19 selected tests and owned-service cleanup. Its CI merge commit
`5f192095e761c5899626bc83eec77d128eba55f7` has the same Git tree as this reviewed
base. The separate Angular T1 step failed; that result does not alter these
completed provider steps. The earlier `05360c50` receipt remains historical.
Standalone management composition has its own maintained node workflow.

Follow these maintained sources while running the scenarios; do not copy their
test credentials or synthetic package trust into an installed node:

| Scenario | Complete runner and configuration | Actual guest and failure cases |
| --- | --- | --- |
| Immutable S3 blobs | [Owned TLS runner](../../tools/run_s3_blob_tests.py), [server setup](../../tools/s3_test_support.py), [provider configuration](../../crates/latent-wasmtime/tests/s3_blobs/setup.rs) | [Multipart, cross-tenant, immutable range and recovery tests](../../crates/latent-wasmtime/tests/s3_blobs.rs), using the maintained [blob guest](../../crates/latent-wasmtime/tests/local_blobs/component.rs) |
| Vault KV-v2 reads | [Owned TLS runner](../../tools/run_vault_secret_tests.py), [server setup](../../tools/vault_test_support.py), [provider configuration](../../crates/latent-wasmtime/tests/vault_secrets/setup.rs) | [Version/rotation/revocation guest sequence](../../crates/latent-wasmtime/tests/vault_secrets.rs), [transport interruption](../../crates/latent-wasmtime/tests/vault_secrets/transport.rs), [redaction checks](../../crates/latent-wasmtime/tests/vault_secrets/audit.rs) |
| NATS publication and external triggers | [Owned TLS runner](../../tools/run_nats_event_tests.py), [server/consumer setup](../../tools/nats_test_support.py), [publication fixture](../../crates/latent-wasmtime/tests/nats_events/fixture.rs), [trigger fixture](../../crates/latent-wasmtime/tests/nats_triggers/fixture.rs) | [Guest publication](../../crates/latent-wasmtime/tests/nats_events.rs), [lost publication replies](../../crates/latent-wasmtime/tests/nats_events/faults.rs), [trigger overload/revocation](../../crates/latent-wasmtime/tests/nats_triggers/acceptance.rs), [trigger recovery/shutdown](../../crates/latent-wasmtime/tests/nats_triggers/recovery.rs) |

The runners use fixed image digests, unique ownership labels, loopback-only
published ports, finite memory/PID/log/storage limits and short-lived fixture
TLS material. Their credentials are explicit public test material, not an
ambient cloud credential chain. Keep the checkout/review directory private and
never pass a real token, secret value or management bearer into this scenario.

## 1. Build the existing four test targets once

The same Cargo JSON artifact inventory selects the actual executable for each
runner, avoiding four recompiles. A manifest is build output, not an execution
receipt; the next step must actually run its selected tests.

```bash
set -euo pipefail
umask 077
test "$(uname -s)" = Linux
test "$(uname -m)" = x86_64
test -z "$(git status --porcelain=v1 --untracked-files=normal)"
SOURCE_COMMIT=55ba1c301518c670820d482bcc991780167e903c
test "$(git -c gc.auto=0 rev-parse HEAD)" = "$SOURCE_COMMIT"
export CARGO_TARGET_DIR="$PWD/target"
PROVIDER_REVIEW=$(mktemp -d "${TMPDIR:-/tmp}/lsf-provider-guide.XXXXXXXX")
timeout --kill-after=15s 1800s cargo test --locked --all-features \
  -p latent-wasmtime --test s3_blobs --test vault_secrets \
  --test nats_events --test nats_triggers --no-run --jobs 2 \
  --message-format=json > "$PROVIDER_REVIEW/provider-tests.jsonl"
test -s "$PROVIDER_REVIEW/provider-tests.jsonl"
```

Expected: a successful build and four selected test executables under this
Cargo target. Each runner rejects an oversized inventory, an ambiguous/missing
executable or a path outside that target. Do not reuse another source's inventory
or point a local manifest at another container's filesystem.

Fetch the exact images chosen by the reviewed runner source, not moving tags:

```bash
for RUNNER_MODULE in run_s3_blob_tests run_vault_secret_tests run_nats_event_tests; do
  PROVIDER_IMAGE=$(python3 -c 'import importlib, sys; sys.path.insert(0, "tools"); print(importlib.import_module(sys.argv[1]).IMAGE)' "$RUNNER_MODULE")
  timeout --kill-after=15s 300s docker pull "$PROVIDER_IMAGE"
done
```

That Python command imports trusted checkout tooling only; it does not execute
downloaded installer code. Native bundle authentication remains a separate
[verify-before-execution procedure](../../packaging/linux/INSTALL.md#prerequisites-and-independent-bootstrap-trust).

## 2. Run the real services and guest/provider scenarios

Run sequentially, so each scenario owns and closes its own service. The runners
bound useful test execution to 300 seconds and have separate finite setup/cleanup.
The outer 420-second watchdog leaves cleanup time; an exceeded watchdog or failed
cleanup is a failure, not a successful test with warnings. Logs stay private.

```bash
timeout --kill-after=30s 420s python3 tools/run_s3_blob_tests.py \
  --test-manifest "$PROVIDER_REVIEW/provider-tests.jsonl" \
  > "$PROVIDER_REVIEW/s3.log" 2>&1
timeout --kill-after=30s 420s python3 tools/run_vault_secret_tests.py \
  --test-manifest "$PROVIDER_REVIEW/provider-tests.jsonl" \
  > "$PROVIDER_REVIEW/vault.log" 2>&1
timeout --kill-after=30s 420s python3 tools/run_nats_event_tests.py \
  --test-manifest "$PROVIDER_REVIEW/provider-tests.jsonl" \
  > "$PROVIDER_REVIEW/nats-events.log" 2>&1
timeout --kill-after=30s 420s python3 tools/run_nats_event_tests.py \
  --suite nats_triggers --test-manifest "$PROVIDER_REVIEW/provider-tests.jsonl" \
  > "$PROVIDER_REVIEW/nats-triggers.log" 2>&1
grep -H -E '^test result:|^Removed owned ' "$PROVIDER_REVIEW"/*.log
```

At the [current executed source](../evidence/provider-guide-2026-09-21.json),
the selected suites pass **2 S3, 3 Vault, 4 NATS publication and 10 NATS trigger
tests**, with zero failures or ignored selected tests. Every runner confirms
owned cleanup. Other test cases are deliberately filtered from these real-server
selectors; these 19 tests are not the complete protocol/adversarial suite.
Zero selected tests, a skipped target or a build-only result does not pass.

### Observe S3 identity and recovery

The actual blob guest creates, seals and reads through its original capability
session. The source also writes an object crossing the 5 MiB multipart boundary
and verifies a range that crosses that boundary. A second tenant cannot resolve
the first tenant's receipt even with credentials for the same test bucket.
Wrong credentials produce a known failure without a hidden retry.

For recovery, the fixture deliberately changes a retained completion record to
the uncertain state, then reopens it with a fresh broker/provider. This is a
**controlled crash-state injection**, not a power-loss or native VM test. Opening
the unresolved reference yields uncertainty; explicit bounded `Observe`
reconciliation verifies the existing remote version rather than uploading again.
Replacing the bucket's latest object version does not change the retained read.
The scenario asserts original budget, handle, inventory and pool cleanup.

The [S3 contract](../runtime/s3-blobs.md) explains why a digest/size/media-type
tuple still needs the original tenant and private version receipt. A closed
socket or an empty list is not proof of remote quiescence. Do not select
`AfterOperatorConfirmedQuiescence` without the actual independent operator
confirmation its contract requires; do not delete uncertain inventory to free
capacity. This guest profile has no remote-object deletion or automatic GC.

### Observe Vault versions and credential currentness

The guest reads the allowed reference, is denied an undeclared reference and
cannot borrow another tenant's identically spelled reference. The fixture checks
a cache hit, a remote update, explicit freshness expiry, exact-version reads,
deletion/destruction, token rotation and remote revocation. A value held before
rotation cannot be newly disclosed under a different current token. Transport
tests deliberately interrupt requests, retain owned work through cleanup and
check subsequent healthy reuse; audit/status checks reject secret disclosure.

The [Vault profile](../runtime/vault-secrets.md) exposes selected KV-v2 string
fields, not arbitrary Vault APIs, renewable dynamic leases or guest token access.
Local credential rotation/expiry is checked independently of cache freshness.
Remote revocation or a KV update may remain unobserved until the configured cache
TTL expires; already disclosed bytes cannot be revoked. There is no stale-on-error
fallback after expiry. Do not log the value to prove that a read succeeded.

### Observe NATS acknowledgement, redelivery and saturation

The publication fixture checks the actual TLS broker acknowledgement, denied
topic/credentials, bounded request budget, current credential material, retained
receipt ownership and connection reuse. An owned fault proxy drops a reply **after
the real broker accepted the message**: the provider reports uncertainty while
the fixture observes the message. Only an explicit caller attempt can exercise
the broker's configured duplicate window; the adapter does not retry for it.

Trigger tests reserve local admission before pulling. Saturation therefore
prevents a pull rather than building an unbounded prefetch queue. They exercise
two tenants, route changes affecting future deliveries, tenant-scoped revocation,
declared failure, bounded poison-message attempts and invalid payload rejection.
The bounded dormant case keeps 256 bindings on two connections without creating
guest stores; that is this configured fixture's observation, not a capacity or
performance guarantee for every installation.

Two recovery cases deliberately differ: one loses the acknowledgement command,
so broker redelivery after poller restart can execute the guest again; another
loses only the broker receipt after it committed. Both local observations remain
uncertain. Shutdown cases retain and reclaim pending/executing ownership without
inventing a successful acknowledgement. This is local owner/poller restart, not
a native machine reboot or a durable guest workflow.

Use the exact [publication result table](../runtime/nats-events.md#receipts-failure-and-duplicate-scope)
and [trigger terminal table](../runtime/nats-triggers.md#broker-profile-and-terminal-outcomes).
Broker acknowledgement is not downstream processing, application state commit,
an outbox receipt or end-to-end exactly-once delivery. A public event ID is not
authority to replay a mutation.

## 3. Diagnose without weakening the boundary

| Observation | Inspect and preserve | Do not do |
| --- | --- | --- |
| Wrong grant or tenant | Actual imported operation, publication/revision, principal, current policy and exact configured provider binding | Treat successful local verification or an opaque handle as an execution grant; widen another tenant's policy |
| Expired/rotated credential or denied remote auth | Protected reference purpose, tenant/provider/destination, current epoch and expected remote permission | Print credentials, reuse test tokens or silently fall back to old material |
| TLS failure or unexpected destination | Approved static peer, independently verified server name, selected roots and protocol profile | Disable verification, accept arbitrary redirects or enable ambient proxy/credential discovery |
| Exhausted budget, full pool or slow provider | Original deadline/cumulative charges, bounded pending/running counts and still-owned bytes/workers | Reset deadlines, create per-app pools or refund work merely because the caller stopped waiting |
| Missing reply after a possible remote write | Original invocation/provider identity, bounded typed outcome and exact pending inventory or broker observation | Convert uncertainty to non-execution, use a new mutation ID, or run a universal retry loop |
| Cleanup incomplete | Actual retained socket/worker/buffer/inventory ownership and the runner's unique label/immutable container ID | Declare clean shutdown from a dropped future or prune unrelated containers/volumes |

The [sealed broker](../runtime/capability-broker.md) intersects actual imports,
deployment restrictions, current tenant policy, principal and provider
configuration, then rechecks currentness at guarded dispatch. Handles belong to
one activation session. Revocation before dispatch prevents new work; accepted
work and possible remote effects retain their original ownership afterward.
The [shared pool contract](../runtime/provider-pools.md) accounts for retired
epochs and delayed consumers too. Audit reports what the node observed; it is
not durable external action or a new execution grant.

## Cleanup, evidence and next step

Successful runners remove only their uniquely labelled service by immutable ID,
its temporary payload/TLS/inventory files and their owned work. If Docker becomes
unreachable, cleanup cannot be verified: stop, retain private diagnostics and
reconcile that exact ownership after recovery. Do not issue broad `docker rm`,
prune images/volumes, adopt another container or rerun a failed mutation as cleanup.

The review directory still contains the Cargo inventory and private logs. Keep
only a redacted record of `SOURCE_COMMIT`, pinned toolchain/images, actual named
test outcomes and cleanup confirmations. After review, remove only that new,
resolved review directory. Do not remove an installed node's state, credentials,
provider inventory or another worktree's target.

The retained evidence is actual CI execution at `05360c50eb6c40212111ad0d87198db5dead78a5`
for reviewed PR head `edec84fa`, not execution at the guide commit. The original
check matches 18 source objects, including the complete relevant crate/WIT trees,
runner/support files and lock/toolchain inputs, against guide source `22dc2f07`.
At the newly selected `3c2f3e7d` base, 17 of those objects still match, but
`Cargo.lock` has changed. Preserve the original record; do not extend its result
to the newer dependency graph without executing the selected suites again.
Local Windows checks of the instructions do not claim a new Linux provider run.
Human newcomer review and the standalone configured-node walkthrough
remain pending, as do the remaining local/HTTP/call/utility paths in the
[guide acceptance inventory](../development/operator-guide-acceptance.md).

Continue with [policy receipt/revocation recovery](reconcile-a-policy-change.md)
and the [operator delivery path](../learn/deliver-and-recover-a-capsule.md).
This page consumes existing implementations and tests; it adds no provider,
alternate transport suite, production certification or release publication.
