# Standalone provider bootstrap and shared workflow (#226)

The opt-in `providers` object installs the existing bounded HTTP and immutable
local-blob providers in the standalone node. It does not install a guest secret
provider, streaming HTTP, S3, events, or an invented provider profile. The
[configuration schema](../../schemas/node-providers.schema.json) describes the
closed input. This example is the provider section of a protected node file:

```json
{
  "providers": {
    "formatVersion": 1,
    "blob": {
      "identity": {"id": "blob", "tenant": "tests", "service": "blob-host", "epoch": 1},
      "namespace": "workflow"
    },
    "bindings": [
      {"name": "blob-binding", "tenant": "tests", "consumerService": "generic",
       "providerService": "blob-host", "contract": "latent:blob/blob@0.2.0",
       "providerBinding": "blob-installed", "route": "guest-blob"}
    ]
  }
}
```

Installation requires Linux x86_64, a protected configuration file, `phase3`
budgets, `capabilityPolicies`, and durable audit. Omission disables installation;
explicit null and unsupported fields fail closed. `check-config` validates the
configuration without installing providers or opening credential/blob storage.
Actual startup separately verifies protected credential storage and may fail.

HTTP configuration is the existing `latent_http::HttpProviderConfig`: explicit
origins, address policy, static or bounded DNS resolution, redirects, roots and
finite request/response/header limits. Credentials are file references under an
explicit protected `credentialDirectory`, relative to the node file if not
absolute. Each reference binds one configured destination, tenant, provider ID
and approved credential header. Secret bytes are neither configuration values
nor public configuration digests, CLI outputs, guest imports, or diagnostics.
The shared workflow writes a clearly public test-only credential, not a real
credential. Production credentials must be supplied by the operator.

The node's bounded `started` record includes actual installed descriptors:
`id`, `tenant`, `service`, `capability`, `profile`, `configurationDigest`, and
decimal-string `configurationEpoch`. Use those exact descriptors when applying
the typed provider-binding policy record; do not manufacture a matching digest.
Installation alone grants no consumer authority. Deployment grants, current
policy, binding restrictions, publication admission, budgets and provider
currentness still apply independently.

Host bindings are durably established once. Restart requires the exact same
definitions and reattaches live providers without changing catalog bytes,
deployment revisions or route generations. Changed or missing bootstrap
definitions fail closed; this profile does not silently migrate bindings.
Shutdown retires capabilities and reports actual pool, broker, I/O and blob
reclamation counters. A failed or incomplete cleanup is not reported as clean.

Combining the resident rollout worker with capability policy/provider work
requires two bounded control blocking slots, not one. The CLI derives this
fixed node-wide ceiling; embedders can use `NodeSettings::control_blocking_threads`.
Otherwise the rollout worker would occupy the only slot and starve protected
credential reads, blob work and policy operations. This adds no per-service
thread, pool or listener.

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
`angularT1Qualified: false`. It does not close full #226, qualify Angular T1,
or replace the pending selected-publication/web/trigger integration tests.

The existing contract gate builds the guests once and runs this workflow with
fresh short-lived evidence. CI retains `phase3-management/provider-receipt.json`
alongside the existing bounded conformance diagnostics, keeping the existing
`phase-1-bounded-conformance-<commit>` artifact name for compatibility.

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
not full provider-workflow or Angular qualification. Exact-head CI must still
complete before merge; earlier unclassified exits are not retroactively
attributed to this finding.
