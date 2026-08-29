<!-- LSF-WIKI-MANAGED -->
# State and effects

State and external effects are documented target capabilities; they are not
implemented by the Phase 0 spike.

## Intended model

The target architecture separates:

- transactional keyed state with explicit conflict semantics;
- durable effect intents recorded with state changes;
- asynchronous effect dispatch and idempotency handling; and
- entity-key routing and workflow continuation where required.

This separation prevents a transient invocation result from being mistaken for
proof that a state mutation and an external effect have both happened exactly
once. Response loss, commit ambiguity, and provider failure need explicit
contract-level semantics.

## Phase 0 boundary

The echo spike has no state backend, durable outbox, provider dispatch,
idempotency key, effect retry loop, or workflow continuation. Its cleanup
proof concerns invocation-owned Wasmtime and pool resources, not transaction
or provider resources.

Future state/effect work must add its own validation for isolation,
reclamation, ambiguity handling, and recovery. It cannot inherit those claims
from a local echo result.

## Canonical sources

- [State and effects architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/architecture/state-and-effects.md)
- [Commit protocol](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/protocol/commit-protocol.md)
- [Phase 4 roadmap](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/roadmap.md)
