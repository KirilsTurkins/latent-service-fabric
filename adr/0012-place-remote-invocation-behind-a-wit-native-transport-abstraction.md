# ADR-0012: Place remote invocation behind a WIT-native transport abstraction

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Local and remote bindings need equivalent typed semantics without freezing the runtime to one network library.

## Decision

Define `RemoteInvocationClient`, `RemoteInvocationServer`, and wire seams suitable for wRPC-like transports.

## Consequences

Transport implementation and broker topology remain open while identity, deadline, budget, and revision pinning are mandatory.
