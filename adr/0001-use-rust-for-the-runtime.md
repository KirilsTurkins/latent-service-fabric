# ADR-0001: Use Rust for the runtime

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

The node and control-plane core require predictable memory ownership, strong concurrency primitives, portable systems access, and a small trusted computing base.

## Decision

Implement the first runtime, control-plane modules, CLI, and architectural traits in Rust. Guest and client languages remain polyglot.

## Consequences

Rust expertise is required. Language interoperability is handled at WIT and Protobuf boundaries rather than through a shared application runtime.
