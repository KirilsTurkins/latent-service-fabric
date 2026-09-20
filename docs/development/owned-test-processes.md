# Owned selected test processes

The selected OCI registry and Angular renderer/node runners share a Python
ownership contract. This is test tooling, not a runtime service, a cross-language
daemon, or a requirement to install Docker for LSF. Only the explicitly selected
OCI fixture needs a prepared Docker image. Ordinary in-process correctness tests
do not run provider, browser, filesystem, or process-accounting preflight.

## Existing owners and migration boundary

| Layer | Existing owner | Boundary after this change |
| --- | --- | --- |
| Python prepared Rust tests | `tools/ci_rust_artifacts.py` | Preserves exact Cargo identity/list/result validation; delegates subprocess ownership to `owned_test_process.py`. |
| Python registry | `tools/run_oci_registry_tests.py` | Migrated CLI: shared preflight, private root, total deadline, identity-bound TLS readiness, immutable-ID removal, structured diagnostics. Imported fixture helpers remain compatible with unmigrated callers. |
| Python renderer/node | `tools/run_angular_renderer_tests.py` | Migrated: explicit prepared components and Cargo inventory; exact registered ignored cases; descendant retirement on listing and execution. |
| Python other providers | `run_s3_blob_tests.py`, `run_vault_secret_tests.py`, `run_nats_event_tests.py`, `nats_test_support.py` | Their existing provider/startup owners remain. They are not silently claimed as migrated. |
| Python operator/resource workflows | `phase2_operator_process.py` (`Process`, `Client`), `phase2_gate_resource_os.py` (`Probe`), `phase2_gate_resource_run.py` (`BoundedClient`, `stop`) | Retain workflow-specific evidence/accounting and shutdown semantics; no measurement or security-policy relaxation. |
| Rust | `crates/latent-testkit/src/process.rs`, `process/owned.rs`, `process/tests.rs` | Preserve `ProcessHarness`, Tokio `OwnedProcess`, bounded capture and wait/terminate tests. These own a direct child; a retained stdout line or `Drop` is not proof of current readiness or reaped descendants. Rust suite callers needing the stronger descendant boundary can run under the Python owner. |

`owned_process_worker.py` is an isolated, per-command Linux subreaper. Its
anonymous, close-on-exec status pipe carries a fresh nonce and is separate from
untrusted stdout/stderr. It reports the target PID, observed exit/signal, timing,
and completion of descendant retirement. Output EOF alone never ends ownership.
The worker reads only its own `/proc/self/task/<self>/children` list, kills direct
unreaped children, and adopts/reaps orphaned descendants (including `setsid` and
double-fork escapes). `ECHILD`, not an empty host process survey, proves retirement.
The parent keeps its worker unreaped until the final process-group kill decision,
so a reused PID cannot select an unrelated process.

The declared platform is native `linux-x86_64`. Restricted Linux without the
owned-child accounting interface is **unavailable**, not a passing substitute.
No host-wide `/proc` enumeration, fabricated zero I/O, privilege escalation,
security-policy edits, system-wide subreaper, or blanket container cleanup is used.
This is lifecycle supervision for trusted tests, not a security sandbox against
malicious fork bombs or an unresponsive kernel. Unconfirmed cleanup fails the run.

## Inventory and explicit preparation

`processContracts` in the existing `tools/ci/suites.json` extends #427's inventory;
its suite IDs, registered ignored cases, package/target/source identity, platforms
and recipe names remain the authority. `test_run.contract()` uses #427's loader;
it does not implement a competing suite classifier. The dependency files are the
#427 snapshots, with only the process-contract extension to the JSON catalogue.

