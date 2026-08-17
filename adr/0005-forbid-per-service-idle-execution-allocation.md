# ADR-0005: Forbid per-service idle execution allocation

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Per-service processes, listeners, heaps, threads, and pools recreate the idle cost LSF exists to remove.

## Decision

A dormant service may consume artifact and metadata storage but owns no live execution resource.

## Consequences

Background behavior must be represented by triggers, events, timers, or durable continuations.
