# Bounded runtime, provider and renderer CI lanes

This document owns the execution-layout decisions for issue #431. Exact suite and
case selection remains owned by 'tools/ci/suites.json'; exact workflow command
review remains owned by 'tools/ci/contracts/'. The lane implementation consumes
those contracts instead of introducing a second changed-file classifier, artifact
manifest, process supervisor, or result gate.

## Current production layout

The required `rust` job uses a fixed seven-variant matrix:

| Variant | Retained obligations |
| --- | --- |
| checks | Formatting, deterministic dependency checks, workspace and independent production checks, bindings and both Clippy policies |
| tests | Complete discovery, authenticated AOT preparation, ordinary workspace tests, doctests, signing compatibility, metadata, security and bounded resource units |
| provider | Fresh pinned S3 fixture, positive/negative S3 runs, Vault, NATS events/triggers and capability-policy CLI |
| renderer-public | Browser component, SSR/hydration, browser boundary, generic Angular/node cases and discovery fault control |
| renderer-angular | Build contracts, fresh actual Angular package, admission/runtime and hydration |
| publications | Static/framework publication, offline delivery, operator, security and bounded physical resource workflows |
| angular-t1 | Fresh actual Angular package, isolated compiler, signed T1 fixtures and protected physical qualification; original manual resource options |

Every runtime variant runs the unchanged workspace/all-target/all-feature Cargo
producer. Its fresh JSON inventory remains on that runner with its consumers.
The tests variant owns complete discovery and the original ordinary test command
vectors. Required renderer variants retain the existing profile selection. The
source-built S3 receipt belongs to the provider variant. Physical qualification
owns separate runners from product integration, preserving uncontaminated
per-job measurements.

The required `contracts` job has independent Python, bindings, runtime,
standalone, SDK-provider, measurement-smoke and optimization-smoke variants.
The complete Python suite runs in the foreground without concurrent native
fixture writers. Each native variant prepares fresh local fixtures and runs its
original exact cases. Frozen collector build-policy rejection stays enforced.
`tools/validate_contracts.sh` still runs all validation by default; unknown
selections fail. See [performance and coverage](../development/ci-performance.md).

No native target tree is uploaded to another Actions job. #428's prepared-artifact
boundary authenticates same-checkout Cargo artifacts and their runtime link paths;
compatible consumers remain on their own producing runner with current source
and inventory identities.

The fast correctness job delivered by #427 remains a separate prompt result.
'CI result' stays unconditional and continues to aggregate the complete selected
job set. Both matrices use `fail-fast: false` and propagate every failure. Any
missing, failed or cancelled required variant prevents a successful result.

## Bounded scheduler

'tools/ci_lanes.py' is the small compiler/network-free scheduling policy. It
accepts an already selected graph and supports exactly one or two workers. Resource
groups are declared and capacity remains charged until the process owner confirms
teardown.

The coordinator supports these exact execution stages:

| Stage | Resource group | Selected work |
| --- | --- | --- |
| provider-integrations | provider | S3 blobs, Vault secrets, NATS events, NATS triggers, capability-policy CLI |
| renderer-integrations | renderer | Angular SSR/hydration, browser boundary, generic renderer/node cases, build/package admission and hydration |
| renderer-public-integrations | renderer | The complete public/browser/generic portion and its negative control |
| renderer-angular-integrations | renderer | The complete actual Angular build/package/admission/hydration portion |

The renderer stage exists only when the existing profile output selects renderer
coverage. Provider coverage remains required for every full profile.

The two renderer portions have disjoint case sets whose union is the original
complete renderer selection. Required CI selects one stage per matrix variant;
the default local coordinator still supports the original provider-plus-renderer
graph.

Normal pull-request and push CI configures **two workers**. 'workflow_dispatch' exposes
'ci_lane_workers' with only 1 or 2, so the same source and selection can be
run the local combined graph serially for comparable evidence without changing
commands, cases or resource policy. This setting does not serialize Actions
matrix variants.

A failed prerequisite blocks only its consumers. Independent work may finish.
Whole-run cancellation is latched; already-started leases are not released until
the underlying owned process has reclaimed descendants. A successful child exit
followed by cancellation before cleanup cannot become a passing lane.

## Prepared inputs and exact selection

'tools/run_ci_lanes.py' reads the current 'tools/ci/suites.json' before dispatch.
The child worker then consumes the existing workspace Cargo inventory.