Each selected contract declares tools, prepared service image identities,
filesystem operations, owned accounting access, artifact roles and supported
version scopes. Python's exact baseline comparison reuses
`tools/check_tool_versions.py` / `tools/toolchain.toml` (#338); no second version
comparator is introduced. Unknown version scopes fail rather than guessing an
unimplemented #338 command-line interface. Rust/toolchain setup remains pinned
by the build workflow.

The prepared boundary composes `ci_rust_artifacts.read_inventory()` and
`cargo_environment()`: it consumes explicit successful Cargo JSON, never scans
`target`, picks the newest cached executable, calls Cargo, or builds on demand.
This is the existing boundary being extended by #428, not a new artifact service.
The renderer preserves explicitly configured `CARGO_TARGET_DIR`. Required target
kind, source, manifest and executable ownership are validated; duplicate,
foreign, malformed or unsuccessful build inventories fail. Each executable and
fixture is bounded and hashed, and an executable replacement between discovery
and execution is rejected. Source revision and dirty state are observed locally;
these diagnostics are **not** a provenance attestation or proof that a cached
binary was built from a claimed revision. Build inventories must be generated by
the current job on its checked-out source, as in CI, not reused across checkouts.

For the registry, prepare the pinned image explicitly (its digest is in the
inventory), then run environment-only preflight **before** Cargo compilation:

```sh
python3 tools/run_oci_registry_tests.py --preflight
cargo test -p latent-oci --test registry --locked --no-run \
  --message-format=json,json-render-diagnostics > /tmp/lsf-oci-tests.jsonl
python3 tools/run_oci_registry_tests.py --test-manifest /tmp/lsf-oci-tests.jsonl
```

Web admission uses its own `latent-policy --lib` Cargo inventory and
`--web-admission-component`; observed capsule provenance retains the explicit
`--provenance-input` directory. These are separate selections; missing preparation
is never replaced with compilation or a skipped successful test.

The renderer uses the already prepared workspace inventory and public/private
composed components:

```sh
python3 tools/run_angular_renderer_tests.py --preflight
# Prepare the workspace harnesses and the existing Angular fixture build.
python3 tools/run_angular_renderer_tests.py \
  --test-manifest /tmp/lsf-workspace-tests.jsonl \
  --component examples/renderer-profile/dist/runtime/application.wasm
```

Before execution, listing must match the full registered ignored set for the
selected target. Each requested case then runs once with `--exact --ignored` and
one test thread. A missing case, duplicate target or zero-test success is failure.
The recorded reproduction selection includes exact case names, recipe, source
identity and fixture/binary digests. No shell commands, credentials or private
artifact paths are captured in that selection.

## Deadline, readiness and cleanup

Each `TestRun` gets a private mode-0700 root and one monotonic total budget,
including source/prerequisite checks, startup, discovery, execution and teardown.
A main-thread watchdog also bounds Python/HTTP stages, not just child waits.
Cleanup reserves budget **inside** the original deadline; it does not receive a
fresh full test timeout. Combined stdout/stderr is bounded while streaming, not
only after process exit. Cancelled async waiters join retirement before returning.

OCI retains dynamic IPv4-loopback ports, pinned images, resource limits,
read-only fixture mounts and ephemeral credentials. `--pull=never` prevents an
implicit fetch during execution. Readiness checks the current immutable container
ID, this run's label, running state, exact mapped endpoint, TLS CA and distribution
v2 response. It checks liveness again after the response. Only finite read-only
polling is allowed: no mutation retries or scenario reruns. Removal uses the
verified immutable ID and confirms absence before deleting its protected recovery
state. Replaced or foreign state is preserved and reported, never overwritten.

## Diagnostics, outcomes and retained examples

`--diagnostic-root` controls where exclusive mode-0600 JSON records are written;
the default is `target/test-diagnostics`. Each record has schema
`latent.test-run.v1`, suite/stage/run identity, observed source and fixture IDs,
child exit/signal and cleanup acknowledgement, elapsed/stage/startup/teardown
times, safe exact reproduction selection, cleanup failures and a redacted bounded
tail. Redaction runs before tail truncation and includes known secret environment
values, credentials, authorization/cookies, private keys and private paths.
Diagnostics never include full environments, raw command arguments or fixture
private keys. The compact records compose with #426's timing collection.

Unavailable environment produces `outcome: not-run`, invalid fixture/assertion/
timeout produces `outcome: failed`, and either exits nonzero for selected CI.
Environment-only success is `preflight-passed`, not test coverage. Records are
explicitly `runner-diagnostic-not-qualification`; synthetic process demonstrations
are marked `synthetic-process-contract`, never Wasmtime/provider qualification.

CI retains attempted renderer/provider diagnostics, including fault examples,
for seven days. Outcome guards prevent pretending an unselected job attempted to
produce evidence. Actual renderer gates remain real Wasmtime/Angular tests; an
additional injected `after-discovery` failure is independently checked by
`check_owned_diagnostics.py` for the expected reason and confirmed retirement.
It never turns a failing normal scenario green. Live OCI normal/fault fixture
checks verify TLS readiness and removal; they are fixture checks, not OCI package
qualification. Normal OCI package and web round trips remain separate real tests.

```sh
LSF_REQUIRE_NATIVE_PROCESS_TESTS=1 python3 -m unittest \
  tools.tests.test_owned_test_process tools.tests.test_owned_runners \
  tools.tests.test_ci_rust_artifacts tools.tests.test_oci_registry_runner
# After explicitly preparing the pinned image:
LSF_REQUIRE_NATIVE_PROCESS_TESTS=1 LSF_LIVE_OCI_DEMO=1 python3 -m unittest \
  tools.tests.test_owned_runners.NativeRunnerDemonstrations
```

Deterministic tests cover missing prerequisites, denied owned accounting,
protected files, false/stale/dead readiness, stalled readiness, crashes, inherited
writers, session and double-fork escape, closed stdout with a live child, timeout,
overflow, synchronous and async cancellation, cleanup failures, foreign recovery
state, exact listings, zero-test rejection and diagnostic redaction. Native
renderer demonstrations run the actual migrated Python runner over explicitly
labelled synthetic libtests and verify orphaned writer PIDs are gone. Native
coverage is required on CI; unsupported developer hosts skip it explicitly and
are not counted as having exercised those guarantees.
