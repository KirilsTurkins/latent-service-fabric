# ADR-0012: Place remote invocation behind a WIT-native transport abstraction

- **Status:** Accepted
- **Date:** 2026-08-17

## Implementation status at Phase 1 completion

Phase 1 exposes generated generic invocation RPCs on the authenticated standalone loopback listener. Cross-node routing, cluster identity, and the service-to-service remote transport remain later-phase work.

## Context

Local and remote bindings need equivalent typed semantics without freezing the runtime to one network library.

## Decision

Define `RemoteInvocationClient`, `RemoteInvocationServer`, and wire seams suitable for wRPC-like transports.

## Consequences

Transport implementation and broker topology remain open while identity, deadline, budget, and revision pinning are mandatory.
