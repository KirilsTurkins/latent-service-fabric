<!-- LSF-WIKI-MANAGED -->
# Deployment and routing

Deployment, release resolution, and routing are part of the planned fabric.
They are not executed by the finite Phase 0 `latentd phase0-spike` command.

## Intended model

```text
release digest + deployment policy + grants/limits
  → revision
  → immutable route snapshot
  → local route selection for a new activation
```

A control plane is intended to validate desired state, compile bindings and
routes, and distribute immutable snapshots. A data-plane node should keep
using a valid local snapshot through a temporary control-plane outage.

## What is absent in Phase 0

The spike accepts a local capsule path. It does not manage releases,
deployments, route snapshots, traffic weights, rollback, canary routing,
policy admission, shared ingress, or a public invocation listener.

The checked-in Protobuf and JSON Schema surfaces document those future
concepts. They are architectural/contract sources, not evidence that a
corresponding production service is running.

## Canonical sources

- [Versioning and deployment architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/architecture/versioning-and-deployment.md)
- [Control plane](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/architecture/control-plane.md)
- [Data plane](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/architecture/data-plane.md)
- [Route and deployment schemas](https://github.com/KirilsTurkins/latent-service-fabric/tree/development/schemas)
