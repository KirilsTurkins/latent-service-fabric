# Frequently Asked Questions

> **Document role:** Concise explanation. Canonical repository documents take precedence.

## Is LSF another ordinary microservice framework?

No. Its defining model is that deployed services remain immutable dormant artifacts until a request becomes a bounded activation. Service count must not determine process, thread, socket, or execution-cell count.

## Does every service receive a process?

No. Normal capsule execution uses a fixed node-owned pool of reusable cells. Stronger containment may use a fixed number of trust-sharded execution hosts. Native compatibility may use an ephemeral fallback, but not as the default idle model.

## Is a cell a warm service instance?

No. A cell is generic while idle. It receives an exact activation identity, guest store, memory, handles, and budgets only for leased work, then must be reset before reuse.

## Why WebAssembly components?

The Component Model and WIT provide typed, language-neutral boundaries for portable capsule exports, imports, resources, asynchronous operations, and host capabilities. Wasmtime is the first engine, behind an abstraction.

## Can capsules be written in multiple languages?

The architecture is language-neutral at the component boundary. The repository already defines interface-only surfaces for Rust, Go, Java, .NET, TypeScript, and C, but final guest toolchains and runtime support remain implementation work.

## Why use both WIT and Protobuf?

WIT is authoritative for capsule and component contracts. Protobuf defines management, control-plane, node, trigger, route, audit, and generic invocation APIs. They solve different boundary problems.

## Where does state live?

Durable state lives behind explicit state capabilities and transactions, not in assumed persistent guest memory. Stateless, keyed transactional, entity, and explicit durable-workflow models are planned.

## Does LSF guarantee exactly-once external effects?

Not universally. It guarantees the semantics explicitly provided by the selected state/effect backend and durable intent model. Arbitrary external systems still require idempotency, status inspection, and sometimes compensation.

## What happens when a capsule traps?

The trap should terminate only that activation. Handles are revoked, staged uncommitted state is discarded, resources are reclaimed, and the generic cell is reset before reuse.

## What happens when the caller times out?

A timeout does not prove the activation failed before commit or effect dispatch. Side-effecting clients need stable idempotency identities and activation or commit-status inspection.

## Does the control plane handle every call?

No. It compiles and distributes immutable route snapshots. Nodes resolve ordinary invocations locally. A temporary control-plane outage should not stop already-known valid routes.

## Can two service versions run at the same time?

Yes. Multiple implementation and contract versions may coexist. Routes select eligible revisions, and each activation remains pinned to its selected release and policy generation.

## Is there a working production runtime now?

No. The current repository is an executable interface and validation scaffold. The first runtime vertical slice remains Phase 0 work.

## What proves the zero-idle-resource claim?

Tests and benchmarks that register increasing numbers of dormant releases while measuring processes, OS threads, sockets, cells, memory, handles, timers, and caches. Interface design alone is not proof.

## When is an ADR required?

When a change alters a core invariant, dependency direction, execution model, compatibility promise, contract authority, state/effect guarantee, trust boundary, or promotion of research into the core.

## Are paging and call fusion required?

No. They are optional research tracks unless an accepted ADR promotes them. The core model must work without them.

## Why is LSF described as a working name?

ADR 0018 explicitly treats “Latent Service Fabric” as a working name. The architecture and contracts should not depend on branding permanence.

## Where should I start?

Use [[Getting-Started|Getting started]], [[Core-Concepts|Core concepts]], and [[Architecture]].
