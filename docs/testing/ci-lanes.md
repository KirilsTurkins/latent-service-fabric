# Bounded runtime, provider and renderer CI lanes

This document owns the execution-layout decisions for issue #431. Exact suite and
case selection remains owned by 'tools/ci/suites.json'; exact workflow command
review remains owned by 'tools/ci/commands.json'. The lane implementation consumes
those contracts instead of introducing a second changed-file classifier, artifact
manifest, process supervisor, or result gate.

## Current production layout

The full Rust job remains the single producer for the compatible host build:

1. Cargo checks, Clippy and the ordinary all-target/all-feature workspace build
   run exactly once.
2. The successful Cargo JSON inventory is verified by
   'tools/ci_suite_discovery.py' and remains the source of prepared libtest
   identities.
3. AOT inputs are prepared through the existing authenticated preparation
   boundary.
4. Ordinary workspace tests, doctests, signing compatibility, metadata and
   Phase 3 security qualification complete before product integration starts.
5. When renderer coverage is selected, the browser component is composed once
   from the already built workspace input.
6. 'tools/run_ci_lanes.py' dispatches the co-located provider and renderer lanes.
7. The existing Phase 2 delivery/security/resource work, isolated Angular T1
   compiler and protected T1 qualification remain after the lanes. They are not
   overlapped with product integration because their physical/resource evidence
   must remain uncontaminated.

No native target tree is uploaded to another Actions job. #428's prepared-artifact
boundary authenticates same-checkout Cargo artifacts and their runtime link paths;
this change deliberately keeps compatible consumers on the producing runner
rather than inventing path rewriting or cross-job native relocation.

The fast correctness job delivered by #427 remains a separate prompt result.
'CI result' stays unconditional and continues to aggregate the complete selected
job set. The lane coordinator is inside the required Rust job, so any missing,
failed or cancelled required lane makes that job fail.

## Bounded scheduler

'tools/ci_lanes.py' is the small compiler/network-free scheduling policy. It
accepts an already selected graph and supports exactly one or two workers. Resource
groups are declared and capacity remains charged until the process owner confirms
teardown.

The production graph has two independent execution stages:

| Stage | Resource group | Selected work |
| --- | --- | --- |
| provider-integrations | provider | S3 blobs, Vault secrets, NATS events, NATS triggers, capability-policy CLI |
| renderer-integrations | renderer | Angular SSR/hydration, browser boundary, generic renderer/node cases, build/package admission and hydration |

The renderer stage exists only when the existing profile output selects renderer
coverage. Provider coverage remains required for every full profile.

Normal pull-request and push CI uses **two workers**. 'workflow_dispatch' exposes
'ci_lane_workers' with only 1 or 2, so the same source and selection can be
run serially for comparable evidence without changing commands, cases or resource
policy.

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

'tools/ci_lane_inventory.py' now checks only lane-specific architecture. The more
general 'tools/ci/commands.json' still reviews every required run block and hashes
the delegated script owners. The lane workflow command explicitly names its
Python child owners so moving them behind a coordinator does not remove them from
command-owner review.

The structural guard requires:

- the complete current job set and unconditional CI result;
- superseded-run cancellation;
- one lane coordinator using the prepared workspace inventory;
- renderer setup/component preparation under the existing renderer condition;
- removal of the old consecutive provider/renderer run slots;
- Phase 2/T1 physical work after the lane; and
- manual catalog scale remaining manual.

Rollback is mechanical: restore the prior serial run slots and remove the two lane
scripts, worker input and lane receipts. It requires no runtime, release,
security, resource-policy, installation or branch-protection change.
