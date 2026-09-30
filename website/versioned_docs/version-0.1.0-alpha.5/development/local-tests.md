# Local test entry point

`python3 tools/test.py` is the local front end for the same suite, recipe, selection,
and prepared-Cargo-artifact contracts used by CI. It does not maintain a second
suite list. Stable suite IDs come from `tools/ci/suites.json`; focused CI selections
are exposed as `selection.<name>`.

The boundary is deliberate:

- `list`, `explain`, and `plan` only read checked-in contracts. They do not run a
  compiler, contact a network service, discover tests dynamically, or dispatch CI.
- `check` validates prerequisites and a supplied prepared Cargo inventory. It never
  builds or installs anything.
- `prepare` is the only verb allowed to compile. If the inventory path does not
  exist, it runs the exact registered build recipe and writes Cargo's JSON artifact
  inventory there. If the inventory already exists, it only validates and reuses it.
- `run` is execution-only. It rejects a missing or incompatible inventory rather
  than building, downloading, installing, broadening the selection, or retrying.
- `reproduce` accepts only the bounded `latent.test-run.v1` diagnostic emitted by
  the shared owned-process runner. Commands and environments are never replayed
  from the record. Source, recipe, exact cases, and prepared-inventory identity are
  checked before execution.
- Custom harnesses and provider-owned selections keep their registered owner. The
  local front end does not pretend they are libtest suites or bypass service/fixture
  setup. Physical/qualification selections remain explicit.

Start by inspecting the shared catalog:

```bash
python3 tools/test.py list
python3 tools/test.py explain --suite latent-core.lib.latent-core
python3 tools/test.py plan --suite selection.metadata-working-set
```

`plan` reports the boundary, supported platforms, prerequisites, resource class,
registered recipe, exact selected cases, preparation state, and whether the
selection is an explicit physical qualification. Cost descriptions remain
qualitative; this interface does not promise stable wall-clock timings.

## Small Rust logic

This path uses the ordinary host suite and an exact registered case. The first
`check` intentionally returns `needs-preparation` when no inventory is supplied;
that is not a skipped success.

```bash
python3 tools/test.py check --suite latent-core.lib.latent-core
python3 tools/test.py prepare --suite latent-core.lib.latent-core --case digest::tests::canonical_sha256_text_round_trips_in_each_identity_domain --inventory target/local-tests/core.jsonl
python3 tools/test.py check --suite latent-core.lib.latent-core --case digest::tests::canonical_sha256_text_round_trips_in_each_identity_domain --inventory target/local-tests/core.jsonl
python3 tools/test.py run --suite latent-core.lib.latent-core --case digest::tests::canonical_sha256_text_round_trips_in_each_identity_domain --inventory target/local-tests/core.jsonl
```

Preparation may compile because it is explicit. The later `run` uses only the
source-matched artifact recorded in `target/local-tests/core.jsonl`, validates the
complete registered test listing first, and then executes exactly the requested
case. Remove the local inventory when it is no longer useful; ordinary Cargo
outputs remain normal checkout-local build outputs.

## Runtime/component integration

Runtime suites use the same artifact contract but can contain opt-in ignored cases.
A suite whose active set is empty will not silently turn `run` into a skipped
success: select one exact ignored case.

```bash
python3 tools/test.py plan --suite latent-wasmtime.test.echo-backend --case invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary
python3 tools/test.py prepare --suite latent-wasmtime.test.echo-backend --case invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary --inventory target/local-tests/echo-backend.jsonl
python3 tools/test.py check --suite latent-wasmtime.test.echo-backend --case invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary --inventory target/local-tests/echo-backend.jsonl
python3 tools/test.py run --suite latent-wasmtime.test.echo-backend --case invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary --inventory target/local-tests/echo-backend.jsonl
```

The preparation recipe is still the registered CI recipe; `run` does not invoke
Cargo. The shared artifact reader verifies the manifest/target/source identity,
the shared discovery contract checks the full suite and ignore state, and the
owned-process runner retains bounded diagnostics and cleanup status.

## Angular/provider failure reproduction

The maintained Angular renderer process is exposed as
`process.angular-renderer`. It composes the registered
`processContracts["angular-renderer"]` suite set and delegates execution to
`run_angular_renderer_tests.py`; the local front end does not reproduce its
fixture or child-process logic.

