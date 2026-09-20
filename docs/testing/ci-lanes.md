# Bounded CI lane rollout

## Status and scope

This is **pre-integration work for [#431](https://github.com/KirilsTurkins/latent-service-fabric/issues/431), not its completed implementation**. The production workflow still runs the existing commands, in their existing jobs and order. No speedup, product qualification, build-free execution, artifact relocation, or process-cleanup qualification is claimed by these policy tests.

The implementation contains a small, compiler/network-free scheduling state machine and a coverage-slot drift guard. It deliberately does not invent replacements for the pending exact suite contract (#427), prepared-artifact manifest contract (#428), or timing records (#426). Actual runner integration, a separate fast correctness result, compatible immutable Wasmtime preparation reuse, live cancellation tests, and completed serial/two-worker qualification are outstanding.

The current full profile remains the compatibility fallback. No production deadlines, resource/security policies, release gates, installation requirements, branch protection, cache configuration, or product acceptance commands change.

## Inspected baseline and dependency graph

Source: `50f003dd006e0786494936c49e55dc683cf26fd6` on `development`.
Workflow: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), Git blob `c4725b368b9d2b4df19c7f6700f21a63178a1b6b`.

```text
profile --+--> docs ------------------------------------+
          +--> rust ------------------------------------+
          +--> catalog ---------------------------------+
          +--> msrv ------------------------------------+--> CI result (always)
          +--> contracts --> oci-registry ---------------+
          +--> sdks ------------------------------------+
          +---------------------------------------------+
```

`profile` and `docs` run for both profiles. The six other validation jobs are selected for `full`. The result job needs all eight preceding jobs and rejects an unknown profile or an unexpected result. Superseded runs use workflow/ref-scoped cancellation.

The machine-readable [baseline snapshot](../../tools/tests/fixtures/ci_lane_baseline.json) registers all **45 top-level `run` steps across nine jobs**, their job dependencies, and their triggering conditions. The snapshot includes the original immutable workflow identity so the full original commands remain attributable. It is **not** an exact test-discovery inventory: a change inside an existing command body requires the #427 command/case coverage review even when the slot guard passes.

| Current job | Coverage that must survive movement | Layout in this PR |
| --- | --- | --- |
| `profile` | Complete-change classification; renderer selection | Unchanged |
| `docs` | Pinned validator setup, documentation/SVG validation, profile tests | Unchanged |
| `rust` | Workspace/independent-package/target checks, Clippy, ordinary tests, doctests, signing compatibility, selected renderer, providers, security and Phase 2 resources | Unchanged |
| `contracts` | Contract validation and nested suites, generated fixtures/bindings, outcome matrix, optimization smoke, exported build inputs | Unchanged |
| `oci-registry` | Observed provenance and public-web input handoff, authenticated distribution, signed package round trips, owned registry cleanup | Unchanged |
| `catalog` | Recovery/routing/dormancy, supervision, explicitly selected 100,000-publication probe | Unchanged |
| `msrv` | Independent MSRV workspace check | Unchanged |
| `sdks` | Cross-language surfaces and exact TypeScript version check | Unchanged |
| `result` | Unconditional, fail-closed aggregate | Unchanged |

The drift guard rejects deleted, renamed, duplicated and unregistered top-level command slots, changed job dependencies, missing renderer setup conditions, altered catalog dispatch conditions and weakened superseded-run cancellation. It runs through the existing `python3 -m unittest discover -s tools/tests` invocation in `tools/validate_contracts.sh`; no issue-numbered workflow is added.

### The expensive Rust chain, including its late steps

The current Rust job first checks formatting; performs workspace, binding and independent production-package checks; runs both Clippy configurations; builds binaries and Cargo JSON test inventory; then executes ordinary workspace tests, admission/scheduler doctests, and the separate signing compatibility-feature tests. The ordinary suite still contains physical probes, so this entire boundary must remain exclusive until #427 classifies its exact cases.

When the existing renderer output is `true`, the same job then installs the pinned Node runtime, qualifies SSR/hydration, installs the component composer, builds and exercises the live browser boundary, builds the public Angular fixture, tests generic cells/shared HTTP, checks observed-build/source-separation boundaries, builds the observed application package, and validates admission/rendering/hydration. Several steps mix build, native preparation and execution; their current step duration is not an isolated rendering measurement.

After the renderer steps come the operator registry pull, S3 pull/test, Vault pull/test, NATS pull/event test/trigger test, and capability-policy CLI lifecycle. Do not drop these simply because a previous renderer step failed in a historical run.

The last combined Phase 2 step includes all of these responsibilities:

- Artifact-runner/resource-binary tests; a private operator fixture root; operator fixture export; operator/canary/offline runner tests; real operator workflow execution.
- A stripped, separately owned AOT compiler copy; exact trust-currentness cases; security-profile and offline workflows; publication fixture export and publication workflow execution.
- Separately stripped CLI/node resource copies; resource fixture export; resource schema/clock tests; source/lock/compiler/binary build identity; real resource-gate execution **and** validation of its receipt.

The corresponding compact receipts remain product evidence, not optional continuous-workstream output. The separate #238/PR #374 security, #239/PR #376 resource, #226/PR #410 reference and #236/PR #372 Angular acceptance authorities remain untouched. Workflow changes must also be reconciled with #355/PR #415 before the production switch; the baseline guard is not permission to discard that work.

## Scheduling policy

[`tools/ci_lanes.py`](../../tools/ci_lanes.py) accepts a graph already selected by the suite owner. It has no changed-file classifier, preview CLI, Cargo invocation, package installer, artifact loader or subprocess launcher.

A stage declares its prerequisites, resource group, total fixture/stage watchdog, exact expected case names and expected receipt roles. Preparation stages may have no cases; execution stages may not have an empty selection. Phase tags distinguish host compilation, component generation, native preparation, execution, teardown, transfer and cache warming. The stage watchdog is metadata for the eventual process-owner adapter, not an enforced timer in this module and never an override of a production activation deadline.

Worker count must be explicitly **one or two**. Resource-group capacities must be declared and may not exceed that bound. There is intentionally no newly chosen production default before a real comparison. A physical probe declares exclusive runner ownership: already running work drains before it begins, and other groups cannot run during its execution or teardown. A ready exclusive stage acts as a barrier rather than starving behind newly launched work. This is a same-runner guarantee; independently hosted Actions jobs do not share this scheduler.

The state transitions are:

```text
pending -> running -> retiring -> success / failure / cancelled
                    ^
           cancelling
pending -> blocked (unsuccessful prerequisite)
pending -> cancelled (whole-run interruption)
```

Dispatch reserves resource capacity atomically in the single coordinator. A process exit only records completion; **it does not release capacity**. The existing process owner must reclaim its descendants, provider fixtures and private temporary roots, then call `retire`. Missing retirement keeps the run incomplete and prevents dependent work. This contract must be wired to the existing runner owners/#434; these tests do not prove live OS-process cleanup.

Prerequisite failure blocks all transitive consumers. An unrelated diagnostic lane may still finish. Cancellation is latched, stops future dispatch, and returns the still-owned leases for cleanup. Cancellation between a successful exit and finished cleanup cannot become success. Reconstructed, foreign-run and retired leases cannot submit a completion.

A successful exit with missing observations, a wrong stage, missing/extra/duplicate cases, or missing/wrong/duplicate receipt roles becomes failure. Receipt-role matching is **not artifact authentication**: the #428 adapter must validate actual bytes/provenance/compatibility, and the product runner must validate its actual receipt before submitting these observations. The wrong-role unit control does not satisfy the real wrong-artifact negative control in #431.

The aggregate helper receives the exact expected job sets from the selection owner. Missing/unregistered jobs, failed/cancelled/skipped required jobs, and unexpectedly executed unselected jobs fail closed. It does not replace the current `CI result` implementation before the new lanes exist.

## Preparation reuse and proposed integration boundary

The eventual minimum useful layout is a prompt correctness result plus a co-located integration owner that prepares each compatible recipe once, schedules provider/renderer consumers, and isolates remaining physical work. This is a proposal, not the current workflow.

Cross-job relocation is not enabled. `ci_rust_artifacts.read_inventory` resolves absolute manifest/source/executable paths under the producing checkout, requires executables under `target/debug/deps`, and preserves runtime library search paths; `cargo_environment` also resolves the active Rust sysroot libraries. Uploading an arbitrary subset of `target/` and rewriting these paths is not a verified handoff. Until #428 specifies relocation and runtime dependencies, same-runner consumption avoids that correctness risk. This is not a measured claim that transfer would be slower.

No compiled native image is loaded by the scheduler. Any future immutable preparation reuse must preserve the tested cold-start, cache-miss and restart transitions. Each activation still needs fresh Store/application state and independently scoped authority. Mutable applications, catalogs and credentials must never be shared to save fixture time.

The integration order is: consume #427 selections and recipes; validate #428 prepared inputs; have existing runners execute only valid leased stages; record #426 stage outcomes; clean up through their process owners; retire leases; validate exact required completion; expose the result through the unconditional aggregate. Missing dependency interfaces must fail the selected integration rather than silently inventing another suite/manifest format.

## Validation and remaining acceptance

The compiler/network-free local checks executed for this change are:

```sh
python3 -m unittest tools.tests.test_ci_lanes \
  tools.tests.test_ci_lane_inventory.InventoryTests -v
```

Result: **43 tests passed**. They include 60 deterministic generated-DAG schedules (30 fixed seeds under each worker bound). These are synthetic scheduling/coverage models, not serial/two-worker LSF performance samples.

The separate `RepositoryInventoryTests` class reads the actual workflow with the already-pinned PyYAML dependency. It is required by normal repository test discovery; a missing workflow/dependency is a failure, never an intentional skip. It was not run in the limited local checkout used for the policy tests. A full checkout runs both modules, including that class, with:

```sh
python3 -m unittest tools.tests.test_ci_lanes tools.tests.test_ci_lane_inventory -v
```

| Required evidence | Current status |
| --- | --- |
| Exact selected-case discovery and narrow correctness build graph | Awaiting #427 integration |
| Validated build-free manifests, clean/reused real inputs and wrong-byte controls | Awaiting #428 integration |
| Before/after nested build/preparation/execution/teardown records | Awaiting #426 integration |
| Immutable native preparation reuse preserving fresh activation/cold transitions | Not implemented |
| Existing-runner dispatch, watchdog enforcement, live supersession cleanup | Not integrated or qualified |
| Complete affected CI execution with new lane layout | Not performed |
| Comparable serial/two-worker elapsed-job and summed-runner observations | Not measured |
| Transfer/extraction/cache-warming cost and peak resources | Unavailable, not zero |

Before selecting a default, collect completed serial and two-worker runs with identical source/recipes/cases and recorded environment/cold-warm state. Retain failed/cancelled/incomplete runs diagnostically, but exclude them from successful-complete speed comparisons. In particular, failed run `34983892143` with skipped late steps is not a successful full baseline. Report elapsed workflow time separately from summed job/runner time; include transfer/extraction and cache-warming work and retain unavailable resource fields as unavailable. Use #342 for offline comparison instead of adding another timing analyzer here.

Keep the PR draft and #431 open until those requirements are actually met. Reverting the policy and inventory additions restores the prior developer surface; there is no production lane, cache, resource or release configuration to roll back in this pre-integration change.
