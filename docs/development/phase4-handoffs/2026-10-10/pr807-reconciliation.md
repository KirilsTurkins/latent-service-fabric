# PR #807 Java futures reconciliation

## Owning issues and comments

PR #807 implements part of [#741](https://github.com/KirilsTurkins/latent-service-fabric/issues/741)
and the shared runtime contract in [#736](https://github.com/KirilsTurkins/latent-service-fabric/issues/736).
Its bounded UTF-8 decoder also contributes to Java HTTP compatibility in
[#727](https://github.com/KirilsTurkins/latent-service-fabric/issues/727),
[#728](https://github.com/KirilsTurkins/latent-service-fabric/issues/728) and
[#688](https://github.com/KirilsTurkins/latent-service-fabric/issues/688).
It closes no ticket. All five issues remain open.

The review includes the bodies and comments of those issues, the completed
design investigation #695, and dependencies #678, #679, #681, #682 and #737.
Their comments require unchanged library APIs, admission before enqueue,
independent executor progress, finite timers, retained physical owners after
logical cancellation, bounded retirement and original capability/budget limits.
The two unchanged-library matrix, aggregate accounting/fairness/late-wake and
authenticated server lifecycle qualification remain with their owning issues.
ADR 0060 remains Proposed; this change enables no production runtime profile.

The original PR head is `406f9e4075f1804051ff831c9395e15a9d1cdee4`.
A normal merge incorporates development
`01748829e2225a9655c87c6a02e3030f6457a1d8`, including its current transaction
checks, generated clients, native preparation, HTTP ownership and CI inventories.

## Snapshot decisions

- #894 has exactly the original #807 head and adds no implementation.
- #951 preserves the V5 native-loader CI repair. Development already has its
  source-bound fixed-result lowering review; its guard is retained.
- #940/#949 preserve the TimeUnit/warm-runtime work. The TimeUnit compiler
  implementation matches #807, including its model/native controls.
- #937 preserves exception-array reference spills already present in
  development. Its older compiler helper would remove development's
  activation-aware wait bridge, so the current helper is retained.
- #880 preserves the lazy default async pool repair already present in #807.
  Idle workers use no timeout timer; the original two timer slots remain
  available for application waits.
- #891 preserves the historical maximum-body comparison and #895 preserves
  the separate authenticated lifecycle candidate. Neither establishes current
  deployment/rollback/CAS/disconnect or full HTTP qualification for this head.

## Implementation and CI repairs

The opt-in Java profile implements owned default CompletableFuture workers,
continuation submission, timed monitor/future waits, bounded independent queues,
original exception/cancellation behavior, and draining of accepted work after
root return. Application code uses ordinary standard APIs. Compiler controls
bind transformations to the pinned TeaVM model, native and method identities;
unknown owners retain the existing refusal behavior.

The shared compatibility builder accepts explicitly declared V5 interfaces while
preserving default V4 selection and development's validated captured transaction
profile. Transaction profile, binding, schema and exact WIT digests remain
required. Java build observations capture the selected compiler profile and
source origins without providing runtime authority.

The old CI run
[37693483053](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/37693483053)
failed the closed recorder-vocabulary test in both Rust qualification and Python
contracts. #807 introduced `SchedulerImmediateCapacityUnavailable` and
`SchedulerQueueFull` without their Python diagnostic mappings. Both exact tokens
are now mapped. Unknown or malformed shapes still remain unclassified, and the
new Rust test checks exact code, retryability and public details.

Reconciliation also restores initialization of the captured file set before
Java source capture. An ambiguous inner lock or tampered outer CAS now retains
its original refusal instead of being masked by `UnboundLocalError`. The new
failure-path control verifies the original error, unchanged source, no compiler
dispatch and no success marker. Existing contract guards and test cases remain.

UTF-8 validation rejects malformed, overlong, surrogate and out-of-range input
before one String decode, under the original byte/item bounds. It avoids the
second encoder buffer. Historical signed HTTP body comparisons at source
`21031d9c` remain attributed to that source.

## Current evidence and remaining boundaries

Temurin 25.0.4.1+1, Gradle 9.1.0, TeaVM 0.15.0 and WASI SDK 29 build fresh
ordinary-thread and default-CompletableFuture components. Each has three JDK
reference runs of four modes returning 42, plus the maintained compiler/source
ownership controls. Their compiler reports retain `component-built-unqualified`,
`qualification: pending` and `nodeExecution: not-run`.

Separately, the two explicit Rust tests sign and admit those exact components
through the local-service artifact repository and execute four modes three
times each. All 24 guest invocations return `[42]`. Cold compilation prepares the
exact signed publication before activation, creates no guest store and retains
its separate 600-second setup watchdog. Each actual invocation keeps the original
120-second, 10-billion-fuel, 64-MiB ceilings and task/executor/queue/wait/timer/
result/native-owner limits of 5/3/8/8/2/8/2.

After every call, the bounded idle assertion checks zero active activations,
cancellation registrations, scheduler leases/queue, instance reservations,
guest stores and broker calls/sessions/handles/results/buffer bytes.
The [fresh evidence receipt](../../../testing/evidence/java-futures-pr807-reconciliation-2026-10-10.json)
binds component/source digests, SDK inputs, runtime test sources and consumption
for all 24 calls. This is signed local-service fixture evidence; ordinary node
installation and the complete unchanged-library matrix remain separate gates.

The ordinary local-service suite passes 31 cases with its two existing compiler
fixture ignores; both ignored fixtures also pass when explicitly selected above.
All ten local-service diagnostics cases pass. The 97 Java SDK/controller cases
pass, including the real JDK UTF-8 source control's 9,466 observations.
Strict Clippy passes for latent, latentd, latent-testkit and latent-admission;
Wasmtime Clippy, workspace formatting and build-foundation validation pass.

The complete maintained Python suite runs 3,733 cases on Python 3.13.5 Linux:
3,715 pass and the 18 existing environment guards skip. All 185 focused
compatibility, Java authoring, diagnostics and CI contract cases also pass.
CI coverage retains 88 baseline and 280 current required run blocks with 148
delegated script owners. New test inventories preserve every prior case and
guard, and include the scheduler-capacity and source-capture regressions.

Hosted CI is not awaited after push. No merge, issue closure, production profile
enablement, full Java/HTTP qualification or refreshed historical HTTP receipt is
claimed.

## Follow-up CI discovery repair

The next hosted run's [Rust tests job](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38056071846/job/114224793136)
stopped before test execution with
`latent-wasmtime.test.local-service: unexpectedly-ignored-case`. The original
reconciliation omitted the new compiler-gated CompletableFuture test from the
exact case and ignore-state inventory. Its existing `#[ignore]` and component
requirement are unchanged.

The corrected inventory includes all 33 actual local-service cases, both existing
opt-in Java fixture cases, their exact ignored leaf names and a matching minimum
case count. All previous cases, selections and other suite records remain intact.
The original refusal is reproduced against the actual Linux test binary before
the corrected inventory is validated. All 89 focused inventory/discovery,
fragment, CI contract and coverage tests pass. Hosted CI is not awaited after
the repair push.

The production discovery checker also validates every Wasmtime test target
against a fresh all-targets Cargo artifact inventory: 557 active cases match
the exact registry. This verifies discovery; it does not repeat guest execution
or replace the signed component evidence above.
