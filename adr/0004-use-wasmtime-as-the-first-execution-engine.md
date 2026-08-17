# ADR-0004: Use Wasmtime as the first execution engine

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

The first backend needs Component Model support, AOT preparation, bounded execution, async support, pooling, and copy-on-write opportunities.

## Decision

Implement the initial `ExecutionBackend` with Wasmtime behind an engine-neutral trait.

## Consequences

Engine-specific artifacts include the exact engine configuration in their key and are not portable across incompatible profiles.
