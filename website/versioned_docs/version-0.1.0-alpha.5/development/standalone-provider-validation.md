# Validate standalone providers

This page is for contributors changing provider bootstrap, SDK workflows or
startup recovery. For node configuration, use [Configure standalone providers](../reference/standalone-providers.md).

## Focused provider failure tests

After setting up [the contributor toolchain](toolchain.md), use these targeted
checks when changing provider ownership or resource accounting:

```bash
cargo test --locked -p latent-wasmtime --test http \
  --test streaming_http --test local_secrets --test random --test metrics -- --nocapture
cargo test --locked -p latent-capabilities --lib broker::pools -- --nocapture
```

The cases cover exhausted original request budgets, cancelled stream reads,
failed secret reload preserving the current value, failed entropy without
partial bytes, a closed metric exporter returning typed unavailability, and
old credential epochs retained while requests remain live. Expected failure
results and cleanup assertions must both pass.

Use [the disposable S3/Vault/NATS scenarios](../how-to/exercise-provider-failure-and-recovery.md)
for actual TLS services, interrupted writes, credential rotation and broker
redelivery. These tests exercise the Rust composition; they do not add those
providers to standalone JSON configuration.

## Shared SDK/management fixture contract

Use `tools/build_guest_capsules.py`, not a synthetic component or a new provider
implementation. HTTP/blob manifests now declare the delivered standalone
10-billion fuel ceiling. This does not add a builder profile or claim
reproducible byte-for-byte builds. The Rust fixture exporter checks the actual
build-completion marker and source observation, then signs that exact package
with fresh test publisher and builder keys and attached SBOM evidence.

```sh
python3 tools/build_guest_capsules.py --output "$CARGO_TARGET_DIR/guest-capsules"
fixture_parent="$(mktemp -d)"
LSF_GUEST_CAPSULES="$CARGO_TARGET_DIR/guest-capsules" \
LSF_PHASE3_WORKFLOW_FIXTURE_ROOT="$fixture_parent/inputs" \
  cargo test -p latentd --test phase3_workflow_fixture --locked -- \
    export_signed_provider_workflow_fixtures --exact --ignored --nocapture
cargo build -p latent -p latentd --locked
python3 tools/run_phase3_management_workflow.py \
  --cli "$CARGO_TARGET_DIR/debug/latent" --node "$CARGO_TARGET_DIR/debug/latentd" \
  --fixture-root "$fixture_parent/inputs"
```

The exporter requires an absolute, absent output directory. It writes
`policy.json`, `fixture.json`, `rust-{http,blob,callee}/package`, and
`rust-{http,blob,callee}/evidence/index.json`. The summary contains exact package and
component digests plus the actual build observations. Test signatures expire;
export immediately before the workflow. No private signing keys are exported.
The shared deployment helper deploys only HTTP/blob; SDK runners may deploy
the maintained `rust-callee` package separately for `answer`, `fail`, and `spin`.

`tools/phase3_management_scenario.py` is the shared setup interface:

| Helper | Contract |
| --- | --- |
| `start_http_fixture(client, private_directory)` | Owned finite loopback peer and its numeric port; credential-checking, no request echo |
| `configure_provider_node(private_directory, fixture_root, port)` | New protected node config; separate durable storage and credential files |
| `connect(client, node_binary, node_directory, config, "tests", ordinal)` from `phase2_operator_scenario` | Owned actual node, explicit authenticated CLI profile, bounded readiness; actual `startup_record` |
| `publish_and_deploy_guests(client, fixture_root, node, port)` | Exact signed publication, actual provider-binding records, grants and deployments; returns HTTP/blob targets |
| `invoke_guest(client, target, which, text="", handle=0, codes=(0,))` | One CLI call and decoded u64 result; useful as the management reference, not an SDK transport substitute |
| `stop_http_fixture(peer)` | Explicit stop/reap and bounded request/authorization counts |

