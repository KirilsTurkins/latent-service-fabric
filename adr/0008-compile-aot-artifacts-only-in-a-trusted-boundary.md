# ADR-0008: Compile AOT artifacts only in a trusted boundary

- **Status:** Accepted
- **Date:** 2026-08-17

## Implementation status at Phase 1 completion

Phase 1 compiles verified portable components locally and retains bounded in-memory prepared entries. A trusted distributed/persistent AOT cache remains Phase 2 work.

## Phase 2 isolated producer

Issue #150 adds a bounded Linux x86_64 compiler process that enters a filesystem and syscall sandbox before reading portable component bytes. Its private completion path authenticates the exact native output with a node-local key and binds the compiler, engine, source, and sandbox identities. The persistent native cache and loader remain issue #151 work; current execution does not consume this output automatically. See [trusted AOT production](../docs/runtime/trusted-aot.md) for the API, enforced limits, and ownership boundaries.

## Context

Precompiled native code can bypass assumptions made by validation of portable component bytes.

## Decision

Nodes compile verified components locally or trust only isolated compiler output keyed to engine and CPU configuration.

## Consequences

Cold preparation has a cost; shared bounded AOT caches mitigate it.
