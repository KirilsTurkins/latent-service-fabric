# RFC-0005: Exact Phase 3 host ABI profiles

- **Status:** Accepted
- **Authors:** Latent Service Fabric maintainers
- **Created:** 2026-09-13
- **Target milestone:** Phase 3, #202
- **Accepted by:** [ADR-0031](../adr/0031-version-host-abi-recognition-independently-of-provider-authority.md)

## Summary

This RFC records the V2 selection. [ADR-0032](../adr/0032-use-bounded-owned-resources-for-streaming-http.md)
and the [current profile reference](../docs/runtime/host-abi-profile.md) describe
the delivered V3 streaming extension and current provider availability.

`lsf-host-abi-phase3-v2` recognizes exact, bounded Phase 3 host interfaces during
package inspection. Recognition does not install a provider or grant execution.
The runtime still installs only context, log and the two clock interfaces.
Required provider imports fail preparation until their node-owned implementations
and activation authority exist. The [build matrix](../wit/host-abi-phase3-v2.json)
records source hashes, versions, selected async forms and current availability.

## Motivation

Independent name allowlists cannot establish agreement between pinned package
sources, compiled imports, generated bindings and native cache compatibility.
The previous v1 profile freezes four implemented imports. Extending that profile
in place would also conceal changes in host error and asynchronous semantics.

This decision retains WIT authority, fresh activation state and bounded reusable
cells. It applies [ADR-0025](../adr/0025-separate-immediate-capability-operations-from-transactional-effect-intents.md),
[ADR-0026](../adr/0026-require-explicit-execution-isolation-profiles.md) and
[ADR-0028](../adr/0028-retain-activation-ownership-across-asynchronous-waits.md).

## Detailed contract

The immutable `latent-core::HostAbiProfile` contains exact interface/package
identities, authoritative WIT source, binding kind and an async-function flag.
It has no engine, provider, credential, principal, policy, handle table or pool.
Core remains free of runtime dependencies. Packaging, component comparison and
Wasmtime preparation use this same profile.

| Interface | Version | Guest function form | Current binding |
| --- | --- | --- | --- |
| context/context | 0.1.0 | synchronous | built in |
| log/log | 0.1.0 | synchronous | built in |
| clock/monotonic, clock/wall | 0.1.0 | synchronous | built in |
| random/random | 0.1.0 | synchronous | unavailable provider |
| blob/blob | 0.1.0 | synchronous | unavailable provider |
| secrets/reader | 0.1.0 | synchronous | unavailable provider |
| events/publisher | 0.2.0 | synchronous | unavailable provider |
| http/client | 0.2.0 | asynchronous | unavailable provider |
| telemetry/custom | 0.1.0 | synchronous | unavailable provider |
| service/invoke | 0.1.0 | asynchronous | unavailable provider |

All names have the `latent:` prefix and exact `@version` suffix. Context/log/clock
source bytes and versions are unchanged. HTTP and events 0.1.0 remain retained
contracts in the legacy aggregate world; v2 recognition selects their new 0.2.0
versions. State and timer packages remain later-phase contracts.

Inspection compares the complete declared host interface with the trusted WIT.
A component compiler may prune unused imports or members, but every retained
member must match the complete pinned source graph, including parameter names,
ordered nested types, results and function kind. Matching source hashes and a
matching component cannot invent a different same-name host interface. Unknown
versions, partial source declarations and extra members fail closed.

The selected type forms are primitives, transparent aliases, records, variants,
enums, tuples, lists, options and results. Only HTTP `send` and service `call` use
freestanding async imports. The #209
[local service profile](../docs/runtime/local-service-invocation.md) additionally
selects freestanding async application exports with exact function-kind metadata
and an installed node adapter. This application profile leaves the frozen host
WIT unchanged. Component Model resources, borrow/own handles, futures, streams,
error-context, flags, maps and fixed lists remain rejected by semantic comparison.
Syntax recognized by the engine is not
automatically an admitted capability. #205 and #212 must version any additional
forms they select; this profile does not claim streaming HTTP delivery.

The existing parser/arena/comparison bounds still apply: at most 64 source-world
imports, 65,536 type nodes, depth 64, 1,024 members per aggregate, 512 bytes per
name, 256 parameters, 256 source packages, 256 KiB per WIT source and 4 MiB total
WIT source. Callers may lower these limits. Whole-world component comparison and
the complete pinned-host comparison each have one conserved work allowance;
adding interfaces cannot reset that allowance. Binary section, function,
operator, summary and token ceilings remain independently enforced.

## Ownership and error semantics

All transferred strings and byte buffers belong to the active call and remain
charged through consumption or cleanup. Returned values do not outlive their
activation unless copied into separately authorized bounded immutable storage.
A synchronous guest ABI may await an asynchronous host operation, but it cannot
justify blocking a shared execution or control thread. Yielding retains the
activation's cell, store, buffers, handles and reservations.

