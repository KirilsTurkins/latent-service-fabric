# ADR-0040: Run the closed Angular adapter in fresh generic Stores

## Status

Accepted; Phase 3 #233. Extends ADR-0006, ADR-0037 and ADR-0038. Supersedes
ADR-0037's pending async-adapter gate for the implemented operator-controlled
T0 profile. T1 qualification remains gated on #234 and #226.

## Context

ComponentizeJS 0.22.0 generates a synchronous component interface. The public
web contract is asynchronous, and a reusable guest instance retains JavaScript
globals, Angular transfer state and callback queues. Neither a separate native
executor nor manual application-state reset satisfies the selected ownership
model. The packaged JavaScript engine also exceeds ordinary capsule binary-work
limits even though its public WIT surface is small.

## Decision

Compose the fixed Rust async `latent:web/application@0.1.0` adapter with the
closed JavaScript engine at build time. Its synchronous internal interface is
an implementation detail inside the component. Only sealed context imports
reach the node. The adapter samples the host principal, lineage, trace and
deadline; request headers and cookies cannot supply that authority.

Run the final component in the ordinary Wasmtime backend, fixed preparation
workers, bounded shared caches and generic execution cells. Each render creates
a fresh Store, both guest memories and all JavaScript/Angular state. Fuel
yields and epoch interruption preserve progress on the shared async executor.
Destruction must finish before cell reuse and resource refunds. Compiled code
may remain cached; a dormant application owns no guest instance or event loop.

Require explicit node `rendererProfile: "angular-ssr-component-v1"` and capsule
`compatibility.renderer` with the exact installed profile digest. Preserve
existing omitted fields and the `wasm-web-buffered-v1` profile identity. Hash
the fixed adapter sources, private composition WIT, timer bridge, public WIT,
host ABI and selected bounds into the portable profile identity. Bind that
requirement through immutable package metadata and existing native target,
CPU, security and engine settings keys. It is compatibility metadata, not a
publisher proof, observed-build attestation or admission grant.

Before compilation or authenticated native loading, validate actual async
exports and the closed import surface. Only this explicit profile receives
the separate 8,000,000 binary-operator and 262,144 binary-type budgets. Ordinary
capsule and public WIT limits remain unchanged. Callers may lower the finite
binary and public budgets independently.

The composition has two memories sharing one aggregate 256 MiB ceiling, 32
core instances, four tables, 131,072 elements per table, 2 MiB Wasm stack and
4 MiB async stack. Capsule ceilings are at most 2,000,000,000 fuel and 5,000 ms.
The selected engine remains Wasmtime 47.0.4, on-demand, Cranelift speed. The node
opt-in configures the engine shape; it does not increase operator fuel, memory,
source, queue, cache or payload budgets. Grants may impose stricter limits.

Bound each private input frame to 256 KiB, result frame to 1 MiB and document
to 128 KiB. Guest timers are cumulative and nonrenewing: 256 zero-delay
callbacks and 4,096 explicit microtasks per Store. Positive timers and intervals
are rejected. Native Promise jobs also consume fuel and memory and remain
interruptible. A frame or document cap is not a promise that the CPU budget
can render every document of that size.

## Consequences

This installs the approved T0 profile. Reject an Angular opt-in under
`external-capsule-v1` until the actual observed Angular build and independently
authorized web deployment path are integrated and tested. Existing Rust/C
provenance recipes cannot honestly attest an Angular composition. #234 owns
that recipe; #226 owns projection from componentless web publication into
execution authority. A web receipt is never converted into a capsule grant by
copying digests. T2/T3 remain unsupported.

The maintained real-component gate covers fresh principal/cookies/hydration,
exceptions, resource/callback exhaustion, concurrent progress, cancellation,
success after failure, and the shared HTTP node's disconnect/revocation path.
CI runs it when renderer, runtime, node or validation inputs change and reuses
the workspace's compiled test harnesses. Generated Wasm and bulk evidence stay
outside Git. #239 owns representative release-build performance comparisons;
debug compilation times are not application latency claims.
