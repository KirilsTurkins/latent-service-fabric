# ADR-0014: Do not promise universal exactly-once external effects

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

A remote provider may complete an operation while its response is lost.

## Decision

Promise durable intent and stable idempotency identity; rely on provider deduplication where available.

## Consequences

Clients and workflows must handle uncertain outcomes explicitly.
