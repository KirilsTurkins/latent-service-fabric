# ADR-0010: Separate immutable capsule metadata from deployment policy

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Code identity and environment-specific grants change at different rates and require different trust rules.

## Decision

Capsule manifests remain immutable with the release; deployments carry mutable routing, placement, grants, and limits.

## Consequences

A deployment change creates a new revision generation without changing the release digest.
