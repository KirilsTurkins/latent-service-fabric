# ADR-0011: Keep the control plane out of the invocation hot path

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Control-plane latency or outage must not block calls using known valid routes.

## Decision

Compile and distribute immutable route snapshots; nodes resolve locally.

## Consequences

Nodes can temporarily operate on their last valid snapshot but cannot apply new desired state without the control plane.
