# ADR-0008: Compile AOT artifacts only in a trusted boundary

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Precompiled native code can bypass assumptions made by validation of portable component bytes.

## Decision

Nodes compile verified components locally or trust only isolated compiler output keyed to engine and CPU configuration.

## Consequences

Cold preparation has a cost; shared bounded AOT caches mitigate it.
