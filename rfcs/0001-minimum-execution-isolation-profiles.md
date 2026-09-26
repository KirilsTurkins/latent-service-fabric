# RFC-0001: Minimum execution isolation profiles

- **Status:** Accepted
- **Authors:** LSF project contributors
- **Created:** 2026-09-13
- **Target milestone:** Phase 3 - Capabilities

## Summary

LSF uses explicit security profiles to distinguish the containment guarantees required for guest execution, compilation, native loading, capability providers, and application renderers. A profile is an exact compatibility and enforcement requirement, not a marketing label. If the requested profile cannot be provided on the current host, admission, preparation, or startup must fail closed rather than silently selecting a weaker profile.

The current node has two delivered containment boundaries:

1. fresh Wasmtime stores in fixed in-process execution cells; and
2. the optional Linux x86_64 isolated AOT compiler child described by `docs/runtime/trusted-aot.md`.

The second boundary isolates compilation only. It does not turn guest execution, native loading, provider code, or the whole node into separate security processes.

## Motivation

ADR-0017 permits a fixed node-owned set of trust-class execution hosts, but it does not say which workload or threat class requires one. Phase 3 adds providers, browser-facing rendering, broader capability surfaces, and explicit deployment security profiles. Those features need a common rule for when in-process containment is sufficient, when a separate execution host is required, and what evidence is necessary before a stronger profile can be advertised.

The decision must preserve the core resource invariant: dormant deployments do not own processes, operating-system threads, listeners, sockets, runtime instances, provider instances, renderers, or execution cells. Stronger containment may add only a fixed or explicitly bounded node-owned host pool independent of service count.

## Detailed contract

### Threat classes

The matrix uses four threat classes:

- **T0 - operator-trusted workload:** package source, deployment configuration, and guest code are controlled by the operator. Ordinary correctness and accidental-failure containment are required.
- **T1 - untrusted component:** guest/component bytes and inputs may be malicious, but the node, Wasmtime, host bindings, approved provider implementation code, native loader, and host operating system remain trusted. The supported boundary must contain guest-visible state and resource use according to its documented limits.
- **T2 - host-process compromise resistant:** the workload may attempt to exploit a Wasmtime, provider, renderer, native-code, or host-binding defect. The required boundary must survive compromise of the process executing that workload. A separate fixed execution host is therefore required.
- **T3 - host/kernel compromise or strong side-channel isolation:** the threat includes compromise of the host kernel, hardware, or same-machine side channels. No current LSF profile claims this boundary. Separate-machine or stronger hardware isolation is outside the delivered standalone model.

A profile may support more than one workload type, but it must never imply a stronger threat class than its evidence establishes.

### Profile matrix

