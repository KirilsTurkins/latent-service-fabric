# Contributing

LSF is currently interface-first. Contributions should preserve the distinction between architectural contracts and implementations.

## Change categories

- **ADR:** a decision that changes a core invariant, dependency direction, execution model, or compatibility promise.
- **RFC:** a proposal requiring review before contracts are changed.
- **Interface change:** a compatible or incompatible update to WIT, Protobuf, JSON Schema, Rust traits, or an SDK surface.
- **Implementation change:** future code behind an accepted interface.

## Interface rules

1. WIT is authoritative for guest-visible component contracts.
2. Protobuf is authoritative for control-plane and generic management RPCs.
3. JSON Schema is authoritative for declarative resources.
4. Rust crates must keep the dependency graph acyclic.
5. Platform errors and domain errors must remain separate.
6. No API may imply that a remote or isolated invocation is infallible.
7. No service API may require a persistent service-owned process, listener, thread, or pool.
8. New external effects require explicit idempotency and retry semantics.
9. Experimental paging, fusion, and native isolation work stays under `research/` until promoted by ADR.

## Pull requests

A pull request should include:

- the affected contract surfaces,
- compatibility impact,
- security and resource-accounting impact,
- relevant ADR or RFC,
- conformance tests or a test specification,
- generated artifacts only when generation is reproducible.
