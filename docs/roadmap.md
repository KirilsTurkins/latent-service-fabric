# Engineering roadmap

## Phase 0: executable spike — Phase 1 authorized

Repository contracts, one Rust echo capsule, one fixed cell pool, Wasmtime
component loading, timeout/trap containment, baseline measurements, native
Linux calibration, hot-path profiling, and a long-running resource soak are
implemented. Fresh native-Linux calibration, profiling, and soak packages from
commit `52ac4754…` were independently rebuilt from their raw evidence and bound
to a fresh full baseline at `b932a935…`. The retained August 30
[receipt](../benchmarks/phase0/receipts/native-linux-2026-08-30-b932a935/gate-summary.json)
records `pass`, `authorized`, and no blockers. See
[the completion gate](phase-0-completion.md).

The underlying measurements remain single-host observational evidence. Neither
an issue closure nor such an observation alone authorizes Phase 1. The full
receipt authorizes only because it validates the matched raw archives,
execution identity, profiling, resource soak, and fresh-baseline checks
together. Phase 1 builds on the retained runtime and invariants; Phase 0 does
not claim production readiness or Phase 1 API compatibility.

## Phase 1: single-node stateless fabric — complete

The following features and their acceptance evidence are delivered:

- [Executable build and generated bindings](development/build-foundation.md) (#2) and [cross-layer contracts](protocol/phase-1-contract-hardening.md) (#36).
- [Manifest codecs and schema-backed validation](protocol/manifest-codec.md) (#3).
- [Durable local release catalog](development/local-release-catalog.md) (#4).
- [Embedded deployment catalog and immutable local routing](deployment-routing.md) (#5).
- [Resource budgets, deadlines, and cancellation primitives](runtime/resource-budgets.md) (#6).
- [Bounded single-node admission and overload control](admission-control.md) (#7).
- [Fixed class pools and bounded tenant-fair scheduling](scheduling.md) (#8).
- [Generic Wasmtime execution and bounded canonical values](runtime/wasmtime.md) (#9).
- [Activation context, structured logging, and clock capabilities](runtime/capabilities.md) (#10).
- [Stateless activation lifecycle, bounded journal/status, and scoped cancellation](activation-lifecycle.md) (#11).
- [Shared telemetry, redacted lifecycle/guest observations, and bounded node inventory](telemetry.md) (#13).
- [Generic invocation, cancellation, and retained-status service adapters](protocol/invocation-service.md) (#12).
- [Release, deployment, route, and node management service adapters](reference/management-services.md) (#37).
- [Configured standalone Linux node, loopback RPCs, durable restart and bounded shutdown](reference/standalone-node.md) (#14).
- [Bounded developer/operator CLI and scriptable local echo workflow](reference/operator-cli.md) (#15).
- [Bounded deterministic conformance, child resource observations and diagnostic report validation](testing/phase-1-conformance.md), with [retained clean CI evidence](../benchmarks/phase1/conformance/2026-09-08-ci93-aee91e5/README.md).
- [Explicit scale, mixed-workload soak and benchmark collectors](testing/phase-1-measurements.md), with [all four scales, three full soaks and seven benchmark runs retained](../benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/REPORT.md).
- [Seven controlled historical/current pairs](../benchmarks/phase1/paired/2026-09-08-container-linux-e7e06f7/REPORT.md) with the original executables, semantic controls, productionization differences and complete raw evidence (#94).
- [SDK caller identity and cancellation contracts](../sdk/README.md) with executable fixtures across six languages (#65).

The [completion review](phase-1-completion.md) maps the collective evidence to
all fifteen [gate #16](https://github.com/KirilsTurkins/latent-service-fabric/issues/16)
criteria and records the completion decision and merged CI evidence for the
[Phase 1 epic](https://github.com/KirilsTurkins/latent-service-fabric/issues/1).
Status is recorded as of September 8, 2026. The standalone node and operator CLI
support the local release-to-invocation workflow through generated RPC clients;
see the [scriptable quickstart](development/standalone-quickstart.md).

At 100,000 releases/deployments, service-specific execution resources remain
absent and fixed node topology remains constant, while catalog metadata RSS
grows explicitly. Reclamation satisfies the declared finite policy; paired
measurements report additional current runtime overhead. Delivery does not mean
constant RSS, arbitrary-duration leak freedom, a production SLO or a claim of
no performance regression. The retained Phase 0 demonstration and historical
native receipts keep their original scope. Clustering, general capabilities,
state/effects and workflows remain the later phases below.

The completed [Phase 1 performance extension](phase-1-extension-completion.md)
records the merged prioritized optimizations and Docker/Kubernetes
comparisons, separately from the original functional completion decision.
Resident Echo met its 2 ms useful-success target in #103; distinct 100k
catalog RSS fell 58.90% in #107. These results do not establish a universal
latency SLO, all-shape memory ceiling or isolated orchestration cost.
The handoff proceeds to Phase 2 packaging and supply-chain feature delivery
under the scope below; local catalog/build foundations remain Phase 1.

## Phase 2: packaging and supply chain

Implementation is tracked by [epic #139](https://github.com/KirilsTurkins/latent-service-fabric/issues/139)
and the [Phase 2 milestone](https://github.com/KirilsTurkins/latent-service-fabric/milestone/4).
The [package identity and artifact-format foundation](protocol/package-format.md)
defines bounded capsule, browser-asset and SSR-package contracts. It does not
itself establish publisher trust. [Deterministic packaging and inspection](component-development/packaging.md)
now validate supplied components against pinned WIT sources and typed metadata.
The [registry adapter](reference/oci-registry.md) provides scoped authenticated
transfers and bounded referrer discovery. Cryptographic verification and trusted
admission follow next.

OCI push/pull, signatures, provenance, SBOM, trusted AOT cache, release rollout
orchestration, canary, and rollback. Atomic local deployment/snapshot publication
and deterministic weighted selection are already Phase 1 routing foundations.

## Phase 3: capabilities

Capability broker, policy grants, HTTP, blob, secrets, events, provider pooling, auditing, and descendant budgets.

Shared application HTTP ingress and bounded hosting profiles, including
[Angular SSR and hydration](https://github.com/KirilsTurkins/latent-service-fabric/issues/44),
belong here. Phase 1 context, clocks, budget access, and structured logging are
already implemented; application-owned listeners and idle execution resources
remain outside the resource model.

## Phase 4: state and effects

Transactional keyed state, optimistic concurrency, durable outbox, effect dispatcher, idempotency, and entity-key routing.

## Phase 5: cluster

Separate control plane, route watches, direct node invocation, mTLS identity, artifact prefetch, state affinity, and multi-zone placement.

## Phase 6: durable workflows

Explicit workflow state machines, timers, continuations, awaited effects, replay, and compensation.

## Phase 7: research promotion candidates

User-space state paging, continuation eviction, call-graph fusion, immutable shared blobs, adaptive materialization, native software fault isolation, and hardware capability backends.
