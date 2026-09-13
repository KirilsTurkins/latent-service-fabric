# ADR-0025: Require explicit execution isolation profiles

- **Status:** Accepted
- **Date:** 2026-09-13
- **RFC:** [RFC-0001](../rfcs/0001-minimum-execution-isolation-profiles.md)

## Context

ADR-0017 permits a fixed node-defined set of trust-class execution hosts for stronger containment, but does not define when such a host is required. Phase 3 adds externally supplied capsules, capability providers and application renderers while the delivered runtime still uses fresh Wasmtime stores in fixed in-process cells. Phase 2 also delivered an optional Linux x86_64 isolated AOT compiler and authenticated same-node native reuse. Those boundaries solve different problems and must not be represented as interchangeable security guarantees.

## Decision

LSF security-sensitive execution uses explicit, versioned isolation profiles with exact threat assumptions, trusted components, platform prerequisites and finite acceptance evidence.

Profile compatibility fails closed. A requested profile that is unknown, unavailable or only partially enforceable must be rejected. Admission, preparation, provider selection or renderer selection may not silently downgrade to a weaker profile, in-process compilation, unauthenticated native loading or an unsupported host.

The baseline matrix is defined by RFC-0001:

- `local-experimental-v1` is the delivered fresh-store, in-process Wasmtime boundary. It supports trusted/local workloads and untrusted guest code only while the node, Wasmtime, host bindings and operating system remain trusted.
- `isolated-aot-compiler-v1` is the delivered bounded Linux x86_64 compiler-child boundary. It isolates compiler work only.
- `authenticated-native-aot-v1` is the delivered same-node authenticated native reuse/loading path. The native loader and node remain trusted; arbitrary external native artifacts are unsupported.
- `external-capsule-v1` is planned and requires enforced package admission, exact ABI/profile compatibility, protected trust configuration, the reviewed runtime baseline and supported isolated compilation before it can be selected.
- in-process provider and Component Model renderer profiles remain planned until their owning Phase 3 tickets implement and validate them.
- work that requires containment after compromise of the process executing the guest/provider/renderer/native compatibility layer requires `fixed-execution-host-v1`, a separate node-owned fixed/bounded host pool. That profile is unsupported until implemented and tested.
- host/kernel compromise and strong same-machine side-channel isolation remain outside the current standalone security boundary.

A package signature, compiler sandbox, guest `Store` limiter, profile label or cache entry is not proof that another boundary is present.

## Ownership of follow-up implementation

This ADR assigns enforcement rather than expanding the current runtime:

- #202 and #204 bind exact requested host/provider compatibility;
- #224 selects and validates renderer compatibility;
- #280 implements deployment/startup enforcement for the external-capsule profile;
- #238 retains integrated adversarial evidence;
- provider-specific tickets own provider bounds and failure behavior.

A new external execution backend is not required to complete this decision. If one is later implemented, its process count must remain fixed or node-configured bounded independently of service count. The supervisor may create, stop, kill, quarantine, reap and replace only those node-owned hosts. A failed host remains charged until termination and reap are observed and is never returned to the reusable pool.

## Interruption and accounting

In-process activations retain current cancellation, deadline, fuel/epoch and affirmative cleanup semantics. A failure that cannot safely stop or clean an in-process guest cannot be promoted to a process-containment claim; the affected cell must not be reused and node-level recovery may be required.

The isolated compiler retains child ownership and reservations through cancellation, kill and actual reap. Native deserialize remains a trusted synchronous node operation. Future provider/renderer/fixed-host profiles must define equivalent bounded ownership, quarantine, shutdown and crash recovery before support.

Guest store limits are not whole-process RSS limits. Runtime/embedder allocations, native code, allocator retention, provider state, caches and IPC have separate ownership and accounting domains.

## Resource invariant

The decision preserves:

```text
resident resources = fixed node runtime + active activations + bounded shared caches and provider pools
```

Dormant deployments do not own processes, threads, listeners, sockets, provider instances, renderers, runtime instances or execution cells. Stronger containment may add fixed/bounded node-owned infrastructure, never one persistent host per service.

## Consequences

- Security-profile names become compatibility requirements, not informal descriptions.
- Stronger claims require profile-specific evidence before they are documented as supported.
- Existing Phase 1/2 behavior remains available with more precise boundaries.
- Phase 3 can proceed under the documented in-process trust model without pretending that compiler isolation provides guest-process isolation.
- Hostile-multitenant/native-compatibility workloads that require process-compromise resistance remain unsupported until a fixed execution-host backend exists and passes its evidence matrix.
