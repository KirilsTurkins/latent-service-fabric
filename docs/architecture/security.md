# Security architecture

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

## Supply chain

Admission verifies content digests, publisher signatures, certificate/key policy, provenance, SBOM presence, requested imports, resource ceilings, minimum fabric version, and forbidden features.

## AOT boundary

Untrusted precompiled native artifacts are forbidden. Nodes compile verified component bytes locally or accept AOT output only from an isolated trusted compiler whose engine version, configuration, target, and CPU features are included in the cache key.

## Isolation levels

- Wasm store boundary for ordinary capsule isolation.
- Fixed trust-class execution-host processes for stronger blast-radius separation.
- Ephemeral process/container/microVM fallback for arbitrary native code.
- Separate hosts or machines for workloads with strict side-channel requirements.

## Secrets

Secrets are returned through short-lived handles or values, never inherited environment variables. Providers must prevent secret values from entering logs, crash reports, snapshots, telemetry attributes, or derived artifacts.