Each target contains `publication`, `componentDigest`, `service`, `route`,
`contract`, `function`, `budget`, and `policyGeneration`. For SDK invocations,
use service `generic`, route `guest-http` or `guest-blob`, contracts
`tests:http/api@1.0.0` or `tests:local-blobs/api@1.0.0`, function `run`, and media
type `application/vnd.latent.wit-values.v1+json`. Inputs are the JSON tuple
`[which, text, "decimal-u64-handle"]`; output is `["decimal-u64-result"]`.
HTTP cases 0/1/2 are GET/HEAD/POST to `http://localhost:PORT/allowed` and return
2201/201/2201; `/denied` returns guest denial 10 without contacting the peer.
Blob case 0 writes, seals and reads four bytes and returns 4; case 1 abandons a
writer and returns 1; case 2 verifies a closed handle and returns 10.
The configured operator credential derives an administrator principal named
`workflow-operator`; the fixture grants match that exact authenticated identity.
Invocation RPC timeouts must be at most the configured 5000 ms ceiling. The
CLI helper selects `--budget-profile phase3` explicitly, without changing node
authority or enabling unsupported state/effect budget dimensions.

Keep SDK runners separate (for example `tools/run_rust_sdk_workflow.py`) and
reuse setup only. Client, node and HTTP peer have disjoint working directories;
the client uses transport credentials and never reads node data or provider
credential files. The management runner checks invocation, grant revocation,
inspection, restart identity, no hidden provider retries, and clean shutdown.
The shutdown report distinguishes live work from persistent blob inventory:
`blobHandles` and `blobWork` must be zero, while `blobStages` reports abandoned,
still-accounted durable staging records. Clean shutdown neither deletes those
records nor refunds their disk reservation. Existing blob reclamation remains
an explicit bounded store operation, not a hidden per-application worker.
Policy read ownership is sampled after dormant catalog plans are destroyed.
Restart waits six seconds for the configured five-second supply-chain clock
lease; this is a bounded test setup wait, not an RPC retry or renewed deadline.
Its compact receipt is deliberately scoped to HTTP/blob acceptance and reports
`angularT1Qualified: false`. It does not qualify Angular T1 or selected-publication/web/trigger integration.
Those behaviors are covered separately by the [management integration record](../phase3-management-integration.md)
and [Angular T1 workflow](../testing/angular-t1-workflow.md).

The existing contract gate builds the guests once and runs this workflow with
fresh short-lived evidence. CI retains `phase3-management/provider-receipt.json`
alongside the existing bounded conformance diagnostics, using the current
`phase-1-bounded-conformance-<commit>` workflow artifact name.

### Startup audit recovery checkpoint

The 2026-09-19 contract run retained a
`node-startup-exit-startup-resource-exhausted` diagnostic. Inspection found that
the capability and generic release recovery paths used nonblocking audit reads
without waiting for pre-admission journal contention. Startup now bounds those
waits by one original 30-second deadline and retries only the exact
`ResourceExhausted` / `audit-busy` pre-admission result. Real capacity failures,
uncertain writes and admitted append acknowledgements are never replayed.

Capability attempts reconcile before the generic release fallback, preserving
the captured capability identity and an explicit `Unknown` provider outcome.
Recovery neither calls the provider nor recreates an authorization grant.
A real durable-journal crash-cut regression reopens the catalogs and checks
that exact identity; three focused tests cover pre-admission contention,
nonretryable capacity/write failures and the original deadline.

On Linux with Rust 1.97.1, `cargo test --locked -p latentd --lib
standalone::start -- --nocapture` passed 28 tests; four separate trust-currentness
tests remained explicitly ignored because their signed fixtures were not
provided. `cargo clippy --locked -p latentd --lib --tests --all-features
--no-deps -- -D warnings` passed. These are bounded startup regression results,
not full provider-workflow or Angular qualification. These retained measurements do not certify later changes; earlier unclassified exits are not retroactively
attributed to this finding.

A later independently retained attempt still failed before launching the Go
participant. A direct repeated startup regression then reproduced the exact
cause on startup 8: `ResourceExhausted` / `capability-busy`. The provider control
task was briefly holding its bounded job registry while bootstrap tried to
enqueue the local blob-store open. This was not an exhausted worker quota or
a failed, already-started filesystem operation.

Bootstrap now waits only for that exact pre-enqueue contention under its
original 30-second deadline. The pool's ordinary nonblocking admission API and
capacity failures are unchanged. A successfully admitted job is awaited once;
neither an uncertain result nor any already-started filesystem work is replayed.
Three deterministic admission tests pass. A normal-CI protected local-blob test
starts and shuts down 32 nodes; a separate explicitly supplied synthetic signed
HTTP/blob configuration passes another 32 starts/shutdowns. Both tests passed
together on Linux (64 actual startups, 5.94 seconds), and strict latentd Clippy
passed. The signed configuration remains an explicit ignored-test input, never
an installed credential or trust default. The complete provider/SDK workflows and current-source CI are separate checks.
