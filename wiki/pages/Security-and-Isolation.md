# Security and Isolation

> **Document role:** Threat-model and control overview. Security-sensitive changes require review against the canonical architecture, ADRs, and tests.

## Trust assumptions

Untrusted by default:

- capsule code and capsule inputs;
- publishers not admitted by trust policy;
- remote invocation payloads;
- tenant-supplied metadata;
- responses from external providers;
- precompiled artifacts outside a trusted compiler boundary.

The platform should validate before allocating scarce execution resources or invoking unsafe host operations.

## Capability security

A guest capability is available only when:

```text
capsule import request
AND deployment grant
AND invocation-principal authorization
```

Capability handles are designed to be:

- opaque;
- activation-scoped;
- operation-scoped;
- quota-bound;
- expiring;
- revocable;
- auditable;
- non-transferable unless explicitly delegated.

Use after activation completion must fail.

## Default-deny guest world

The default capsule world exposes no unrestricted operating-system filesystem, sockets, processes, environment, threads, or secrets. External access occurs through WIT capabilities whose provider implementations remain under platform policy.

## Identity layers

LSF separates:

- transport peer identity;
- authenticated caller principal;
- logical tenant and service identity;
- node workload identity;
- delegated child-call identity;
- administrator identity.

A child call carries bounded delegation rather than the caller's unrestricted original credentials. Node transport identity and logical caller identity are authenticated and audited separately.

## Supply chain

Release admission should verify:

- content digests;
- publisher signatures and key or certificate policy;
- provenance;
- SBOM presence;
- requested imports;
- resource ceilings;
- minimum fabric version;
- forbidden features.

An immutable release digest covers the component and its immutable metadata inputs.

## AOT trust boundary

Nodes may compile verified components locally or accept precompiled output only from an isolated trusted compiler boundary. Cache identity includes engine version, configuration, target, and CPU features.

Untrusted native precompiled artifacts must not cross directly into the execution boundary.

## Isolation tiers

| Tier | Intended use |
|---|---|
| Wasm store boundary | Ordinary capsule isolation |
| Fixed trust-class execution-host processes | Stronger blast-radius partitioning |
| Ephemeral process, container, or microVM | Arbitrary native compatibility |
| Separate host or machine | Strict side-channel or high-value isolation |

The normal model remains a fixed number of generic execution hosts rather than one process per service.

## Secrets

Secrets should be returned through short-lived handles or values, not inherited environment variables. Providers must prevent secret material from entering logs, crash reports, snapshots, telemetry attributes, or derived artifacts.

## Reuse safety

Cell reuse must prove that no prior activation's input, output, handles, state namespace, buffers, or secrets are observable. Trap containment, cancellation, memory reset, and provider-handle revocation are security properties, not only resource-management details.

## Security review questions

A change should answer:

1. Which principals and trust boundaries are involved?
2. Which capability import, deployment grant, and operation authorization apply?
3. Which quotas and deadlines constrain abuse?
4. What is logged, and can it contain secret or tenant data?
5. What survives cancellation, trap, or node failure?
6. Can a cache or derived artifact cross incompatible policy or engine identities?
7. Does stronger isolation change the fixed-resource invariant?
8. Which security and leak tests prove containment?

## Canonical sources

- [Security architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/security.md)
- [Identity and capabilities](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/identity-and-capabilities.md)
- [Execution cells](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/execution-cells.md)
- [Security tests](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/tests/security)
- [Leak tests](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/tests/leak)
- [SECURITY.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/SECURITY.md)
