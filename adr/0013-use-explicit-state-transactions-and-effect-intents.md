# ADR-0013: Use explicit state transactions and effect intents

- **Status:** Accepted
- **Date:** 2026-08-17

## Current implementation

Application transactions and durable effect dispatch remain planned. Durable
publication/deployment metadata is not application state. Immediate capability
operations are implemented under
[ADR-0025](0025-separate-immediate-capability-operations-from-transactional-effect-intents.md),
which supersedes this ADR's blanket requirement to journal every external effect.

## Context

Implicit process memory and immediate external writes are unsafe under eviction, retry, and node failure.

## Decision

Represent durable state through explicit transactions and external effects through journaled intents.

## Consequences

Component authors must design state and side effects for retries and conflicts.
