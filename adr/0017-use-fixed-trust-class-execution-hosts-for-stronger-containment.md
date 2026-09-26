# ADR-0017: Use fixed trust-class execution hosts for stronger containment

- **Status:** Accepted
- **Date:** 2026-08-17
- **Clarified by:** [ADR-0026](0026-require-explicit-execution-isolation-profiles.md)

## Implementation status at Phase 1 completion

Phase 1 uses fixed logical trust-class cells inside one standalone node process. Separate execution-host processes remain a future backend option.

## Context

A single process minimizes overhead but increases the blast radius of runtime or provider defects.

## Decision

Allow a fixed node-defined set of execution-host processes partitioned by trust or workload class.

ADR-0026 defines which threat classes require that stronger boundary, the current delivered profiles, fail-closed profile selection, and the evidence required before an external execution-host profile can be called supported.

## Consequences

Process count remains independent of service count while operators can trade isolation for overhead.
