# ADR-0017: Use fixed trust-class execution hosts for stronger containment

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

A single process minimizes overhead but increases the blast radius of runtime or provider defects.

## Decision

Allow a fixed node-defined set of execution-host processes partitioned by trust or workload class.

## Consequences

Process count remains independent of service count while operators can trade isolation for overhead.