`blob-handle` is an opaque `u64` token, not a pointer, file descriptor, global
object ID or authority. Its provider must bind it to one activation, tenant and
provider generation; reject invented, closed, stale and foreign tokens; prevent
reuse from reviving a token; and close all outstanding handles before cell
reuse. Open references name immutable content and require fresh authorization.
Create/write/seal stages are immediate provider operations; a successful seal
returns verified content identity and does not commit guest application state.
These implementation obligations belong to #204, #213 and #214.

Secret references are policy-selected names. Returned secret bytes and versions
are activation-owned sensitive data, never cache identity or telemetry. Random
output has byte/fuel charges; custom telemetry is subject to cardinality and
reserved-name rules. The concrete provider tickets define finite per-operation
and retained bounds before installing these recognized ABIs.

HTTP 0.2.0 adds invalid-request, cancelled and uncertain results. Success means a
complete bounded HTTP response, including possible HTTP error status. `uncertain`
means the external operation may have occurred without a complete trustworthy
response. Known pre-dispatch cancellation/deadline errors remain distinct.
No outcome authorizes an automatic retry or implies transaction rollback.

Events 0.2.0 adds explicit invalid-event, deadline, cancelled and uncertain
results plus broker stream name, sequence and duplicate fields in its receipt.
The receipt acknowledges broker publication, not consumer processing, application
commit or universal exactly-once delivery. An idempotency key is not permission
to replay an uncertain operation. The JetStream provider must validate these
receipt fields against its authorized publication before returning success.

Legacy typed errors remain frozen for the other selected packages. Activation
termination, missing capability authority or failure of mandatory accounting is
a platform failure where the WIT result has no suitable case; it must not be
disguised as provider success. Child calls preserve the existing explicit
success/declared-error/platform-failure distinction, inherited deadline and
conserved descendant budget. Lineage and caller-supplied metadata grant no
authority. #204, #207, #208 and #209 implement those boundaries.

## Compatibility and migration

The legacy aggregate `latent:platform/capsule@0.1.0` remains available to binding
consumers. A new aggregate at 0.2.0 selects this profile. Staging resolves only
the referenced package versions, so unrelated versions cannot rename generated
Rust modules. Host and guest Rust bindings are generated from those worlds in
the existing binding owner; native and Wasm targets are checked in normal CI.
The JSON schema/matrix is a portable compatibility description, not a remote
client implementation or a substitute for the six SDK delivery tickets.

The profile digest is SHA-256 over `lsf-host-abi-profile-v1\0`, a framed profile
ID, an interface count, and the ordered entries. Each entry frames its interface
and package strings, writes built-in/provider as 0/1 and async as 0/1, then frames
the exact WIT source bytes. Frames and counts use unsigned 64-bit little-endian
lengths. Sources use LF as required by `.gitattributes`; even a source comment
change conservatively changes identity.

Generic prepared configuration contains the profile ID and digest. The AOT
capability digest uses the same identity, in addition to existing actual-engine,
input, policy and runtime compatibility checks. Old prepared/AOT identities
therefore miss or fail validation and must be regenerated. The legacy Phase 0
adapter remains separately identified. Component/package/publication wire
identities do not change meaning.

Mutable grants, credentials and provider rotations remain outside native-code
authority. Current publication eligibility and exact prepared descriptors are
checked at invocation, including the final guarded-start boundary. Required
activation imports must still be present. The sealed broker and provider epoch
checks in #204/#207 extend authority at actual host use; this ABI change does not
claim that those unfinished mechanisms already exist.

## Security and resource impact

The matrix is frozen against Wasmtime 47.0.4 and guest generator wit-bindgen
0.60.0. No WASI filesystem, HTTP, WASIp3 stream or ambient process/network surface
is installed. Enabling such interfaces requires a new advisory reachability
review; an upstream affected version and an exposed affected interface remain
different findings. Real generated-linker tests supplement profile-name checks.

ABI compatibility does not select stronger isolation. The delivered runtime
remains `local-experimental-v1`; isolated compilation and authenticated native
reuse retain their separate boundaries. `external-capsule-v1` startup enforcement
belongs to #280, and `fixed-execution-host-v1` remains unavailable. New providers
must enforce required profiles through their actual owners before registration;
an in-process label cannot satisfy a stronger containment requirement.

Profiles allocate no dormant service resources. The finite sources and generated
types are node/code data; package parsing is bounded preparation work. No pool,
listener, task, store or provider connection is created by ABI recognition.

## Alternatives and validation

Independent runtime allowlists were rejected because names cannot prove binding
shape agreement. Enabling every Wasmtime type was rejected because engine support
alone does not establish finite transfer or cleanup semantics. Mutable grants in
the native key were rejected because compiled-code sharing is not authority.

Validation uses small real components for all 11 interfaces, exact generated
built-in and async HTTP linker checks, wrong versions/shapes/function kinds,
missing providers, stale/forged prepared identity, bounded comparison failures,
unsupported async/resource/stream forms and AOT profile changes. Independent
Python schema/source/world/generator parity and Rust profile checks run in normal
CI. These are ABI tests, not provider performance or hostile-multitenant evidence;
the provider, security and Phase 3 gate tickets retain those responsibilities.
