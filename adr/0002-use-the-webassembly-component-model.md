# ADR-0002: Use the WebAssembly Component Model

- **Status:** Accepted
- **Date:** 2026-08-17

## Current implementation

LSF executes supported Component Model guests with Wasmtime. An isolated
native-binary fallback remains architectural direction; it is not an installed
backend. See the [execution profiles](../docs/runtime/execution-security-profiles.md).

## Context

LSF needs portable polyglot binaries with typed imports/exports and stronger in-process isolation than arbitrary native libraries.

## Decision

Use Component Model binaries as the default capsule execution format.

## Consequences

Guest languages require compatible component toolchains. Arbitrary native
binaries are unsupported until an isolated fallback backend is separately
implemented and qualified.
