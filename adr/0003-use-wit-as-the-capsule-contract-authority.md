# ADR-0003: Use WIT as the capsule contract authority

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Language-specific interfaces cannot be the source of truth for polyglot components.

## Decision

All guest-visible exports, imports, types, resources, futures, and streams are defined in versioned WIT packages.

## Consequences

SDK surfaces are projections and must track WIT compatibility.
