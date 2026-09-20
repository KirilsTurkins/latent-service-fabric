# Local test commands

`python3 tools/test.py` is the local command front end for explicit test
selections. It is being integrated in [#435](https://github.com/KirilsTurkins/latent-service-fabric/issues/435).
**This first integration is not the completed native test interface.** The
shared suite/recipe inventory [#427](https://github.com/KirilsTurkins/latent-service-fabric/issues/427)
and validated prepared inputs [#428](https://github.com/KirilsTurkins/latent-service-fabric/issues/428)
are prerequisites for native execution through this front end. Until they land,
it refuses native execution rather than treating Cargo's JSON inventory as a
validated prepared manifest or duplicating either facility.

Use [VALIDATION.md](../../VALIDATION.md) for the existing complete validation
contracts and the [toolchain guide](toolchain.md) for installation instructions.
No command here installs software, downloads tools, builds Rust or Angular,
dispatches Actions, retries a failing test, or selects a full qualification run.

## Available commands and coverage

```sh
python3 tools/test.py list
python3 tools/test.py explain --suite tooling-artifacts
python3 tools/test.py plan --suite tooling-artifacts --output json
python3 tools/test.py check --suite tooling-artifacts
python3 tools/test.py prepare --suite tooling-artifacts
python3 tools/test.py run --suite tooling-artifacts
```

`list`, `explain` and `plan` inspect checked-out declarations without executing
subprocesses, importing test modules or fetching Git history. `check` performs
bounded, read-only prerequisite checks. Planning does not prove a usable host:
run `check` before execution. JSON output is versioned; human output is the same
information, formatted for inspection. Cost descriptions are not timing promises.

The executable `tooling-artifacts` suite runs the existing
`tools.tests.test_ci_rust_artifacts` module. Its cases are read from that module's
source, not copied into another list. Actual unittest discovery must match the
complete, nonempty declaration inventory before any selected test executes.
This is ordinary correctness coverage of artifact selection and owned Python
processes. It is **not** Wasmtime, provider, browser, RSS or phase qualification.
It uses Python's standard library, Git and checked-out sources. Linux and macOS
are supported; the recorded development validation was on Linux. No external
prepared files are required, so `prepare` is an explicit source-only prerequisite
check and does not create a cache or run the tests. Re-running `run` does not
require a prior successful test receipt.

Existing native IDs are read directly from `ci_rust_artifacts.SUITES`:
`browser-boundary`, `operator-fixture`, `publication-fixture`, `resource-fixture`
and `trust-currentness`. Their exact libtest owner, ignored selection and required
case counts remain visible. The legacy owner does not declare a complete recipe,
platform, prerequisite or qualification contract; those fields are reported as
unknown, not guessed. `check`, `prepare` and `run` return **not-run / exit 3** for
these native selections pending #427/#428. Unknown custom harness contracts are
rejected, never interpreted as ordinary libtest binaries.

`--case` accepts one complete case ID printed by `plan`. Empty filters, substring
filters, unknown suites and extra shell commands are errors. There is deliberately
no default suite or `all` selection. CI uses the same `check`, `prepare` and `run`
commands with `--context ci`; this changes only descriptive context, not the
command, cases, features, fixtures or recipe identity. Existing required Rust,
provider, renderer, signing, doctest and qualification commands are unchanged.

## Changed-file preview and tool versions

```sh
python3 tools/test.py preview --base development --head HEAD
python3 tools/test.py preview --base development --worktree --output json
python3 tools/test.py doctor --scope python --output json
```

These delegate to `tools/preview_ci.py` (#339) and the scoped interface of
`tools/check_tool_versions.py` (#338), respectively, when available. The front end
has no classifier or version parser. The old unscoped checker is not invoked as
a fallback, including with `--help`: it can probe unrelated SDKs. If the optional
interface is absent, the command reports its owning prerequisite and exits 3.
The final interface names must be reconciled with those owners before #435 closes.
No preview or doctor result authorizes a merge or stands in for passing tests.

## Recording and reproducing one failure

Create a private directory that you own. Record one selected run, retaining the
actual exit status even when the run fails:

```sh
run_dir="$(mktemp -d)"
python3 tools/test.py run --suite tooling-artifacts --record "$run_dir/selection.json"
status=$?
printf 'Test exit: %s\n' "$status"
```

For a failed record, inspect its `failed_cases` array and reproduce the original
selection, or add `--case` with one exact ID from that array:

```sh
python3 tools/test.py reproduce "$run_dir/selection.json"
# After an intentional edit, this is explicitly a changed-input rerun:
python3 tools/test.py reproduce "$run_dir/selection.json" --allow-changed-checkout
rm -f -- "$run_dir/selection.json"
rmdir -- "$run_dir"
```

The private, exclusively created report uses
`latent.local-test-selection.v1`, is bounded to 64 KiB and contains only suite,
source commit/dirty state, host/Python identity, recipe identity, source-only
fixture identity, exact selection, counts, outcome and exit status. Options are
currently the empty object. It does not contain executable paths, shell commands,
environment variables, log tails, patches, credentials or private source paths.
Duplicate keys, unknown fields/schemas, symlink/special-file inputs and arbitrary
options are rejected. A report is selection metadata, not a signed result or
permission to execute foreign code. Reproduction executes only the current
checked-out supported runner, once.

A changed commit, dirty worktree (including untracked files), changed host or
Python version is not an exact reproduction. Even a report made in the *same*
dirty checkout requires `--allow-changed-checkout`; no private patch is captured
to establish its identity. This option labels the result `changed-input-rerun`
and never bypasses recipe, fixture, case or preparation validation. A clean,
matching selection is labelled `same-input-selection`, not a guarantee that a
race or external condition will happen identically. A passed record cannot be
presented as a failure reproduction. A source change during execution marks the
record non-exact.

The child environment excludes provider credentials, `PYTHONPATH`, Git override
variables and Actions output paths. Normal bounded test diagnostics remain on
stderr and may contain test-generated text; they are **not a redacted log export**.
Inspect terminal output before sharing it. Rich #426/#434 failure records are not
yet accepted; their eventual adapters must use their maintained schemas instead
of guessing fields or executing embedded commands.

## Worked contributor paths

### 1. Small Rust logic change

First review the [focused Rust checks](../../VALIDATION.md) and optional local
preview. The new front end can validate its own relevant artifact-selection
logic now, but **does not yet replace focused Rust builds or libtests**:

```sh
python3 tools/test.py check --suite tooling-artifacts
python3 tools/test.py prepare --suite tooling-artifacts
python3 tools/test.py run --suite tooling-artifacts
```

The source-only suite leaves no prepared artifacts to clean up. A `--record`
file belongs to the caller and can be removed as shown above. The Rust change
itself still requires the package/feature tests specified in VALIDATION.md;
passing this tooling suite does not validate Rust behavior. A complete
prerequisite/prepare/run/cleanup Rust walkthrough through this front end is
blocked on #427 registering the fast Rust recipe and #428 supplying its prepared
harness. No guessed `rust-fast` suite is advertised.

### 2. Real runtime/component integration

Inspect the existing runtime selection before doing expensive work:

```sh
python3 tools/test.py explain --suite trust-currentness
python3 tools/test.py check --suite trust-currentness
python3 tools/test.py prepare --suite trust-currentness
python3 tools/test.py run --suite trust-currentness
```

The last three commands currently return exit 3, explicitly identifying
#427/#428. They do not silently compile the workspace or execute a stale AOT
compiler. Consequently they create no runtime state to clean up. To execute the
integration today, use the existing explicit build/fixture/runner/cleanup
sequence in VALIDATION.md and `.github/workflows/ci.yml`, including the exact
compiler copy and operator fixture owner. That coverage must remain required.
The completed walkthrough must consume the shared prepared manifest before the
front end can run this suite. A tooling test is not a substitute for real
component compilation, native execution, currentness or containment proof.

### 3. Angular/provider failure reproduction

The current browser selection can be planned without installing Node or Chrome:

```sh
python3 tools/test.py explain --suite browser-boundary
python3 tools/test.py check --suite browser-boundary
python3 tools/test.py prepare --suite browser-boundary
python3 tools/test.py run --suite browser-boundary
```

Again, prerequisite/preparation/execution commands return not-run until the shared
interfaces exist, and no browser/provider state is created. Use the existing
Angular/provider runners and their owned cleanup contracts for actual product
coverage today. Do not feed a browser receipt or captured environment into the
source-only reproduction command: it rejects that unsupported schema. The safe
record/reproduce/cleanup workflow above is executable for tooling failures, not
an Angular or provider qualification. Completing this product walkthrough
requires #427's registered case selection, #428's fixture identities and the
#434 diagnostic adapter. No container dependency is introduced for ordinary
local tests; explicit provider conformance retains its existing contract.

## Exit and validation contract

Exit 0 means the selected operation completed; only `state: passed` on a `run`
means all required cases executed. Assertion failures retain the child nonzero
exit. Missing prerequisites and incomplete/skipped required work are not-run
(exit 3), not success. Syntax errors use argparse's exit 2. Cancellation remains
cancelled (130 for interruption, 143 for termination); watchdog expiry is failed
(124), and bounded-output supervision failure is failed (125). No automatic retry
is performed. A requested report-write failure also returns nonzero without
replacing another run's file or concealing an existing test failure.

Run the interface and existing owner regression tests without Cargo or network:

```sh
python3 -m unittest tools.tests.test_local_tests tools.tests.test_ci_rust_artifacts
```

Tests compare local and CI plans, validate documentation/workflow commands,
exercise missing/changed selections and unsafe reports, and execute the actual
14-case source-only suite in temporary Git checkouts. A committed injected
assertion failure exercises record/reproduce and dirty-checkout refusal. Failing
PATH sentinels for Cargo, Rust, npm and download tools check the supported path;
these are regression instrumentation, **not a security sandbox or a proof against
absolute-path subprocesses**. No native runtime, Angular or provider execution
is claimed by these tests. The existing shared process owner remains responsible
for lifetime, output bounds and descendant cleanup.

## Remaining integration before #435 can close

- Consume the final #427 inventory and #428 preparation/validation operations;
  remove the native execution block only after commands, platforms, immutable
  fixture identities, custom harnesses and required counts are available.
- Reconcile #338/#339 interfaces with their owners; adapt #426/#434 failure
  metadata without creating a second timing analyzer or process supervisor.
- Run and document the three complete native contributor journeys, including
  cleanup and actual local-versus-qualification coverage. Link this guide from
  the #357 learning path when that content is integrated.

These are integration blockers, not passing acceptance criteria or new phase
dependencies. Source/phase evidence and the unconditional CI result gate are
unchanged.
