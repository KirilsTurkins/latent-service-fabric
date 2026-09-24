# ADR-0011: Keep the control plane out of the invocation hot path

- **Status:** Accepted
- **Date:** 2026-08-17
- **Follow-up:** [ADR-0030](0030-bound-disconnected-authorization-validity.md) defines the finite authorization and disconnected-validity contract; local resolution remains unchanged.

## Current implementation

The standalone node builds and resolves immutable snapshots locally and applies
local management mutations without a separate control plane. Cluster distribution
and disconnected authorization are planned; the
[cluster freshness handoff](../docs/architecture/cluster-freshness-handoff.md)
defines the required distributed qualification.

## Context

Control-plane latency or outage must not block calls using known valid routes.

## Decision

Compile and distribute immutable route snapshots; nodes resolve locally.

## Consequences

In the planned clustered model, nodes may operate on their last snapshot only
within its authorization-validity bounds. Applying new desired state requires
the control plane. The current standalone node owns its local mutations.
