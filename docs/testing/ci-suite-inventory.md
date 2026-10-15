# Exact CI suites and host correctness

The current catalogue is `tools/ci/suites.json` plus bounded additive fragments
under `tools/ci/suites.d/`. The [loader](../../tools/ci_suite_inventory.py) checks
the combined contract; fragments can add target suites but cannot replace shared
recipes, selections or existing identities. Use `tools/test.py list` and `plan`
for the selected checkout rather than treating a historical target/case count
as today's inventory. Listing metadata is not executable discovery or a pass.

Website validation is required in every profile, including host correctness.
The result aggregator independently checks the complete expected job set.
Workflow command contracts preserve historical replacement obligations alongside
current run blocks and delegated owners. Their current counts come from
`tools/ci_coverage.py`, not a copied count in a guide. See the
[ownership-local contract guide](ci-command-contracts.md) for scoped review.

The retained `tools/ci/evidence/current-discovery.json` filename denotes an
original build/discovery snapshot at `9a99d1f3`, not current-head qualification.
The later publication regression and shared-helper/AOT integrations retained
separate exact sources and cases. Earlier host execution receipts below also
keep their original source; the maintained CI produces fresh discovery and
execution receipts for subsequent changes.

The versioned contracts live in `tools/ci/suites.json` and
`tools/ci/contracts/`. The former identifies Cargo artifacts and exact test
names; the latter shards workflow policy, per-job commands and historical
replacements, per-script owner fingerprints, and per-Python-module exact cases.
See the [contract update and rebase guide](ci-command-contracts.md). They extend `tools/ci_profile.py` and
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

Only source changes whose *entire reverse-dependent closure* fits the current
`narrowPackages` allowlist can select the host-only profile. The larger
`fastPackages` set supplies candidate feedback for full changes too; it is not a
host-only permission list. Current state/core edits require full validation,
while an isolated workflows edit can remain narrow. The actual manifests decide,
not the package's historical interface role. Empty test targets must be explicitly
compile-only; they cannot become successful zero-test execution. Provider-only
changes are not implicitly host-only.

## Exact selection and discovery

Every workspace/all-targets/all-features test artifact has a stable ID, manifest,
target kind/name/source, platform, feature/target recipe, prerequisites, timeout
and resource class. The exact expected test list and ignored list are committed.
Renamed, missing, newly ignored, unregistered and ambiguous test selections fail.
A new test needs a reviewed inventory update; a stale expected name cannot
silently turn into a successful zero-test invocation. Explicit selected ignored
cases are recorded once in the inventory and consumed by the existing artifact
runner. Provider fixture creation and cleanup stay with their existing runners.

The [artifact reader](../../tools/ci_rust_artifacts.py) and shared discovery owner
validate exact Cargo package/target/source, executable and runtime-library
identities. Security selections consume the same primitives while retaining
their own case matrix. Do not introduce a competing selector or replace a real
security/runtime case with an inventory-only success.

The two `harness = false` AOT executables have distinct contracts. The supervisor
implements the registered **custom-list** protocol with exact custom case names
and completion records. The sandbox declares listing **unsupported** and uses
its separate production sandbox success marker. Neither is treated as ordinary
libtest or a successful zero-test target. Full Cargo execution and the prepared
AOT runner retain their exact listing/completion checks; see
[prepared AOT inputs](../development/aot-test-inputs.md).

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

WIT, Protobuf, fixtures, scripts, SDK sources, unknown paths and shared build
infrastructure conservatively select full validation. Pure reviewed website/MDX
changes select the website profile; mixing them with product inputs selects full.
Approved prose/SVG changes retain the docs profile. Every profile requires the
website validation job; publication remains a separate operation.
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

Run the bounded tooling regression suite on Linux x86_64 without a Rust build.
Python runner/process fixtures can still require Linux ownership, Bash and
filesystem behavior; running Python on Windows does not qualify those paths:

```sh
python3 -m unittest tools.tests.test_ci_profile tools.tests.test_ci_rust_artifacts tools.tests.test_ci_suite_inventory tools.tests.test_ci_suite_discovery tools.tests.test_ci_result tools.tests.test_ci_coverage tools.tests.test_ci_contracts
python3 tools/ci_coverage.py
```

For an explicitly selected host-only workflows change, derive the current
package JSON from the existing classifier. The following execution command
consumes that selection; it is not itself a preview or classifier. It compiles
and executes tests and needs the pinned Linux toolchain:

```sh
packages="$(python3 - <<'PYCODE'
from tools.ci_profile import classify_paths
decision = classify_paths(['crates/latent-workflows/src/lib.rs'])
assert decision.profile == 'fast'
print(decision.outputs()['fast_packages'])
PYCODE
)"
GITHUB_SHA="$(git rev-parse HEAD)" python3 tools/ci_fast.py \
  --packages-json "$packages" --output target/ci-fast
```

Use the pinned toolchain. Receipts include exact executed command arguments,
individual formatting/check/Clippy/build durations, actual compiled package IDs,
all selected test names, ignore states, per-suite execution durations and final
pass/fail state. A build receipt is not reused as test-result evidence. Full CI
retains workspace discovery and ordinary/custom execution logs separately. On a
full change, the fast job additionally executes the genuinely narrow
reverse-dependent regression fixture and retains a separate receipt. That replay
does not waive the full affected CI jobs.

## Historical discovery and execution

These observations retain their recorded sources and original package roles.
They do not define current counts, package selections or runtime support.

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

The original rollout baseline was `50f003dd006e0786494936c49e55dc683cf26fd6`.
The later reviewed snapshot at development
`2c52ff1a9d260da2fbcd81aa0c420926a5820d98` contains **88 historical replacement
obligations and 208 current run blocks**. Issue #732 migrates those exact records
without resetting them to source discovery; all historical relationships remain
active in their destination job contracts. The archived snapshot is
`tools/ci/history/commands-v1.json`, not a validation input. The original
four replacement categories remain:

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

The catalogue retains its three inventory-owned OCI/renderer process contracts,
their prerequisites, normal/fault controls and diagnostics. Deterministic
dependency checks remain in the documentation job. Completion is checked against
the actual current listing and execution logs, never inferred from an earlier
successful or failing workflow.
