# ADR-0015: Build a single-node stateless fabric before clustering

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Clustering, state, and workflows can hide failure to prove the core dormant-service resource claim.

## Decision

Implement and benchmark single-node stateless activation first.

## Consequences

Cluster APIs remain specified, but no cluster implementation is required for the first milestone.
