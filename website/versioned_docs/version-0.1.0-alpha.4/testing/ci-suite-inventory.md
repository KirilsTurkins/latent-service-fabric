# Exact CI suites and host correctness

The current integration was refreshed against development
`9a99d1f364eb0c5d09b879fa857811820c8bb005`, plus the publication lease
regression from #458 at `7b3d9a4b1d3635538572e2203aaf737d939b35ed`: a successful whole-workspace
all-target/all-feature build and exact executable listings found **165 targets,
2,831 libtest cases and 149 explicit ignores**. The raw current discovery and binary
identities are in `tools/ci/evidence/current-discovery.json`; the older baseline
receipt remains historical. The two custom harness contracts are counted separately from libtest. The
compiler supervisor now provides an exact 23-case custom listing and completion
records; the sandbox retains its separate fixed completion marker. This is build/discovery evidence, not an ordinary
execution PASS. The shared deterministic tests moved to `latent-core`; their
compatibility tests, current AOT input validation, Angular fixture and physical
metadata owner are registered without dropping their execution contracts.

Website and MDX selection now retains the required site job in every profile,
including the host correctness profile. The aggregate independently checks the
complete job set. The reviewed command map preserves all 97 original required
run blocks and covers 129 current blocks plus 70 delegated script owners. The
temporary upstream-discovery workflow has been retired; the maintained CI owns
future build, discovery and execution receipts.


The repaired runner also completed the actual narrow five-package selection:
formatting, Cargo check, Clippy, build/discovery and all **88 active host tests**
passed. Cargo's diagnostic stderr is retained separately from its JSON artifact
stdout under one combined output bound. Source-file identities use explicit
`sha256` fields; scanning the updated inventory with pinned Gitleaks 8.30.1
reported no leaks. The complete maintained CI remains required.

The versioned contracts live in `tools/ci/suites.json` and
`tools/ci/commands.json`. The former identifies Cargo artifacts and exact test
names; the latter records the before/after required commands, their conditions,
and delegated script owners. They extend `tools/ci_profile.py` and
`tools/ci_rust_artifacts.py`; they do not introduce another change classifier.

## Boundaries and rollout

| Boundary | Coverage | Execution owner |
| --- | --- | --- |
| Host correctness | Bounded value, admission, scheduling, routing, metadata and interface tests; selected reverse dependents | `tools/ci_fast.py`, required `fast` job |
| Runtime contracts | The entire existing ordinary workspace invocation, containment, trust, RPC and component contracts | Existing `rust` and `contracts` jobs, with exact artifact discovery |
| Product integration | Real provider services, browser isolation, Angular build/admission and live hydration, OCI and SDK integration | Existing provider/browser runners and their existing CI jobs |
| Physical/full qualification | Bounded Phase 2 resource gate plus explicitly dispatched large catalog, native and measurement campaigns | Existing resource, native and qualification workflows and event conditions |

Fast feedback is **additional** for runtime-sensitive changes. Passing it does
not satisfy a selected runtime, provider, browser, security, SDK or resource job.
Full remains the fallback for unknown inputs, incomplete history, mixed inputs,
changed manifests/features/build recipes, deleted paths and shared infrastructure.
The 100,000-release catalog campaign remains explicitly dispatched; the bounded
resource gate remains required in the full profile. Release/security workflows
retain their original triggers and commands. Branch protection is not changed.

Only source changes whose *entire reverse-dependent closure* is confined to the
currently isolated state/effects/commit/workflows interface packages can select
the host-only profile. Their shared core suite is nonempty; their test-free
interface artifacts are explicitly registered as compile-only, not presented as
passing tests. As soon as a runtime package depends on one of these interfaces,
the manifest-derived closure selects full validation. This is intentionally a
small initial rollout, not a claim that provider-only changes are host-only.

## Exact selection and discovery

