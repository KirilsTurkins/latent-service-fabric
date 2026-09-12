# Security architecture

Phase 1 provides the locally trusted standalone boundary: verified local
artifact bytes/metadata, explicit tenant credentials, stateless Wasmtime
containment and declared context/log/clock imports. Phase 2 additionally provides
the [publisher signature library](../reference/publisher-trust.md), using exact
package subjects and explicit current policy/revocation snapshots, plus separate
[builder provenance](../reference/build-provenance.md) for the maintained echo
recipe. [Authenticated catalog admission](../reference/package-admission.md)
combines these proofs with current SBOM and tenant policy. Workload mTLS,
secret providers, trust-sharded processes and native fallback remain future
security work. See [standalone authentication](../reference/standalone-node.md),
[catalog trust](../development/local-release-catalog.md#trust-boundary) and
[the Phase 1 completion scope](../phase-1-completion.md#implemented-surface-and-limits).

## Threat model

Untrusted by default:

- capsule code and inputs,
- publishers without an admitted trust policy,
- remote invocation payloads,
- tenant-supplied metadata,
- external provider responses,
- precompiled artifacts not produced by a trusted compiler boundary.

## Capability model

A capability is usable only when:

```text
capsule import request
AND deployment grant
AND invocation-principal authorization
```

Handles are opaque, activation-scoped, operation-scoped, quota-bound, expiring, and auditable.

## Default-deny guest environment

The default capsule world exposes no unrestricted operating-system filesystem, socket, process, environment, thread, or secret access. All external access uses WIT capabilities.

## Supply-chain boundaries

The bounded publisher verifier checks Ed25519 package signatures against raw
approved public keys, validity and explicit revocations. Its private proof binds
exact package/evidence bytes and both current trust snapshots. Certificate and
keyless workflows are unsupported. A signature never establishes tenant
ownership, semantic validity, routability or trusted native output.

Builder provenance uses separately approved keys and explicit source requirements.
It binds an observed component to the exact package and current builder trust.
Unsigned observations, matching referrers and publisher-only keys do not create
builder authority. The maintained build is nonhermetic and its repository label
remains an operator assertion.

Durable Phase 2 admission combines these proofs with provenance/SBOM and tenant
policy, complete package semantics and content checks. It retains durable
clock/generation floors and rechecks shared trust at publication and actual
activation start, independently of prepared-cache residency. Historical receipts
and public admitted flags do not authorize execution. Phase 1 local publication
remains explicitly locally trusted; signed admission does not protect against
an administrator replacing the whole node or its approved trust configuration.

## AOT boundary

Untrusted precompiled native artifacts are forbidden. Nodes compile verified component bytes locally or accept AOT output only from an isolated trusted compiler whose engine version, configuration, target, and CPU features are included in the cache key.

## Isolation levels

- Wasm store boundary for ordinary capsule isolation.
- Fixed trust-class execution-host processes for stronger blast-radius separation.
- Ephemeral process/container/microVM fallback for arbitrary native code.
- Separate hosts or machines for workloads with strict side-channel requirements.

## Planned secrets

Secrets are returned through short-lived handles or values, never inherited environment variables. Providers must prevent secret values from entering logs, crash reports, snapshots, telemetry attributes, or derived artifacts.
