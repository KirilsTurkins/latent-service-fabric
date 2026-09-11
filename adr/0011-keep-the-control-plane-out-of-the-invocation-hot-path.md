# ADR-0011: Keep the control plane out of the invocation hot path

- **Status:** Accepted
- **Date:** 2026-08-17

## Implementation status at Phase 1 completion

Phase 1 builds and resolves immutable snapshots locally and applies local management mutations without a separate control plane. Cluster distribution and control-plane outage behavior remain Phase 5 work.

## Context

Control-plane latency or outage must not block calls using known valid routes.

## Decision

Compile and distribute immutable route snapshots; nodes resolve locally.

## Consequences

Nodes can temporarily operate on their last valid snapshot but cannot apply new desired state without the control plane.
