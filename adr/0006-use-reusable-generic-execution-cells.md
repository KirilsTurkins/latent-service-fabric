# ADR-0006: Use reusable generic execution cells

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Activation resources should scale with active work, not registered services.

## Decision

Nodes maintain fixed cell classes leased to activations and reset after use.

## Consequences

Cell reset and cross-activation isolation become critical conformance requirements.
