# ADR-0016: Keep paging, continuation eviction, and fusion optional

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

These techniques may improve efficiency but carry high semantic and implementation risk.

## Decision

Develop them under research interfaces and promote them only through later ADRs and conformance evidence.

## Consequences

The production core remains useful without experimental optimizations.
