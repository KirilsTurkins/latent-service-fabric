# ADR-0008: Compile AOT artifacts only in a trusted boundary

- **Status:** Accepted
- **Date:** 2026-08-17

## Implementation status at Phase 1 completion

Phase 1 compiles verified portable components locally and retains bounded in-memory prepared entries. A trusted distributed/persistent AOT cache remains Phase 2 work.

## Context

Precompiled native code can bypass assumptions made by validation of portable component bytes.

## Decision

Nodes compile verified components locally or trust only isolated compiler output keyed to engine and CPU configuration.

## Consequences

Cold preparation has a cost; shared bounded AOT caches mitigate it.
