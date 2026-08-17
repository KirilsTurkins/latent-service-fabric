# ADR-0002: Use the WebAssembly Component Model

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

LSF needs portable polyglot binaries with typed imports/exports and stronger in-process isolation than arbitrary native libraries.

## Decision

Use Component Model binaries as the default capsule execution format.

## Consequences

Guest languages require compatible toolchains. Arbitrary native binaries use an isolated fallback backend.
