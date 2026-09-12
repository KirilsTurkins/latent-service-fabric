# ADR-0008: Compile AOT artifacts only in a trusted boundary

- **Status:** Accepted
- **Date:** 2026-08-17

## Implementation status at Phase 1 completion

Phase 1 compiles verified portable components locally and retains bounded in-memory prepared entries. A trusted distributed/persistent AOT cache remains Phase 2 work.

## Phase 2 isolated producer and authenticated native reuse

Issue #150 adds a bounded Linux x86_64 compiler process that enters a filesystem and syscall sandbox before reading portable component bytes. Its private completion path authenticates the exact native output with a node-local key and binds the compiler, engine, source, and sandbox identities.

Issue #151 integrates optional persistent reuse with the catalog-bound runtime. A fresh verified source fetch and exact current compatibility key precede receipt authentication; the receipt MAC is checked before reading its claimed blob. Only a private proof over authenticated immutable bytes reaches the one audited copying native loader. Native mappings receive a page-rounded allowance before loading and keep it through runtime pins, eviction and cleanup. Cache storage never grants lifecycle or publisher authority, and configured isolated mode has no in-process compilation fallback. See [trusted AOT production and reuse](../docs/runtime/trusted-aot.md) for the API, limits, optional persistence failures and memory-accounting exclusions.

## Context

Precompiled native code can bypass assumptions made by validation of portable component bytes.

## Decision

Nodes compile verified components locally or trust only isolated compiler output keyed to engine and CPU configuration.

## Consequences

Cold preparation has a cost; shared bounded AOT caches mitigate it.
