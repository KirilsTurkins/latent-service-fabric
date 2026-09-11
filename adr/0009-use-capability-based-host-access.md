# ADR-0009: Use capability-based host access

- **Status:** Accepted
- **Date:** 2026-08-17

## Implementation status at Phase 1 completion

Phase 1 implements activation context, clocks, budget access, and structured logging. General external capability providers and grants remain Phase 3 work.

## Context

Direct sockets, filesystem, environment, threads, and secrets would break isolation and resource pooling.

## Decision

Capsules access external resources only through explicit WIT imports granted by policy and bound per activation.

## Consequences

Capability providers become part of the trusted computing base and require strict auditing and quotas.
