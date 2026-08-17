# ADR-0009: Use capability-based host access

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Direct sockets, filesystem, environment, threads, and secrets would break isolation and resource pooling.

## Decision

Capsules access external resources only through explicit WIT imports granted by policy and bound per activation.

## Consequences

Capability providers become part of the trusted computing base and require strict auditing and quotas.
