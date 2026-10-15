# Test invariants

This document maps current invariant owners and separates their requirements
from historical Phase 0, Phase 1 and Phase 2 evidence. The retained
clean-checkout [completion receipt](../../benchmarks/phase0/receipts/native-linux-2026-08-30-b932a935/gate-summary.json)
authorized Phase 1 for its recorded August 30 execution identity. It does not
describe the current runtime or claim production readiness. See the
[historical Phase 0 decision](../phase-0-completion.md), completed
[Phase 1 gate](../phase-1-completion.md), and
[extension results](../phase-1-extension-completion.md), and completed
[Phase 2 gate](../phase-2-completion.md) for their separate scopes.

## Current invariant owners

Historical evidence below keeps its original source and configuration. Current
implementation owners and their focused conformance are:

| Boundary | Maintained owner and evidence entry point |
| --- | --- |
| Admission, fixed cells, fresh stores and cleanup | [Data plane](../architecture/data-plane.md), [execution cells](../architecture/execution-cells.md), [activation lifecycle](../activation-lifecycle.md). Cancellation never refunds physically live work. |
| Publication and current authority | [Control plane](../architecture/control-plane.md), [security](../architecture/security.md), [capability bindings](../runtime/capability-bindings.md). Cached code/receipts never renew grants. |
| Descendant progress and budgets | [Descendant reservations](../runtime/descendant-budgets.md), [local calls](../runtime/local-service-invocation.md). Parents retain their cells; saturated capacity rejects rather than creating hidden workers. |
| Host-owned atomic commands and fresh queries | [Commit protocol](../protocol/commit-protocol.md), [state/effects](../architecture/state-and-effects.md). Original command, attempt, result and effect identities remain separate from activation status. |
| Retention and recovery | [Reserved recovery/retention](../architecture/transaction-retention.md), [protected recovery](../architecture/protected-offline-recovery.md), [installed native qualification](installed-transaction-recovery.md). Epoch, decoder, current permission and actual retirement fences remain required. |
| Cluster freshness and durable workflows | [Cluster conformance handoff](../architecture/cluster-freshness-handoff.md) and [roadmap](../roadmap.md). Distributed and workflow paths remain unimplemented. |

Phase 3 capability delivery is no longer future work. Development also contains
explicit Phase 4 runtime/recovery profiles, whose focused tests and source
registration do not close the full application, terminal/pending native or
packaged acceptance gates. Do not extend a historical zero-idle or RSS result
to new provider/state populations without their own measured configuration.

## Phase 0 exercised subset

The fresh executable baseline and retained evidence prove, for their recorded
local/native-Linux environments and configurations:

- a fixed two-cell generic pool never exceeds active capacity, and its
  four-waiter queue rejects overflow deterministically;
- success, domain error, trap, timeout, explicit cancellation,
  memory-pressure/resource exhaustion, and bounded-queue rejection return to
  a reusable/idle pool state or fail before a lease is retained;
- every tested failure cause is followed by a successful echo without poisoning
  the retained composition;
- no measured terminal path retains an active lease, queued waiter,
  cancellation registration, invocation, Wasmtime store, host state, component
  instance, temporary buffer, cancellation probe, retained log, or quarantine;
- prepared-component cache growth remains within its configured bound and
  explicit release clears the cache;
- configured runtime workers remain fixed, process count remains one,
  listeners/open sockets remain zero, and cell capacity remains fixed across
  component loading and repeated invocations; and
- calibration and profiling preserve fresh-store isolation, fixed topology,
  bounded node-owned state, cleanup proof before reuse, and the rejection of
  native execution, persistent AOT/compiler cache, and store/instance reuse.

The Wasmtime epoch-interruption mechanism may add one bounded helper OS thread
after preparation. The invariant is fixed configured/node runtime topology,
not byte-for-byte constancy of raw OS thread count while an engine runs.

The retained August 30 three-process resource soak passes its hard
logical-resource and terminal-topology checks and proves a calibrated plateau
for the recorded native-Linux configuration: its seven-process calibration is
matched and its descriptor-lifecycle evidence is complete. It remains
single-host observational evidence and does not authorize Phase 1 by itself;
the full gate authorizes only after also verifying source identity, archive
integrity, profiling, and a fresh baseline.

## Phase 1 selected deterministic evidence

The [bounded conformance profile](phase-1-conformance.md) exercises the actual
standalone CLI/node, typed generic and capability fixtures, tenant-scoped
observations, adapter/RPC pairs, child PID resources and verified shutdown.
Its controlled queue handoffs distinguish tenant fairness from FIFO, and its
runtime budget cases cover positive fuel exhaustion and aged relative wall-time
ceilings. Cell identities and correlated guest logs/spans connect reuse and
tenant-isolation assertions to the actual composition.
Its versioned report distinguishes passed selected cases from unrun heavy gate
evidence. It does not establish a calibrated Phase 1 RSS plateau, zero-idle
scaling at 100,000 registrations or complete end-to-end gate coverage.

Current scheduler, activation lifecycle, wire, Wasmtime and standalone owner
suites additionally exercise their implemented fairness, route pinning, budget,
context and restart boundaries. The Phase 0 paragraphs below describe historical
evidence, not the limits of the current implementation.

## Phase 2 delivery and current authority

The completed [gate report](../phase-2-completion.md) maps all eighteen delivery
dependencies to their source suites and retained results. Its bounded operator
workflow covers real registry/CLI/node publication, rollout, promotion, rollback,
revocation and recovery. Separate offline and native schedules distinguish a
registry outage from current proof, policy and lifecycle permission. Neither
cached bytes nor a held prepared token can revive a revoked grant.