Every workspace/all-targets/all-features test artifact has a stable ID, manifest,
target kind/name/source, platform, feature/target recipe, prerequisites, timeout
and resource class. The exact expected test list and ignored list are committed.
Renamed, missing, newly ignored, unregistered and ambiguous test selections fail.
A new test needs a reviewed inventory update; a stale expected name cannot
silently turn into a successful zero-test invocation. Explicit selected ignored
cases are recorded once in the inventory and consumed by the existing artifact
runner. Provider fixture creation and cleanup stay with their existing runners.

The artifact and exact-list primitives are reused from issue #238 / PR #374's
`tools/phase3_security_artifacts.py` at `d70057996e1ec86bdb892184d80e1c60e4c1f791`.
Its accepted registered target kinds and Cargo-owned example directory are
extended to cover the complete workspace. Its security case matrix is **not** copied or replaced. Merging that
work should retain this shared selector module rather than introduce a second
security runner.

Both `harness = false` AOT executables have an explicit **no-list** contract,
source identity and exact success marker. They are never called with `--list` or
libtest arguments. Their execution remains in the ordinary full Cargo command;
a subsequent check requires both real markers exactly once. An empty custom
executable or a zero-test libtest summary cannot substitute for either harness.

The admission and scheduler compile-fail doctests remain a separate required
invocation. The signing suite still runs separately with
`ed25519-dalek/legacy_compatibility`. Their result contracts require two one-case
doctest summaries and the five compatibility cases respectively. They are not
assumed to run under `--all-targets`.

## Affected inputs and offline selection

The existing classifier reads workspace manifests directly, including renamed,
workspace-inherited, optional, normal, development, build and platform-specific
path dependencies. It takes reverse dependents before choosing bounded host
packages. The actual build artifact list is checked again for Wasmtime,
Cranelift, renderer and `latent-testkit` dependencies; convenience helpers cannot
quietly enlarge the host-only build into a runtime-fixture build.

WIT, Protobuf, fixtures, scripts, SDK sources, MDX, unknown paths and shared build
infrastructure conservatively select full validation. Existing documentation-only
rules are unchanged. Website validation/publication remains owned by issue #355.
The deterministic fixtures cover Rust-only, provider-only, renderer, docs/MDX,
mixed, deletion/rename, protocol, fixture, manifest and unknown changes.

Selection performs no Cargo invocation, build, installation or network operation.
The CI checkout supplies history; absent or ambiguous ancestry selects full.
NUL-delimited `--no-renames` diffs retain both sides of a rename. Issue #339's
committed/worktree preview can consume the same `classify_paths`/`Decision`
result; this change does not add a preview CLI.

`Decision.outputs()` includes the selected host packages and expected job set.
The unconditional `CI result` recomputes that set and checks every expected
`needs` entry. Failure, cancellation, missing outputs, unknown states and
unexpected skips fail the gate. Only intentionally unselected jobs may report
`skipped`; a missing job is never equivalent to an intentional skip.

## Execution evidence and contributor commands

Run the bounded tooling regression suite without a Rust build:

```sh
python3 -m unittest tools.tests.test_ci_profile tools.tests.test_ci_rust_artifacts tools.tests.test_ci_suite_inventory tools.tests.test_ci_suite_discovery tools.tests.test_ci_result tools.tests.test_ci_coverage
python3 tools/ci_coverage.py
```

The existing classifier emits the selected package JSON. The execution command
consumes it; it is not a preview or a classifier:

```sh
GITHUB_SHA="$(git rev-parse HEAD)" python3 tools/ci_fast.py \
  --packages-json '["latent-commit","latent-core","latent-effects","latent-state","latent-workflows"]' \
  --output target/ci-fast
```

Use the pinned toolchain. Receipts include exact executed command arguments,
individual formatting/check/Clippy/build durations, actual compiled package IDs,
all selected test names, ignore states, per-suite execution durations and final
pass/fail state. A build receipt is not reused as test-result evidence. Full CI
retains workspace discovery and ordinary/custom execution logs separately. On a
full change, the fast job additionally executes the genuinely narrow
reverse-dependent regression fixture and retains a separate receipt. That replay
does not waive the full affected CI jobs.

