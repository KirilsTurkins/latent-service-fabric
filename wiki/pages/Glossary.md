# Glossary

> **Document role:** Quick reference. Where a definition affects protocol or compatibility, the canonical contract or architecture document wins.

## Activation

A bounded temporary execution of one exact revision, function, input, identity, budget, and deadline.

## Admission

Pre-allocation evaluation of identity, policy, quota, payload, deadline feasibility, trust-class capacity, cell class, and overload.

## AOT artifact

A derived ahead-of-time compiled cache artifact. It is not a release and is valid only for its complete engine, target, configuration, policy, and CPU-feature key.

## Binding

A mapping from an imported WIT contract to a host capability or provider, with permitted physical execution modes.

## Blob

A large immutable or staged binary value accessed through a capability rather than repeatedly copied through invocation envelopes.

## Budget

A bounded allowance for CPU, wall time, memory, stack, host calls, payloads, fan-out, state, blobs, logs, effects, or descendant work.

## Capability

An explicit, policy-scoped external operation available only through the intersection of capsule request, deployment grant, and principal authorization.

## Capsule

An immutable deployable component plus manifest, contract graph, package metadata, and supply-chain evidence.

## Cell

A reusable generic sandbox allocation slot. It has no service identity while idle.

## Commit receipt

Durable evidence of the commit level reached for an activation, used to resolve lost-response ambiguity.

## Control plane

The desired-state, catalog, policy, binding, routing, inventory, and audit plane. It does not execute capsule code and is not on the ordinary invocation hot path.

## Data plane

The node path that receives, resolves, admits, schedules, materializes, binds, executes, commits, records effects, and returns invocation results.

## Deployment

Mutable grants, limits, placement, availability targets, and route weight applied to an immutable release.

## Domain error

A service-specific error declared by the WIT contract.

## Durable workflow

An explicit state machine that can persist a continuation and release its complete execution cell during suspension.

## Effect intent

A durable description of an external operation with a deterministic identity, provider operation, payload, idempotency key, deadline, and audit context.

## Entity lane

Ephemeral ownership for serialized or affinity-sensitive work on one entity key. It disappears when no queued or active work remains.

## Execution host

A fixed node-owned process that may contain execution cells, optionally partitioned by trust class.

## Platform error

A stable fabric-level failure code separate from domain errors.

## Provider

A host or service implementation that satisfies a capability or imported contract.

## Release

An immutable capsule identity addressed by content digest.

## Revision

A release combined with one compiled deployment-policy generation.

## Route

A rule selecting eligible revisions for a logical service or trigger.

## Route snapshot

An immutable, content-digested, monotonically generated set of resolved routes, revisions, bindings, and policy references distributed to nodes.

## Service

A stable logical name. It is not a process, port, listener, heap, or resident instance.

## State transaction

An activation-scoped read and staged-write set committed with the selected consistency and conflict semantics.

## WIT

WebAssembly Interface Types, the authoritative language for capsule-visible imports, exports, functions, resources, futures, and streams.

## Further reading

- [[Core-Concepts|Core concepts]]
- [[Contracts-and-APIs|Contracts and APIs]]
- [[Activation-Lifecycle|Activation lifecycle]]
