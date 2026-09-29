# Local test entry point

`python3 tools/test.py` is the developer interface to the shared
`tools/ci/suites.json` catalogue, Cargo artifact readers, and maintained process
owners. It neither dispatches GitHub Actions nor requires GitHub credentials.
Use a supported Linux x86-64 checkout and the [pinned tools](toolchain.md).
The commands do not install tools automatically.

## Select before doing work

```bash
python3 tools/test.py list --output json
python3 tools/test.py explain --suite latent-core.lib.latent-core
python3 tools/test.py plan --suite selection.echo-runtime
python3 tools/test.py plan --suite process.angular-renderer
```

`list`, `explain` and `plan` read repository definitions and file presence only.
They never compile, invoke test discovery, query a service or contact the network.
The plan includes purpose, platforms, prerequisites, recipe and fixture commands,
exact cases, resource class, preparation state and execution support. “Present”
means files exist, not that they passed validation. Cost classes are qualitative,
not timing guarantees. Local and CI contexts resolve to identical recipes, cases,
fixtures and runner ownership.

`check` validates successful Cargo stream completion, selected owner/source paths,
features/profile, generated fixture identities and required tool presence without
executing a test binary. Full registered discovery happens inside `run`, before
the selected cases execute. Scoped version diagnostics remain the responsibility
of `doctor`, not an implicit all-SDK probe.

## Small Rust logic

Start with one exact case; a substring is not a case selection.

```bash
python3 tools/test.py check --suite latent-core.lib.latent-core
python3 tools/test.py prepare --suite latent-core.lib.latent-core --case digest::tests::canonical_sha256_text_round_trips_in_each_identity_domain --inventory target/local-tests/core.jsonl
python3 tools/test.py check --suite latent-core.lib.latent-core --case digest::tests::canonical_sha256_text_round_trips_in_each_identity_domain --inventory target/local-tests/core.jsonl
python3 tools/test.py run --suite latent-core.lib.latent-core --case digest::tests::canonical_sha256_text_round_trips_in_each_identity_domain --inventory target/local-tests/core.jsonl
rm -- target/local-tests/core.jsonl
```

The first check intentionally reports `needs-preparation` (exit 3). The registered
`core-host` recipe builds only `latent-core --lib --all-features --locked`, not the
workspace or Angular. The CI Rust lane runs this same case from its compatible
all-features workspace inventory. A local pass covers this selected case, not the
entire workspace, runtime or release qualification.

`prepare` is explicit and may build. An existing inventory is validated and
reused, not silently overwritten. After changing source, locks or build
configuration, remove the inventory you created and explicitly prepare again.
Cargo inventories describe successful artifacts and exact owner paths; they are
**not retrospective proof of the source bytes used by someone else's build**.
Do not copy an inventory from another checkout or relabel stale binaries.

## Runtime/component integration

The echo recipe prepares the existing echo capsule builder and supplies
`LSF_ECHO_COMPONENT` and `LSF_ECHO_CAPSULE` itself. Contributors need not reconstruct
hidden environment variables or fixture order.

```bash
python3 tools/test.py check --suite latent-wasmtime.test.echo-backend --case invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary
python3 tools/test.py prepare --suite latent-wasmtime.test.echo-backend --case invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary --inventory target/local-tests/echo-backend.jsonl
python3 tools/test.py check --suite latent-wasmtime.test.echo-backend --case invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary --inventory target/local-tests/echo-backend.jsonl
python3 tools/test.py run --suite latent-wasmtime.test.echo-backend --case invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary --inventory target/local-tests/echo-backend.jsonl
rm -- target/local-tests/echo-backend.jsonl
```

This is a real component/Wasmtime contract, not a mocked host-only check.
`selection.echo-runtime` selects all four registered ignored cases and additionally
prepares the oversized-log fixture. `tools/validate_contracts.sh` uses that exact
selection and the same preparation/validation/execution interfaces. Existing
compatible generated fixtures are reused. Runtime compilation of a guest under
test is still allowed; invoking Cargo or installing a tool during execution is not.

Generated fixtures under `target/capsules/echo` and `target/capsules/oversized-log`
can be removed after other users of those outputs finish. Test-private state and
children are retired by the maintained owner. `CARGO_TARGET_DIR` is respected for
both preparation and execution; use the same target directory for both.

## Angular/provider failure reproduction

The maintained Angular process is an atomic integration. It owns its complete
registered renderer/node case selection, not the broader browser lane or every
provider. Preparation runs the existing npm/build/renderer builders explicitly.

