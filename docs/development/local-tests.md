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
python3 tools/test.py run --suite latent-wasmtime.test.echo-backend --case invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary --inventory target/local-tests/echo-backend.jsonl
```

The preparation recipe is still the registered CI recipe; `run` does not invoke
Cargo. The shared artifact reader verifies the manifest/target/source identity,
the shared discovery contract checks the full suite and ignore state, and the
owned-process runner retains bounded diagnostics and cleanup status.

## Angular/provider failure reproduction

The browser-boundary selection is an existing CI-owned Angular/browser integration
selection. It is exposed through the same entry point without inventing another
fixture recipe.

```bash
python3 tools/test.py check --suite selection.browser-boundary
python3 tools/test.py prepare --suite selection.browser-boundary --inventory target/local-tests/browser-boundary.jsonl
python3 tools/test.py run --suite selection.browser-boundary --inventory target/local-tests/browser-boundary.jsonl
```

On failure, the command reports the `target/test-diagnostics/...json` record written
by the shared `TestRun` owner. Re-run the exact recorded cases with the same
prepared inventory:

```bash
python3 tools/test.py reproduce target/test-diagnostics/selection.browser-boundary-RECORD.json --inventory target/local-tests/browser-boundary.jsonl
```

A changed checkout is rejected by default. For investigation only, it can be
labelled explicitly; recipe/case and prepared-inventory identity are still not
bypassed:

```bash
python3 tools/test.py reproduce target/test-diagnostics/selection.browser-boundary-RECORD.json --inventory target/local-tests/browser-boundary.jsonl --allow-changed-checkout
```

Provider-owned selections such as `selection.s3-blobs`, `selection.vault-secrets`,
and NATS selections are listed and explained, but `run` refuses to bypass their
existing provider/service owner. Use the owner named by the plan (the same owner
used by `run_ci_lanes.py`) when a real provider fixture is required. This is a
deliberate distinction between “known selection” and “safe generic execution.”

Private test fixtures and owned children remain the responsibility of their
registered runner and are cleaned during normal/fault teardown. The local front
end never issues a blanket process/container kill. Remove only the inventory or
other output you explicitly created after the run.

## Explicit qualification

Physical suites are not pulled into ordinary local runs. They are available only
through an exact selection. The metadata working-set probe, for example, is the
same prepared selection exercised by full CI:

```bash
python3 tools/test.py plan --suite selection.metadata-working-set
python3 tools/test.py check --suite selection.metadata-working-set --inventory target/local-tests/metadata.jsonl
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