| Profile | Status | Work | Supported threat | Boundary and trusted components | Platform / prerequisites |
| --- | --- | --- | --- | --- | --- |
| `local-experimental-v1` | Delivered | guest execution and ordinary local preparation | T0 operator-trusted/local admission | fresh Wasmtime store in a fixed in-process cell; standalone node, Wasmtime, host bindings, parser/validator, in-process compiler and OS are trusted | current standalone-runtime platform support; no separate guest process or hardened external-capsule admission |
| `isolated-aot-compiler-v1` | Delivered, opt-in | compilation of verified portable components | T1 for compiler work only | one bounded child per reserved job, authenticated executable, Landlock ABI 3 + seccomp, hard limits, bounded pipes, kill/reap ownership; parent parser/validator and OS remain trusted | Linux x86_64 with the exact sandbox prerequisites in `docs/runtime/trusted-aot.md` |
| `authenticated-native-aot-v1` | Delivered, opt-in | same-node reuse/loading of output produced by the approved isolated compiler | T0/T1 input integrity under the node TCB; not T2 native-code isolation | protected host-local key, exact compatibility key, authenticated native bytes, bounded cache/image owners, one audited copying deserialize boundary; node/native loader/Wasmtime/OS are trusted | same supported isolated-AOT platform; arbitrary external native artifacts are unsupported |
| `external-capsule-v1` | Delivered by #280 | externally supplied component admission plus guest execution | T1 | enforced package admission, exact host ABI/profile compatibility, protected credentials/trust configuration, reviewed runtime baseline, supported isolated compilation, fresh in-process Wasmtime guest store | #202, #278, #279 and #280 provide exact compatibility, protected files, reviewed dependencies and enforced startup/preparation requirements; see the execution-profile reference |
| `provider-inprocess-v1` | Planned | shared capability-provider execution | T0 provider implementation; T1 guest/provider inputs | bounded node-owned provider pool with policy, quotas, cancellation and cleanup; provider implementation remains inside the node TCB | #204 and provider-specific tickets must define exact compatibility and evidence before use |
| `renderer-component-v1` | Planned | Component Model application renderer | T1 under the ordinary Wasmtime/node TCB | fixed generic execution cells and shared node ingress; no application-owned listener, persistent Node.js process, or service-specific worker pool | #224 must select and validate the renderer profile before it is supported |
| `fixed-execution-host-v1` | Unsupported until implemented | guest, provider, renderer, or native-compatibility work requiring T2 | T2 | separate node-owned process boundary from a fixed/bounded trust-class host pool; host supervisor, IPC boundary, OS and kernel remain trusted | no current implementation; requires explicit implementation and #238 evidence |
| `host-machine-isolated-v1` | Unsupported | workloads requiring T3 | T3 | separate-machine or stronger hardware boundary | outside current standalone delivery |

`external-capsule-v1` intentionally does not claim T2. Enforced signatures, provenance, isolated compilation, and fresh Wasmtime stores reduce different risks; none makes the Wasmtime/node process itself an untrusted boundary.

The local default's Wasm execution barrier remains useful under the trusted
Wasmtime/node implementation. It does not establish end-to-end T1 admission:
the default is `TrustedLocal`, compilation is in-process unless isolated AOT is
explicitly configured, and protected credential/trust files are independently enforced by #278.
Enforced admission does not automatically select isolated compilation. T1
external-capsule support requires every `external-capsule-v1` prerequisite and
its evidence to pass.

The names in this table are architectural identities. Implementation status:
#280 now supplies the two node selectors and checks their actual owners before
startup/preparation. The [execution-profile reference](../docs/runtime/execution-security-profiles.md)
maps the delivered requirements to finite evidence. Provider/renderer/fixed-host
profiles still require their separate implementations; the taxonomy is unchanged.

The delivered compiler readiness protocol continues to require
`lsf-linux-x86_64-landlock3-seccomp-v1`. The architectural
`isolated-aot-compiler-v1` name does not replace or alias that wire identity.

### Exact compatibility and no downgrade

A deployment or preparation path that requests a security profile must bind the exact profile identity into the compatibility decision owned by #202/#204 and the relevant renderer/provider selector. The effective profile must be observable without exposing credentials or secrets.

The following are errors, not reasons to downgrade:

- a requested profile is unknown;
- required OS facilities are absent or only partially available;
- the configured isolated compiler does not match its approved executable/profile;
- protected credential/trust prerequisites are unavailable;
- the runtime/dependency baseline is not the reviewed baseline for the profile;
- a provider or renderer requires a stronger profile than the node can supply; or
- a T2 workload is requested when no separate fixed execution host exists.

A cache hit, previously prepared artifact, package signature, profile label, guest `Store` memory limit, or compiler sandbox cannot substitute for these checks.

### Supervisor operations for separate hosts

If `fixed-execution-host-v1` is implemented, the node supervisor may create, stop, kill, quarantine, reap, and replace only a fixed or configured-bounded set of node-owned hosts. Host count is independent of registered service count. Work enters through bounded authenticated IPC owned by the node; a deployment cannot request a dedicated persistent host.

