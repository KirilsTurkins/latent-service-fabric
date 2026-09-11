# Security architecture

Phase 1 provides the locally trusted standalone boundary: verified local
artifact bytes/metadata, explicit tenant credentials, stateless Wasmtime
containment and declared context/log/clock imports. It does not yet provide
publisher signature/provenance verification, workload mTLS, secret providers,
trust-sharded processes or native fallback. Those sections below define later
security requirements. See [standalone authentication](../reference/standalone-node.md),
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

## Planned supply chain

Phase 2 admission is intended to add publisher signatures, certificate/key
policy, provenance and SBOM verification to the existing content digest,
manifest, import and resource checks. Phase 1 completion does not authenticate
publishers or make locally supplied artifacts safe under an untrusted filesystem.

## AOT boundary

Untrusted precompiled native artifacts are forbidden. Nodes compile verified component bytes locally or accept AOT output only from an isolated trusted compiler whose engine version, configuration, target, and CPU features are included in the cache key.

## Isolation levels

- Wasm store boundary for ordinary capsule isolation.
- Fixed trust-class execution-host processes for stronger blast-radius separation.
- Ephemeral process/container/microVM fallback for arbitrary native code.
- Separate hosts or machines for workloads with strict side-channel requirements.

## Planned secrets

Secrets are returned through short-lived handles or values, never inherited environment variables. Providers must prevent secret values from entering logs, crash reports, snapshots, telemetry attributes, or derived artifacts.
