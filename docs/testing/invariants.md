# Test invariants

This document separates the Phase 0 invariants exercised by the executable
spike from target invariants that remain Phase 1 or later work. The retained
clean-checkout [completion receipt](../../benchmarks/phase0/receipts/native-linux-2026-08-30-b932a935/gate-summary.json)
authorizes Phase 1 for the current canonical execution identity. It does not
claim production readiness or Phase 1 API compatibility. See
[`../phase-0-completion.md`](../phase-0-completion.md).

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

## Dormant-service scaling — not yet proven

Register 100, 1,000, 10,000, and 100,000 dormant releases. Process count,
configured operating-system/runtime thread topology, socket count, and
execution-cell count must remain constant. Registry metadata, route indexes,
bounded caches, and disk storage may grow only within their documented models.

Phase 0 does not register those service counts. Its one-service result must not
be used to infer the 100,000 dormant-service invariant.

The [Phase 1 scale collector](phase-1-measurements.md) registers all four target
scales through the actual durable stores and samples the real standalone
composition. Its default 2/4-registration smoke run validates the collector;
full-scale acceptance requires retained full-profile results.

## Reclamation — partially proven

After repeated calls, resident memory must return near the fixed-runtime plus
bounded-cache baseline. File descriptors, handles, timers, provider leases,
and temporary blobs must remain bounded.

Phase 0 proves activation-owned cleanup for its finite local Wasmtime
composition and records a matched, fully documented native-Linux plateau for
the selected configuration. It does not prove arbitrary-duration leak freedom,
production SLOs, a capacity guarantee, or Phase 1 API behavior, and it does
not authorize Phase 1 by itself; the complete retained gate does. Provider
leases, state/effect resources,
production telemetry, and new Phase 1 subsystems require their own reclamation
tests.

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

## Route pinning — implemented, full gate pending

An in-flight activation finishes on its pinned release after a route switch.
New calls select only revisions in the new snapshot. The Phase 1 deployment and
activation lifecycle owner suites exercise immutable snapshot pinning and
publication. The bounded CLI profile holds an active call across a deployment
policy revision and verifies the old receipt and a new call's changed pin. The
standalone restart suite separately checks unchanged committed route identity.
Phase 0 has no production route table or snapshot path.

## Budget hierarchy — future

A child call cannot exceed the parent’s remaining deadline, CPU, fan-out,
outbound-call, state, blob, log, or effect budget. Phase 0 exercises local
deadline/fuel/memory/log limits only; it has no descendant call graph.

## Failure ambiguity — future

Tests must cover response loss after state commit or provider dispatch.
Automatic retries are permitted only when the operation contract and idempotency
model allow them. Phase 0 has no durable state/effect commit path.

## Local/remote equivalence — selected pairs implemented

Domain output, platform errors, identity, deadlines, budgets, tracing, state
semantics, and accounting must match whether a binding is inline, isolated
local, or remote. The bounded Phase 1 profile compares eight outcome pairs and
three capability pairs through the direct adapter and real RPC, including live
budgets, per-call context/clock invariants and correlated telemetry. This is
selected evidence for the Phase 1 standalone boundary; other execution-host
backends and later-phase state semantics require their own coverage. Phase 0
exercises only the local Wasmtime path.