Baseline GitHub Actions run `35516070488` successfully built and discovered the
workspace at `047035f5d6007b8f4f1e84ff3ddd02a529ae3077`: **160 executable targets,
2,729 cases, 147 deliberately ignored cases, 344 compiled package identities**.
The measured Cargo build took **298.059 seconds**, including that command's
compilation/dependency work, not toolchain setup. The unchanged raw discovery
receipt is `tools/ci/evidence/baseline-discovery.json`. This establishes discovery
completeness and names, **not execution success** for the runtime test suite.
Actual host/full execution qualification must use the current CI receipts.

### Hosted host-correctness execution, 2026-09-21

[CI run 35553538203, attempt 1](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35553538203)
executed the affected host set and the separate narrow dependency fixture for
PR #445 head `149abd76ad4752007babf467c46d392c7464519d`. Both unchanged receipts
identify the tested pull-request merge `888f9fceb36344675ee1604c02d0acddd9c13234`.
They are actual execution receipts, separate from the earlier listing-only
discovery evidence.

| Observed selection | Selected packages | Compiled package identities | Active cases | Cargo test build | Listed test execution |
| --- | --- | --- | --- | --- | --- |
| [Affected host set](../evidence/ci-suite-inventory-35553538203/affected.json) | 14 | 95 | 358 | 24.947669 s | 1.258160 s |
| [Narrow reverse dependents](../evidence/ci-suite-inventory-35553538203/narrow.json) | 5 | 21 | 88 | 3.049295 s | 0.070497 s |

The narrow selection contains `latent-commit`, `latent-core`, `latent-effects`,
`latent-state` and `latent-workflows`. Its actual dependency list contains no
Wasmtime, Cranelift, renderer or `latent-testkit`. The timing columns are the
observed Cargo test build and sum of per-suite execution durations; they exclude
job setup, formatting, checking, Clippy and the affected set's separate doctests.
They are not cold-cache performance guarantees. Both receipts preserve every
command, discovered case, ignore state and compiled package identity, with an
adjacent checksum for their exact bytes.

The full CI run also completed successfully: exact workspace discovery,
Rust/runtime/product execution, six-language provider contracts, catalog, MSRV,
OCI, website and selected security checks passed. All 18 PR checks were successful
or intentionally unselected. The host receipts remain evidence for their own
scopes; they do not substitute for those separately executed jobs.

## Before/after command review

The baseline is `50f003dd006e0786494936c49e55dc683cf26fd6`. All **97 existing required
run blocks** are represented in `commands.json`, including delegated shell/Python
owners and all native/security/measurement workflows. No old command is deleted.
The four changed blocks and same-change replacements are:

| Original block | After this change | Coverage preserved |
| --- | --- | --- |
| Documentation/profile tests | Original validators plus inventory, selection, discovery and aggregation regressions | Documentation rules and SVG validation still execute |
| Workspace tests | Same full Cargo command, captured log and exact discovery/custom marker checks | All ordinary tests, both AOT custom harnesses, separate doctests and signing compatibility remain required |
| MSRV workspace check | Original full check under `full`; selected transitive package check under the narrowly qualified `fast` profile | Runtime-sensitive changes still check the entire workspace at MSRV |
| Inline CI aggregation | Independently tested `tools/ci_result.py` with the complete expected job topology | The unconditional protected check stays fail-closed |

The existing build/check/Clippy, generated bindings, production-package checks,
Angular/provider/OCI suites, catalog regressions, SDK matrix, optimization smoke,
security profile, offline/publication workflows, bounded resource gates and
explicit large qualification commands retain their existing owners and full
triggering conditions. Source/foundation validators run in the docs job only
when `fast` omits `contracts`; the full profile still runs them once through
`validate_contracts.sh`, preserving issue #183's duplicate-validation removal.
The inventories and this map are review inputs: the validator does not
silently regenerate or bless modified commands, ignored cases or test lists.

The integration with merged #449 preserves its three inventory-owned process
contracts and every OCI/renderer prerequisite, normal/fault check and diagnostic
upload. Deterministic dependency checks remain in the documentation job. The
supervisor completion validator was checked against the actual failing CI log:
all 23 cases and the separate production sandbox marker are present.
