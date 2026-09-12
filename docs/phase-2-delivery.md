# Phase 2 delivery notes

These are unreleased development notes. The current tagged release remains
`0.1.0-alpha.2`, which records Phase 1 and its prioritized performance extension.
Phase 2 feature delivery is present; its completion decision belongs to
[gate #158](https://github.com/KirilsTurkins/latent-service-fabric/issues/158).
Closed implementation tickets alone do not establish that decision.

## Features

- [Deterministic packaging](component-development/packaging.md) binds original
  package, configuration, component, WIT and asset bytes. Explicit inventories
  produce [SBOMs](component-development/sbom.md); the maintained build observer
  records [source and tool provenance](reference/build-provenance.md).
- [Authenticated OCI transfer](reference/oci-registry.md) supports exact package
  and detached evidence bytes, immutable digest selection, TLS, separate registry
  credentials and finite transfers. It does not turn registry possession into
  publisher authority.
- [Publisher and builder trust](reference/publisher-trust.md), tenant and SBOM
  policy fence [catalog admission](reference/package-admission.md). Current
  authority, lifecycle and runtime compatibility are checked again before use,
  including cached preparation and native loading.
- [Raw caching](reference/raw-artifact-cache.md), isolated compilation and a
  [protected persistent native cache](runtime/trusted-aot.md) have explicit
  byte, image, process and lease owners. Native output requires the approved
  local compiler and a separate protected authentication key.
- [Durable audit](phase-2-audit.md), versioned managed deployments and
  [rollout plans](phase-2-rollouts.md) retain inspectable operation identities.
  [Canary promotion](phase-2-canary-promotion.md) uses exact observed windows;
  [rollback](phase-2-rollback.md) restores eligible content through a new route
  generation and preserves existing activation pins.
- The [operator CLI](reference/operator-cli.md) exposes package
  build/inspect/verify/push/pull, publication and lifecycle, managed deployment
  receipts, rollout control, observation and audit pagination. Files remain
  client-local; authenticated management sends bounded bytes and typed inputs.

![Phase 2 package transfer, node admission and explicit rollout control.](assets/phase2-delivery-boundary.svg)

## Upgrade and recovery

Existing trusted-local catalogs retain their explicit compatibility mode.
Enforced roots require complete current public policy and cannot reopen through
the legacy constructor. Review [admission migration and clock leases](reference/package-admission.md#clock-leases-retries-and-migration)
before changing policy or restarting; an immediate restart can correctly fail
until its persisted future clock floor is reached. Do not delete a policy floor,
catalog marker or audit journal to bypass that failure.

Deployment formats 1 through 3 retain their historical decoding rules. The first
managed deployment operation writes format 4 with its bounded receipt history;
rollout mutations preserve that history. Old binaries that cannot read the new
format are not a supported rollback strategy. Application rollback uses current
eligibility and a new publication, as described in the
[rollback runbook](phase-2-rollback.md).

After a timeout, inspect the original operation ID and exact route/catalog
versions. `Unknown` includes absent or evicted receipts and cannot establish
that a mutation never ran. Publication identity, directory synchronization and
audit acknowledgment are separate facts. Keep original caller preconditions;
the CLI does not retry mutations or silently refresh their versions.

Registry outage prevents transfers. Already retained local bytes do not need a
registry connection for invocation, but their current policy and lifecycle must
still permit use. Neither cached bytes nor a cached positive proof extends
expiry or reverses revocation. Corruption fails closed; recovery must use exact
verified bytes and the documented catalog procedures.

## Validation and limits

The [bounded walkthrough](development/standalone-quickstart.md) uses separate
client/node processes, an authenticated TLS registry and fresh public test
policy. It exercises exact transfer, deployment, actual invocations, canary
promotion, rollback, audit, restart and revocation. Its signed test observation
is synthetic; the separately maintained observed-build integration supplies
the actual build-capture evidence. [Validation](../VALIDATION.md) identifies both.

This remains a standalone Linux stateless node. Package contracts for browser
assets and SSR do not provide application ingress, browser hosting or rendering.
The [Phase 3 backlog](roadmap.md#phase-3-capabilities-and-application-hosting)
tracks general capabilities, providers, SDK transports and web delivery.
Distributed placement, durable state/effects and workflows remain later phases.
Finite test profiles establish their observed behavior, not production SLOs,
universal memory ceilings or a general dependency-security guarantee.