```bash
python3 tools/test.py check --suite process.angular-renderer
python3 tools/test.py prepare --suite process.angular-renderer --inventory target/local-tests/angular-renderer.jsonl
python3 tools/test.py check --suite process.angular-renderer --inventory target/local-tests/angular-renderer.jsonl
python3 tools/test.py run --suite process.angular-renderer --inventory target/local-tests/angular-renderer.jsonl --fault after-discovery
```

The first `check` reports every missing prepared input before execution.
`prepare` is the only command in this workflow that may build: it produces the
registered Cargo inventory, runs the existing renderer-profile `npm ci` /
`npm run build` preparation, and calls the maintained
`build_angular_renderer.py` preparer. This explicit step can use the network
through npm when the local cache is insufficient. The later `run` is
execution-only and consumes those exact files.

The `--fault after-discovery` command is an intentional negative control and is
expected to exit nonzero after real prepared-harness discovery. Its maintained
`TestRun` owner writes
`target/test-diagnostics/angular-renderer-RECORD.json`. Re-run only that
sanitized source/recipe/case/fixture selection:

```bash
python3 tools/test.py reproduce target/test-diagnostics/angular-renderer-RECORD.json --inventory target/local-tests/angular-renderer.jsonl
```

A changed checkout is rejected by default. For investigation only, it can be
labelled explicitly; recipe, case list, Cargo inventory, public/private renderer
WASM, and inventoried harness identities are still checked:

```bash
python3 tools/test.py reproduce target/test-diagnostics/angular-renderer-RECORD.json --inventory target/local-tests/angular-renderer.jsonl --allow-changed-checkout
```

For a successful renderer integration after the failure/reproduction exercise:

```bash
python3 tools/test.py run --suite process.angular-renderer --inventory target/local-tests/angular-renderer.jsonl
```

Provider-owned selections such as `selection.s3-blobs`,
`selection.vault-secrets`, and the NATS selections remain with
`run_ci_lanes.py` / their provider owners. The local front end lists and
explains them but will not turn a provider selection into an unprepared generic
libtest. This preserves Docker image, service readiness, credential, cleanup,
and negative-control ownership.

The maintained Angular runner owns its test children and writes bounded cleanup
diagnostics on normal and fault teardown. When finished, remove only the local
inventory and generated renderer-profile preparation you created, for example
`target/local-tests/angular-renderer.jsonl` and, if no longer useful,
`examples/renderer-profile/node_modules` / `examples/renderer-profile/dist`.
No blanket process or container cleanup is performed.

## Explicit qualification

Physical suites are not pulled into ordinary local runs. They are available only
through an exact selection. The metadata working-set probe, for example, is the
same prepared selection exercised by full CI:

```bash
python3 tools/test.py plan --suite selection.metadata-working-set
python3 tools/test.py check --suite selection.metadata-working-set --inventory target/local-tests/metadata.jsonl
python3 tools/test.py prepare --suite selection.metadata-working-set --inventory target/local-tests/metadata.jsonl
python3 tools/test.py run --suite selection.metadata-working-set --inventory target/local-tests/metadata.jsonl
```

A local pass is evidence for that one run and host. It is not a release or phase
qualification receipt unless the owning gate says so.

## Optional preview and version diagnostics

Changed-file preview remains owned by issue #339, and scoped tool-version
diagnostics remain owned by issue #338. This wrapper delegates only when those
interfaces exist; it never substitutes a broader check.

```bash
python3 tools/test.py preview --base development --worktree
python3 tools/test.py doctor --scope python
```

Until those optional tools land, the commands return `not-run` with the missing
prerequisite instead of dispatching GitHub Actions or probing every SDK.

## Exit and failure semantics

A completed selected run returns zero only after all required cases and result
counts match the registered contract. Test failure returns nonzero; missing
preparation or unavailable prerequisites return `not-run`; interruption is
preserved as cancellation; watchdog/output-bound failures remain distinct.
There is no automatic test retry.

CI uses this same entry point for the existing `selection.metadata-working-set`
prepared suite: `check`, `prepare` (validation/reuse of the already built
inventory), then execution-only `run`. The regression test
`tools/tests/test_local_tests.py` locks that handoff to the same inventory cases
and prevents documentation/CI drift.
