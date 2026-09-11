# ADR-0017: Use fixed trust-class execution hosts for stronger containment

- **Status:** Accepted
- **Date:** 2026-08-17

## Implementation status at Phase 1 completion

Phase 1 uses fixed logical trust-class cells inside one standalone node process. Separate execution-host processes remain a future backend option.

## Context

A single process minimizes overhead but increases the blast radius of runtime or provider defects.

## Decision

Allow a fixed node-defined set of execution-host processes partitioned by trust or workload class.

## Consequences

Process count remains independent of service count while operators can trade isolation for overhead.
