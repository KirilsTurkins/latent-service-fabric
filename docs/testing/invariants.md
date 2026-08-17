# Test invariants

## Dormant-service scaling

Register 100, 1,000, 10,000, and 100,000 dormant releases. Process count, operating-system thread count, socket count, and execution-cell count must remain constant. Registry metadata, route indexes, and disk storage may grow.

## Reclamation

After repeated calls, resident memory must return near the fixed-runtime plus bounded-cache baseline. File descriptors, handles, timers, provider leases, and temporary blobs must remain bounded.

## Isolation

- one guest trap cannot corrupt another activation,
- one activation cannot access another handle table or memory,
- tenant state cannot cross namespaces,
- cell reuse cannot reveal prior input, output, or secret material,
- malformed payloads fail before unsafe host operations,
- AOT artifacts with mismatched engine keys are rejected.

## Route pinning

An in-flight activation finishes on its pinned release after a route switch. New calls select only revisions in the new snapshot.

## Budget hierarchy

A child call cannot exceed the parent’s remaining deadline, CPU, fan-out, outbound-call, state, blob, log, or effect budget.

## Failure ambiguity

Tests must cover response loss after state commit or provider dispatch. Automatic retries are permitted only when the operation contract and idempotency model allow them.

## Local/remote equivalence

Domain output, platform errors, identity, deadlines, budgets, tracing, state semantics, and accounting must match whether a binding is inline, isolated local, or remote.
