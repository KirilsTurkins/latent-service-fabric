# Trusted AOT compatibility and output binding

Phase 2 introduces the first concrete trust boundary for reusable native AOT
artifacts. This document covers the compatibility identity and the sealed
trusted-local output association implemented by `latent-wasmtime`.

This is a partial delivery of issue #150. It does **not** yet launch or supervise
an isolated compiler process, persist native output, load precompiled bytes, or
replace the Phase 1 portable-component preparation path.

## Exact compatibility identity

`AotCompatibilityKey` binds one candidate native output to:

- the exact immutable OCI package digest;
- the exact portable component blob digest;
- the runtime/backend identity and Wasmtime version;
- the target triple and CPU feature policy;
- a digest over the complete current `WasmtimeEngineProfile`, including ordered
  engine configuration metadata and required containment feature switches;
- an exact capability-contract digest; and
- an exact security-policy digest.

Changing any of these inputs creates a different compatibility identity. A cached
or persisted native image must therefore be rejected rather than reused when the
runtime, target, CPU profile, engine configuration, capability contract, or
security policy changes.

The profile and identity material are bounded before retention. The AOT identity
is not a substitute for package admission: package signature/provenance/SBOM and
current release eligibility remain separate authority.

## Sealed trusted-local output

`TrustedAotCompilerAuthority` is host-owned. It accepts a host-approved compiler
identity and a 256-bit secret seal key that must not come from an untrusted
package, request, compiler output, or persisted self-asserted provenance field.
The authority rejects an all-zero key.

After an approved compiler boundary returns native bytes, the host can call
`seal` to produce `TrustedAotOutput`. The seal binds:

- the complete AOT compatibility-key digest;
- SHA-256 of the exact native output bytes;
- the exact native output length; and
- the configured compiler identity.

The native bytes are retained as a boxed slice so caller-controlled spare vector
capacity is not kept. Output size and profile metadata have finite hard ceilings.

Before any future native loader call, the same host authority can `verify` the
output against the expected compatibility key. Verification fails on another
compiler authority, changed compatibility inputs, changed output bytes, changed
output digest, or a changed seal.

A caller-controlled compiler name or digest therefore cannot by itself establish
native-code trust. The authority object and its secret are the trusted-local
ownership boundary for this slice.

## Remaining #150 work

The following acceptance criteria remain deliberately outstanding:

- launch the approved compiler in an isolated process or equivalent containment
  boundary with an explicit bounded input/output protocol;
- constrain compiler filesystem, environment and credential access;
- bound concurrent workers/jobs and input/output staging;
- keep process/job ownership after caller cancellation until the compiler and
  descendants exit and are reaped;
- enforce timeout, shutdown and temporary-file cleanup semantics;
- prove failure containment for malformed components, compiler failure,
  cancellation and timeout; and
- connect the sealed output to the persistent AOT storage/loading work in #151.

No native deserialization or unsafe loader boundary is introduced by this slice.
`#![forbid(unsafe_code)]` remains unchanged.