Provider selections are the existing registered s3-blobs, vault-secrets,
nats-events and nats-triggers cases. The renderer receipt binds the existing
browser-boundary selection, the exact angular-renderer process-contract cases
(including the selected latentd Angular HTTP case), and the maintained
angular-build ignored case.

The coordinator accepts a child receipt only when:

- the lane identity and schema are current;
- every expected logical step completed;
- the exact selected-case set matches the central inventory;
- a nonempty stage timing record is present; and
- the child reports success.

A missing receipt, renamed/extra case, missing timing, wrong step list or failed
child cannot unblock the scheduler.

## Process ownership, watchdogs and cancellation

Each lane worker is launched through 'owned_test_process.run_owned_async'. That
owner uses the existing Linux subreaper contract and does not return until
descendant retirement is acknowledged. The scheduler calls retire only after
that acknowledgement.

Inside the lane, 'TestRun' supplies one total watchdog, private fixture state,
redacted diagnostics, source identity, artifact digests, cleanup and per-stage
monotonic elapsed records. Behavioral activation deadlines inside LSF and its
provider/browser fixtures are unchanged; the lane watchdog never rewrites them.

GitHub's existing 'concurrency.cancel-in-progress: true' remains required.
'run_ci_lanes.py' installs termination handlers, cancels live async owners, and
waits for 'run_owned_async' to finish cleanup before recording the lane as
cancelled.

## Real negative controls

The integrated lane contains failure controls rather than relying only on the
scheduler model:

- The provider lane first completes the real S3 suite, then supplies the same
  S3 runner with a Cargo inventory whose S3 executable identity was replaced by
  a nonexistent target-owned harness. Acceptance is a failure; the runner's
  finally cleanup still owns the MinIO fixture.
- The renderer lane performs real prepared-harness discovery and then invokes
  the maintained after-discovery fault. Its diagnostic is checked with
  'check_owned_diagnostics.py'; no selected renderer case executes after that
  injected failure.
- Unit regressions reject missing lane receipts, case/step/timing drift,
  cancellation-before-retirement, duplicate/foreign leases and missing required
  job results.
- Existing #434 owned-process tests continue to exercise cancellation and
  descendant cleanup independently of this orchestration layer.

These controls do not turn a failed product run into evidence. The normal provider
and renderer runs must still complete successfully.

## Timing evidence

Each child diagnostic records named preparation/execution/teardown stages through
'TestRun'. The aggregate 'latent.ci-lanes.v1' receipt records:

- source revision when Actions supplies it;
- exact Cargo-inventory SHA-256;
- selected worker count and renderer selection;
- aggregate elapsed time;
- terminal stage states/reasons; and
- the validated child receipts and their stage timings.

Actions retains the complete '$RUNNER_TEMP/ci-lanes/' directory for 14 days.
Browser receipts and existing Phase 2 receipts remain separate artifacts.

The serial pre-lane baseline for the current integration source is Actions run
35634834989 at development ffa90dc3f76f4bc589be63d313103fdb67fb5f1b.
That run uses the old consecutive renderer/provider layout. It was still executing
when this implementation revision was first published, so no completed speedup
claim is made from it here. The PR must retain a completed two-worker run and a
comparable one-worker dispatch before an elapsed-time improvement is stated.

Elapsed workflow time and summed runner time are distinct. Cache restore, npm
preparation, Docker pulls, component composition and any transfer work remain
visible stages rather than being subtracted from the comparison. Resource fields
that are unavailable are unavailable, not fabricated zeros.

## Coverage and rollback

`tools/ci_lane_inventory.py` checks both the lane-specific architecture and the
complete execution-relevant workflow model. The ownership-local
`tools/ci/contracts/` records review every required run block and retain per-script
fingerprints until an enforced replacement approval boundary is verified. The lane workflow command explicitly names its
Python child owners so moving them behind a coordinator does not remove them from
command-owner review.

The structural guard requires:

- the complete current job set and unconditional CI result;
- superseded-run cancellation;
- every fixed Rust and contract matrix variant, without exclusions or failure masking;
- one lane coordinator per selected integration variant, using its fresh workspace inventory;
- renderer setup/component preparation under the reviewed variant and profile conditions;
- removal of the old consecutive provider/renderer run slots;
- Phase 2/T1 physical work on isolated producing runners; and
- manual catalog scale remaining manual.

Rollback restores the previous monolithic required jobs and reviewed contract
dispatcher, then updates the structural snapshots. It requires no runtime,
release, security, resource-policy, installation or branch-protection change.
