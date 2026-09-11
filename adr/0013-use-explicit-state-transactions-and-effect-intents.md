# ADR-0013: Use explicit state transactions and effect intents

- **Status:** Accepted
- **Date:** 2026-08-17

## Implementation status at Phase 1 completion

Transactions and durable effect execution are Phase 4 work. Phase 1 is stateless; its durable release/deployment metadata is not application state.

## Context

Implicit process memory and immediate external writes are unsafe under eviction, retry, and node failure.

## Decision

Represent durable state through explicit transactions and external effects through journaled intents.

## Consequences

Component authors must design state and side effects for retries and conflicts.