The [frozen resource profile](phase-2-resource-profile.md) measures 32 signed
releases and 16 deployments while warming only two portable runtime images. It
does not extend the historical 100,000-release measurements to Phase 2, native
compilation or future provider populations. The report preserves an earlier
unclassified `Unavailable` workflow attempt separately from the passing run;
finite success is not an availability SLO or arbitrary-duration leak guarantee.

## Dormant-service scaling — observed at all four Phase 1 scales

Register 100, 1,000, 10,000, and 100,000 dormant releases. Process count,
configured operating-system/runtime thread topology, socket count, and
execution-cell count must remain constant. Registry metadata, route indexes,
bounded caches, and disk storage may grow only within their documented models.

Phase 0 does not register those service counts. Its one-service result must not
be used to infer the 100,000 dormant-service invariant.

The [Phase 1 scale collector](phase-1-measurements.md) registers all four target
scales through the actual durable stores and samples the real standalone
composition. Its default 2/4-registration smoke run validates the collector;
it does not substitute for the
[retained full-profile observations](../../benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/REPORT.md#dormant-catalogs-at-four-scales).
At 100, 1,000, 10,000 and 100,000 releases/deployments, fixed node topology and
idle cell capacity remain constant, with no stores or prepared code created.
Catalog metadata RSS grows and is reported separately from execution resources.

## Reclamation — bounded evidence at recorded configurations

After repeated calls, resident memory must return near the fixed-runtime plus
bounded-cache baseline. File descriptors, handles, timers, provider leases,
and temporary blobs must remain bounded.

Phase 0 proves activation-owned cleanup for its finite local Wasmtime
composition and records a matched, fully documented native-Linux plateau for
the selected configuration. It does not prove arbitrary-duration leak freedom,
production SLOs, a capacity guarantee, or Phase 1 API behavior, and it does
not authorize Phase 1 by itself; the complete retained gate does. Provider
leases and state/effect resources require later-phase reclamation tests.

The [three retained Phase 1 soaks](../../benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/REPORT.md#three-mixed-workload-reclamation-runs)
each include 1,000 warmup and 100,000 measured mixed calls. They check current
stores, host state, cancellation, quotas, leases, journal and telemetry owners
at idle boundaries, and satisfy the declared RSS/descriptor-growth allowances.
The [completion report](../phase-1-completion.md) links timer/drop/helper ownership
tests and states the unenumerated general OS-timer limit. These finite results
do not extend to arbitrary-duration leak freedom or future providers.

## Isolation — scope-specific evidence

- one guest trap cannot corrupt another activation;
- one activation cannot access another handle table or memory;
- tenant state cannot cross namespaces;
- cell reuse cannot reveal prior input, output, or secret material;
- malformed payloads fail before unsafe host operations; and
- AOT artifacts with mismatched engine keys are rejected.

Phase 0 directly proves only the tested trap/timeout/cancellation/memory
containment and fresh-store/resource-reclamation behavior. It does not
establish multi-tenant namespace isolation, secret handling, production
capability isolation, or AOT-key rejection.

## Route pinning — implemented and validated

An in-flight activation finishes on its pinned release after a route switch.
New calls select only revisions in the new snapshot. The Phase 1 deployment and
activation lifecycle owner suites exercise immutable snapshot pinning and
publication. The bounded CLI profile holds an active call across a deployment
policy revision and verifies the old receipt and a new call's changed pin. The
standalone restart suite separately checks unchanged committed route identity.
The [Phase 1 completion report](../phase-1-completion.md) maps this evidence to
the collective gate decision.
Phase 0 has no production route table or snapshot path.

## Descendant budget hierarchy: implemented local profile

[Descendant admission](../runtime/descendant-budgets.md) conserves the parent's
remaining deadline, fuel, memory, fan-out, call and byte reservations. The
[local-call provider](../runtime/local-service-invocation.md) admits a separate
child activation under the exact compiled target and current authority. Unused
reservations return once; live children keep their charges through retirement.
Saturated parent-held cells cause prompt rejection, never hidden capacity or a
refund of the waiting parent's cell. Unsupported dimensions and strict-command
child compositions fail explicitly. Phase 0 has no descendant call graph; its
local deadline/fuel/memory/log tests are not evidence for this delivered profile.

## Failure ambiguity: independent control, command and provider outcomes

Phase 2 control tests cover response loss and uncertain durability around release,
deployment and rollout commits. Retained exact receipts support explicit lookup
and replay; unknown or evicted history does not establish that a mutation never
ran. The operator CLI never automatically resubmits an ambiguous operation. See
the [recovery contract](../phase-2-operator-workflows.md).

Immediate [provider acknowledgement/uncertainty](../runtime/capabilities.md) and
[deferred dispatch](../architecture/state-and-effects.md#immediate-calls-and-deferred-durable-intents)
have separate owners and conformance. The installed transaction runtime commits
its state/outbox/outcome envelope in the protected engine; the Phase 2 control
journal supplies no such application transaction. A lost reply, expired result
or unknown status is no abort proof and never authorizes automatic write replay.
Phase 0 has no durable state/effect path. The broader native/application recovery
campaign remains distinct from focused provider and engine tests.

## Adapter/RPC equivalence: selected pairs implemented

Cross-path equivalence is a requirement for every advertised execution mode.
Inline composition and node-to-node remote invocation remain unsupported; the
current direct-adapter/RPC comparison is not evidence for those modes. The
bounded Phase 1 profile compares eight outcome pairs and
three capability pairs through the direct adapter and real RPC, including live
budgets, per-call context/clock invariants and correlated telemetry. This is
selected evidence for the Phase 1 standalone boundary; other execution-host
backends and later-phase state semantics require their own coverage. Phase 0
exercises only the local Wasmtime path.
