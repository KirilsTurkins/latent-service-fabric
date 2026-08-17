# ADR-0013: Use explicit state transactions and effect intents

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Implicit process memory and immediate external writes are unsafe under eviction, retry, and node failure.

## Decision

Represent durable state through explicit transactions and external effects through journaled intents.

## Consequences

Component authors must design state and side effects for retries and conflicts.
