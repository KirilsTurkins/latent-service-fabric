# ADR-0009: Use capability-based host access

- **Status:** Accepted
- **Date:** 2026-08-17

## Current implementation

Activation context, clocks, budget access and structured logging are installed
built-ins. The sealed capability broker also supports bounded external providers
under activation-scoped grants. The standalone node configures HTTP and local
blobs; other maintained adapters require Rust embedding. Recognition of a WIT
import alone installs no provider and grants no access. See the
[capability model](../docs/architecture/identity-and-capabilities.md).

## Context

Direct sockets, filesystem, environment, threads, and secrets would break isolation and resource pooling.

## Decision

Capsules access external resources only through explicit WIT imports granted by policy and bound per activation.

## Consequences

Capability providers become part of the trusted computing base and require strict auditing and quotas.
