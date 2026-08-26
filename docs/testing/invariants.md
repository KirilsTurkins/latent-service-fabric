# Test invariants

This document separates invariants already exercised by the completed Phase 0 feasibility gate from target invariants that remain Phase 1 or later work. The machine-readable Phase 0 evidence is [`../../benchmarks/phase0/raw-results.json`](../../benchmarks/phase0/raw-results.json); interpretation and limitations are in [`../phase-0-completion.md`](../phase-0-completion.md).

## Phase 0 proven subset

The finite local Phase 0 reference run and executable E2E suite prove, for the recorded Linux environment/configuration:

- a fixed two-cell generic pool never exceeds configured active capacity and its four-waiter queue rejects overflow deterministically;
- success, domain error, trap, timeout, explicit cancellation, memory-pressure/resource exhaustion, and bounded queue rejection return to a reusable/idle pool state or fail before lease acquisition;
- every tested failure cause is followed by a successful echo without poisoning the retained composition;
- no measured terminal path retains an active lease, queued waiter, cancellation registration, invocation, Wasmtime store, host state, component instance, temporary buffer, cancellation probe, retained log, or quarantine;
- prepared-component cache growth remains within its configured bound and explicit release clears the cache;
- configured runtime workers remain fixed, process count remains one, listeners/open sockets remain zero, and cell capacity remains fixed across component loading and repeated invocations;
- the Linux process probe observes bounded RSS/file-descriptor behavior for the finite sample window and shutdown returns runtime workers/live backend resources to zero.

The Wasmtime epoch-interruption mechanism adds one bounded helper OS thread after preparation in the reference run. The invariant is therefore fixed **configured/node runtime topology**, not byte-for-byte constancy of raw OS thread count during engine operation.

## Dormant-service scaling — not yet proven

Register 100, 1,000, 10,000, and 100,000 dormant releases. Process count, configured operating-system/runtime thread topology, socket count, and execution-cell count must remain constant. Registry metadata, route indexes, bounded caches, and disk storage may grow only within their documented models.

Phase 0 did not register those service counts. Its result shows component loading/invocation does not introduce a per-service process, listener/socket, worker pool, or cell in the measured one-service spike. The 100,000 dormant-service invariant remains a future scale test and must not be inferred from Phase 0.

## Reclamation

After repeated calls, resident memory must return near the fixed-runtime plus bounded-cache baseline. File descriptors, handles, timers, provider leases, and temporary blobs must remain bounded.

Phase 0 proves the activation-owned subset for its local Wasmtime composition and finite sample window. Long-duration allocator behavior, provider leases, state/effect resources, production telemetry, and other Phase 1 subsystems require new reclamation tests as those systems are implemented.

## Isolation

Target invariants:

- one guest trap cannot corrupt another activation,
- one activation cannot access another handle table or memory,
- tenant state cannot cross namespaces,
- cell reuse cannot reveal prior input, output, or secret material,
- malformed payloads fail before unsafe host operations,
- AOT artifacts with mismatched engine keys are rejected.

Phase 0 directly proves only the tested trap/timeout/cancellation/memory-pressure containment and fresh-store/resource-reclamation behavior. It does not establish multi-tenant namespace isolation, secret handling, production capability isolation, or AOT-key rejection.

## Route pinning — future

An in-flight activation finishes on its pinned release after a route switch. New calls select only revisions in the new snapshot. Phase 0 has no production route table/snapshot path.

## Budget hierarchy — future

A child call cannot exceed the parent’s remaining deadline, CPU, fan-out, outbound-call, state, blob, log, or effect budget. Phase 0 exercises local deadline/fuel/memory/log limits only; it has no descendant call graph.

## Failure ambiguity — future

Tests must cover response loss after state commit or provider dispatch. Automatic retries are permitted only when the operation contract and idempotency model allow them. Phase 0 has no durable state/effect commit path.

## Local/remote equivalence — future

Domain output, platform errors, identity, deadlines, budgets, tracing, state semantics, and accounting must match whether a binding is inline, isolated local, or remote. Phase 0 exercises only the local Wasmtime path.
