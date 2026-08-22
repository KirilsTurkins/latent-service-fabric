# Core Concepts

> **Document role:** Conceptual vocabulary. Formal definitions and constraints remain in the repository architecture, schemas, and ADRs.

## The resource model

LSF separates **registered service identity** from **allocated execution resources**.

```text
resident resources = fixed node runtime + active activations + bounded shared caches
```

A deployed but inactive service owns no process, operating-system thread, listener, heap, runtime instance, database pool, HTTP client pool, timer loop, or telemetry exporter. Metadata and immutable artifacts may remain stored; active execution resources do not.

## Service model

```text
Service = stable logical name
Release = immutable capsule digest
Revision = release + deployment configuration
Route = rule selecting a revision
Activation = revision × function × input × identity × budget × deadline
Result = output + state commit + effect intents + accounting
```

### Service

A stable logical identity used by routing, policy, and management. It is not a PID, port, container, or resident object graph.

### Capsule

The immutable deployable unit containing a WebAssembly Component Model binary, WIT contract information, a capsule manifest, package metadata, supply-chain evidence, and trust material.

### Release

One immutable capsule identified by content digest. Reusing a semantic version does not change the digest identity; changing any covered artifact creates a different release.

### Deployment and revision

A deployment points to a release and adds mutable policy: capability grants, resource ceilings, placement, availability objectives, and route weight. A compiled deployment generation produces a revision.

### Route and route snapshot

A route maps a logical service or trigger to eligible revisions. The control plane compiles routes, bindings, and policy digests into an immutable snapshot. Nodes atomically replace snapshots; an activation pins the generation it selected.

### Activation

A bounded temporary execution of one function for one exact revision, caller identity, budget, and deadline. It may run, wait asynchronously, commit, fail, or suspend durably. It does not become a permanent service instance.

### Execution cell

A reusable sandbox allocation slot from a node-defined fixed pool. An idle cell has no service identity. During an activation it contains an isolated guest store, memory, handles, budgets, buffers, cancellation state, and accounting.

### Capability

An explicit, policy-scoped way for guest code to access the outside world. A capability is usable only when all three conditions hold:

```text
capsule import request
AND deployment grant
AND invocation-principal authorization
```

Handles are activation-scoped, quota-bound, expiring, auditable, and invalid after completion.

### Binding

A resolution from a consumer's imported WIT contract to a host capability or provider. Permitted physical modes are host, inline, isolated local, remote, or automatic selection within policy.

### State transaction

An activation-scoped transaction for keyed state. Reads establish observed versions; writes and deletes are staged. Commit validates the read set and applies mutations according to the selected backend semantics.

### Effect intent

A durable record describing an external operation, including a deterministic identity and idempotency key. Durable intent is distinct from proof that an arbitrary external system applied the effect exactly once.

### Durable workflow

An explicit state machine whose continuation can be persisted. Durable suspension releases the complete execution cell and guest store. LSF does not rely on arbitrary native stack checkpointing.

### Blob

A large immutable or staged value addressed through a capability rather than repeatedly copied through invocation envelopes. Blob storage can scale independently from execution-cell allocation.

## Three planes

- **Developer plane:** builds contracts and components, creates supply-chain evidence, signs artifacts, and publishes OCI artifacts.
- **Control plane:** stores desired state, validates releases, compiles bindings and routes, evaluates policy, tracks nodes, and distributes immutable snapshots.
- **Data plane:** receives calls and triggers, resolves, admits, schedules, materializes, binds capabilities, executes, commits, records effects, and returns results.

## What LSF is not

- one operating-system process per deployed service;
- a library that links all services into one trusted address space;
- a claim that remote or isolated calls are infallible;
- a universal exactly-once wrapper around arbitrary external systems;
- a requirement that service-local memory survive between calls;
- a requirement that the control plane participate in every invocation.

Continue with [[Architecture]], [[Execution-Cells|Execution cells]], and [[Glossary]].