A compromised, crashed, timed-out, or non-cooperatively stuck host is not returned to the reusable pool. It remains charged until termination and reap are observed. Replacement capacity is acquired under the same node-owned ceiling. Guest/provider code may not create descendants or widen the supervisor's allowed operations.

Process separation alone is insufficient. The selected OS facilities must
prevent worker access to supervisor memory, trust/signing keys, inherited
privileged descriptors and unrelated files, sockets or tenant resources. Workers
receive only the exact activation authority delegated over bounded authenticated
IPC. Untrusted native code, provider callbacks and renderer execution stay behind
that boundary; the supervisor does not execute worker-supplied code.

Each host needs independent enforced CPU-time, address-space or memory, wall-time,
descriptor, task/descendant and IPC byte/queue limits. Limits must remain effective
after worker compromise and must not be supplied or relaxed by that worker.
Descendants are denied unless a later reviewed profile contains and accounts for
the complete process tree. Kill/reap must cover that tree before any host slot or
resource allowance is returned. OS-policy or IPC enforcement failure rejects the
profile before untrusted work starts; no T2 claim is made from a PID or a
supervisor timeout alone.

### Interruption, quarantine, shutdown, and recovery

For `local-experimental-v1`, ordinary activation cancellation/deadline/fuel/epoch handling remains the first interruption mechanism. A trap or normal cancellation must retire the activation and complete affirmative cell cleanup before reuse. Because execution is in-process, a defect that prevents safe interruption or corrupts the node process cannot be contained by killing only a guest process; the affected cell must not be reused, and process-level recovery may require node restart. This profile therefore does not claim T2 containment.

For `isolated-aot-compiler-v1`, cancellation, timeout, malformed output, crash, or shutdown retains the child and all reservations until the child exits and is reaped. There is no in-process compiler fallback in that configured mode.

For `authenticated-native-aot-v1`, authentication/currentness failures reject the cached artifact. The synchronous native deserialize boundary has no independent cancellation hook and is part of the node TCB; a hang or process fault is not promoted to a stronger containment claim.

Future in-process provider and renderer profiles must define bounded operation ownership and quarantine rules before support. Future fixed execution hosts must treat process exit/reap as the refund barrier and must prove that one failed host does not leak activation identity or owned resources into a replacement host.

### Accounting boundary

Guest `Store` limits account guest-visible resources, not complete process RSS. Whole-process memory also includes Wasmtime/embedder allocations, native code, allocator retention, provider state, caches, IPC buffers, and other node-owned data. Compiler child hard limits cover that child only. Provider and renderer budgets must account their own shared pools and retained state separately.

No profile may claim a whole-process memory bound from a guest memory/table limiter alone.

## Compatibility and migration

This RFC does not change WIT, Protobuf, JSON Schema, package bytes, or the current default runtime. Existing trusted-local behavior maps to `local-experimental-v1`; existing optional isolated AOT compilation and authenticated native reuse map to their delivered subprofiles above.

#280 owns configuration/startup enforcement for `external-capsule-v1`. #202/#204 own exact ABI/provider compatibility. #224 owns renderer selection. #238 owns integrated adversarial evidence. No new execution backend is required to accept this decision.

## Resource-allocation impact

The decision adds no runtime resource by itself. Any future separate host implementation must be node-owned and fixed/bounded independently of service count. Dormant deployments remain metadata/artifacts only and never acquire a process or host slot merely by being registered.

## Security and trust-boundary impact

The trusted computing base is explicit per profile. Parent-side parsing, package verification, configuration, the runtime, native loader, and provider implementations remain trusted unless a later profile moves them behind a separate boundary. The isolated compiler child narrows compiler exposure but does not isolate those parent-side stages.

Credentials, trust roots, native-authentication keys, or provider secrets are never profile metadata. Profile observability may expose only non-secret effective controls and compatibility identities.

## Failure semantics

