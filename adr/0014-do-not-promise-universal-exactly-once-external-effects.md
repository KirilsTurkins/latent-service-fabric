# ADR-0014: Do not promise universal exactly-once external effects

- **Status:** Accepted
- **Date:** 2026-08-17

## Current implementation

The current immediate capability APIs report uncertainty when an external effect
may have occurred. They provide no durable intent dispatcher or automatic retry.
The durable-intent decision below constrains the planned transactional model;
see [ADR-0025](0025-separate-immediate-capability-operations-from-transactional-effect-intents.md).

## Context

A remote provider may complete an operation while its response is lost.

## Decision

Promise durable intent and stable idempotency identity; rely on provider deduplication where available.

## Consequences

Clients and workflows must handle uncertain outcomes explicitly.