```bash
python3 tools/test.py check --suite process.angular-renderer
python3 tools/test.py prepare --suite process.angular-renderer --inventory target/local-tests/angular-renderer.jsonl
python3 tools/test.py check --suite process.angular-renderer --inventory target/local-tests/angular-renderer.jsonl
python3 tools/test.py run --suite process.angular-renderer --inventory target/local-tests/angular-renderer.jsonl
python3 tools/test.py run --suite process.angular-renderer --inventory target/local-tests/angular-renderer.jsonl --fault after-discovery
```

The last command deliberately fails after real discovery and before case execution;
it must not pass or retry. Its JSON result supplies a `runId`. Replace `RECORD`
below with that value. The diagnostic retains the **entire intended case set** and
all executable/fixture identities, even though no case completed.

```bash
python3 tools/test.py reproduce target/test-diagnostics/process.angular-renderer-RECORD.json --inventory target/local-tests/angular-renderer.jsonl
python3 tools/test.py reproduce target/test-diagnostics/process.angular-renderer-RECORD.json --inventory target/local-tests/angular-renderer.jsonl --allow-changed-checkout
rm -- target/local-tests/angular-renderer.jsonl
```

The first replay requires the same clean observed Git revision. Tracked and
untracked source changes prevent an exact-reproduction claim. The second command
is an explicitly labelled `changed-input-rerun`; it does not waive the recipe,
case set or prepared byte identities. It retains the recorded fault selector,
so replaying the deliberate failure fails again rather than silently running the
normal path.

Only bounded `latent.test-run.v1` selection data is read. Commands, captured
credentials, arbitrary environments and unsupported owner options are never
replayed. Older records without a bound recipe identity and complete case count
are rejected with an instruction to repeat the run using current tooling.
Large whole-suite selections use a bounded registered-selection digest and count,
not a truncated list.

The wrapper keeps its own redacted diagnostic under `target/test-diagnostics`;
the child owner's private diagnostic is checked before cleanup. Delete only
diagnostics and generated `examples/renderer-profile/dist` assets you own, once
other users are finished. No blanket process/container kill is issued.

Provider selections (`selection.s3-blobs`, Vault and NATS), custom harnesses,
browser-boundary and runtime suites without a migrated fixture owner are still
listed. `check` reports their blocker and `run` refuses a bare libtest fallback.
Selecting their underlying Cargo owner does not bypass service ownership.
Use the maintained owner reported by the plan for those broader integrations.

## Explicit qualification and execution boundary

```bash
python3 tools/test.py plan --suite selection.metadata-working-set
python3 tools/test.py prepare --suite selection.metadata-working-set --inventory target/local-tests/metadata.jsonl
python3 tools/test.py check --suite selection.metadata-working-set --inventory target/local-tests/metadata.jsonl
python3 tools/test.py run --suite selection.metadata-working-set --inventory target/local-tests/metadata.jsonl
rm -- target/local-tests/metadata.jsonl
```

This is explicit physical qualification, not a fast ordinary check. Selecting its
exact case by Cargo owner still delegates to the same physical observation owner
and retains its classification. Original resource thresholds and phase gates are
unchanged. No local diagnostic authorizes a release or becomes cached gate evidence.

`run` consumes the selected prepared inputs, performs exact owned discovery,
validates case results/counts, and does not retry. Failure, cancellation,
unavailable prerequisites, watchdog timeout and output overflow remain distinct.
Child nonzero statuses are preserved; cancellation returns 130, timeout 124,
overflow 125 and unavailable prerequisites 3. Zero or partial execution cannot pass.
`--output json` keeps stdout machine-readable; bounded redacted diagnostics go to
stderr and the owned diagnostic file.

Execution environments include failing build/install/download tool sentinels.
The only allowed `rustc` invocation is the artifact reader's existing read-only
`--print target-libdir` probe, with toolchain auto-install disabled. A swallowed
sentinel failure still fails the run. These checks cover maintained command/PATH
boundaries: they are **not an OS security sandbox or proof against arbitrary
absolute-path subprocesses**.

## Optional preview and version diagnostics

```bash
python3 tools/test.py preview --base development --worktree
python3 tools/test.py doctor --scope python
```

Changed-file preview remains owned by #339, and scoped toolchain diagnostics by
#338. Available interfaces are delegated to; absent interfaces return a clear
`not-run` prerequisite. No competing classifier, silent software installation or
all-SDK fallback is introduced. Offline planning and documentation/CI drift checks
live in `tools/tests/test_local_tests.py`.