Profile selection fails closed. Unsupported/partially enforced profiles are rejected before work is admitted to the stronger boundary. A failure does not retry under a weaker profile, switch from isolated to in-process compilation, accept unauthenticated native bytes, or reuse quarantined execution state.

## Alternatives

- **One universal "secure" profile:** rejected because it collapses independent trust assumptions and would overstate the delivered boundary.
- **Per-service host processes:** rejected because resident process count would scale with service count and violate the dormant-resource invariant.
- **Require a new external guest host before any Phase 3 work:** rejected because T0 work can continue under the documented in-process TCB, and T1 external-capsule support can follow its explicit prerequisites while T2 remains unavailable.
- **Treat compiler isolation as guest isolation:** rejected because compilation and execution occur in different processes and have different trusted components.

## Validation plan

Finite acceptance evidence is profile-specific:

- `local-experimental-v1`: existing activation isolation, budgets, cancellation, cleanup, cross-activation leakage, and Wasmtime conformance tests; evidence supports the T0 default and its documented Wasm execution barrier, not hardened external-capsule admission.
- `isolated-aot-compiler-v1`: existing sandbox prerequisite probes plus bounded timeout, cancellation, malformed I/O, crash, kill/reap, descriptor, filesystem/network, process/thread creation, and cleanup tests.
- `authenticated-native-aot-v1`: exact engine/config/security identity, tamper/rejection, currentness, cache miss/rebuild, image ownership, restart, and authenticated-load tests.
- `external-capsule-v1`: #280 startup/check-config and every-preparation-path fail-closed tests, using #278/#279 prerequisites and #238 integrated adversarial evidence.
- provider/renderer profiles: provider-specific malformed response, quota, cancellation, overload, secret-leak/cross-tenant, shutdown, and renderer containment evidence before support.
- `fixed-execution-host-v1`: process crash/kill/quarantine/reap, bounded host replacement, OS-enforced denial of supervisor memory/keys/descriptors, CPU/memory/process-tree/IPC limits under worker compromise, cross-activation/tenant leakage, stuck-work shutdown, and resource-accounting tests before any T2 claim.

Historical benchmark evidence remains historical. This decision does not require a new scale or performance campaign.

The delivered mechanisms have concrete, bounded test entry points:

| Mechanism | Executable evidence |
| --- | --- |
| Fresh stores, guest limits, cancellation and reuse | [generic backend](../crates/latent-wasmtime/tests/generic_backend.rs), [containment](../crates/latent-wasmtime/tests/containment_backend.rs), [lifecycle](../crates/latent-wasmtime/tests/lifecycle.rs) and host-accounting library tests |
| Isolated compilation and enforced OS facilities | [real compiler](../crates/latent-wasmtime/tests/isolated_aot.rs), [supervision](../crates/latent-wasmtime/tests/aot_supervisor.rs) and [sandbox probes](../crates/latent-wasmtime/tests/aot_sandbox.rs) |
| Authenticated native loading and independent currentness | [native cache/restart/tamper tests](../crates/latent-wasmtime/tests/native_aot_cache.rs), [admission](../crates/latent-wasmtime/tests/admission.rs) and AOT profile/seal/image ownership library tests |

The patched runtime/compiler baseline passed these suites and the bounded
real-node workflows in [PR #286's CI run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/34756145022).
That result supports the documented mechanisms, not an unimplemented profile.
Compiler/native-cache acceptance requires supported Linux x86-64 facilities;
Windows compilation alone is not an isolation result. See the
[baseline record](../docs/development/wasmtime-security-update.md) for the exact
dependency/advisory and platform limits. Subsequent profile expansions must add
their own finite negative/cleanup cases to #238 before stronger support claims.

## Open questions

None for the profile taxonomy. Concrete implementations may refine versioned profile identifiers through their owning tickets, but they must preserve the threat/boundary distinctions and fail-closed no-downgrade rule established here.
