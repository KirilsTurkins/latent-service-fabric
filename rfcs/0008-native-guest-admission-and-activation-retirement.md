# RFC-0008: Native guest admission and activation retirement

- **Status:** Draft
- **Authors:** LSF project contributors
- **Created:** 2026-10-15
- **Target milestone:** Phase 7 optional backend research

## Summary

Propose a separate admission and lifecycle contract for native guest artifacts,
shared by possible [native-SFI](../research/native-sfi/README.md) and
[hardware-compartment](../research/hardware-capabilities/README.md) backends.
Native guests remain guests with activation-scoped authority; they do not enter
through the trusted Wasmtime AOT cache or ordinary host-library loading.

The decision requested is this separation and the artifact, host-entry and
retirement obligations below. This draft selects no toolchain, capability ISA,
public profile name or native ABI, and enables no native execution. No mechanism
is adopted here. Promotion requires a mechanism-specific ADR and conformance evidence.

## Motivation

The existing [isolation-profile contract](0001-minimum-execution-isolation-profiles.md)
describes threat classes and fail-closed selection. Existing authenticated AOT
binds trusted locally compiled Wasmtime output; it does not sandbox arbitrary
native input. The new question is how native guest bytes could be admitted and
reused without inheriting host authority or confusing authenticity with isolation.
SFI and hardware compartments need different safety evidence but the same LSF
identity, accounting and physical retirement discipline.

## Detailed contract

### Separate artifact family and immutable preparation

Introduce an explicitly reviewed native guest artifact family only when its
manifest/packaging/backend contracts are implemented. Never infer it from file
extensions, symbol names or opaque Wasmtime artifacts. Its descriptor must bind:

| Area | Required identity or rule |
| --- | --- |
| Image and publication | Exact final executable/data bytes, segments, dependencies, finite bounds and exact tenant-scoped publication/release association. |
| Platform and ABI | ISA, endianness, CPU/capability features, calling/value/resource ABI, runtime/loader/gate versions and selected security profile. |
| Build and transformations | Compiler/sysroot/runtime libraries, assembler/linker/rewriter/post-linker identities, options, generated stubs and allowed relocations. |
| Safety mechanism | Exact SFI verifier/policy or hardware/software compartment configuration, validation owner and evidence scope. A guest-supplied certificate is not a trusted admission result. |
| Resource model | Stack, mutable memory, image/metadata, calls, interruption and cleanup bounds, plus accounting semantics affecting preparation. |

Verify the bytes actually executed after relocation/transformation, or demonstrate
that every admitted transform preserves the selected safety argument. Keep code
immutable with no writable executable alias or unqualified dynamic extension.
Initialization and constructors execute inside the guest boundary, not as trusted
loader callbacks before containment is installed.

Prepared code may be reusable; current publication/grant authority remains checked
at use and final start. Cache validity, supply-chain provenance, execution safety
and completed retirement are independent predicates with trusted owners.

### Mechanism-specific safety

An SFI candidate must enforce its exact instruction, memory, control-transfer and
host-entry discipline over all executable dependencies. A hardware candidate must
establish narrow initial and transitively reachable capabilities, controlled entry,
OS-call restrictions and safe lifetime/reuse for its exact ISA/ABI. A verifier
proof on one target cannot qualify another; a hardware tag is not automatic expiry.
Neither mechanism may inherit the other's evidence by sharing this RFC.

The initial candidate is a bounded C computation in an isolated research harness,
with no threads, JIT, dynamic loading, ambient syscalls or unsupported callbacks.
A later backend must qualify bounded interruption even when the guest makes no
host calls, fault recovery and healthy subsequent invocation inside its actual
execution boundary. An outer process kill is not in-process interruption evidence.

### Host authority and retirement

Use a typed, checked native value/resource representation with bounded buffers,
errors, ownership and async completion. WIT may describe logical interfaces, but
its existing Component Model representation does not automatically define this ABI.
Every host entry preserves the actual member activation, current provider/grant,
required audit, original budget/deadline and cancellation owner. No raw host object,
copied capability or cached image can manufacture another reservation or session.

Each activation owns fresh globals, heap, stack, TLS, runtime state and handles.
Retain immutable code separately from mutable execution. Before reuse, stop guest
execution and retire callbacks, borrows, descendant/provider work and old memory
authority, or make an explicitly bounded safe transfer. Escaped native references
cannot reach memory reused by a later activation. Logical handle generations and
zeroing are not substitutes for direct-reference retirement.

## Compatibility and migration

Portable Wasm capsules and the existing AOT path retain their current contracts.
No current backend enum, package schema or security selector gains native support
from this draft. Publish authoritative descriptor/ABI/profile changes and generated
projections through interface review before enabling admission.

Missing hardware/verifier/runtime prerequisites reject the selected native profile;
there is no silent fallback to unrestricted native code or a weaker profile.
Narrow host-library compartment studies, a capability-aware engine port and
Wasmtime MPK optimization are separate claims, not native guest admission.
Native support does not qualify six language runtimes, server API lowering or
transactional calls without their own integration evidence.

## Resource-allocation impact

Use fixed or bounded node-owned execution/compilation capacity independent of
deployment count. Dormant services retain code and bounded metadata, not a heap,
thread, process, socket or provider connection. Charge validation, images, native
metadata, stacks, callbacks, revocation/quarantine and cleanup until actual owners
retire. Finite limits apply to malformed input and compilation as well as execution.

## Security and trust-boundary impact

Retain the threat taxonomy and limits of RFC-0001. An in-process SFI/CHERI boundary
does not by itself provide T2 process-compromise resistance or T3 kernel/side-channel
isolation. Name the exact trusted verifier/decoder, loader, runtime gates, allocator/
revoker, bindings, OS and hardware. Hardware memory authority does not replace
LSF application policy; a union of guest and host authority is forbidden.

## Failure semantics

Malformed, unsafe, incompatible or no-longer-authorized artifacts fail before
guest execution. A native fault must produce the declared isolated outcome and
complete actual cleanup; otherwise withhold capacity under quarantine/recovery.
Client timeout, cancellation delivery or a return value cannot establish that
execution stopped. Never retry uncertain external work or report a cell reusable
while live native authority can re-enter it.

## Alternatives

Continue using Wasmtime components and authenticated AOT. Fixed separate execution
hosts may serve workloads requiring a different containment boundary under
RFC-0001. Selective native host-component isolation may provide value without
introducing guest artifacts. An architecture-specific native frontend must justify
its benefit and maintenance cost over these existing or separately planned paths.

## Validation plan

Use the [SFI matrix](../research/native-sfi/evaluation-plan.md) and
[hardware lifetime matrix](../research/hardware-capabilities/evaluation-plan.md)
for their respective mechanisms. Cover final-byte tampering/relocation, forbidden
access and host entry, infinite loops, faults, capability escape/reuse, stale
handles, current policy, callbacks, exhaustion and physical cleanup. Pin the exact
bundle and compare workloads with equivalent capability/lifecycle guarantees.
No native experiment or backend qualification accompanies this RFC.

## Open questions

1. Which first workload and exact mechanism/platform can satisfy bounded
   interruption, fault recovery and memory-authority retirement?
2. What native artifact descriptor, ABI and public selection surface should be
   reviewed, without overloading Wasmtime AOT identities?
3. Which transformations are independently verified and which components remain
   trusted in each candidate's safety argument?
4. Can non-escape be enforced, or what bounded revocation/retention protocol is
   required for direct references and asynchronous owners?
5. Which evidence would justify adding this backend rather than retaining Wasm
   or using a separately contained execution host?
