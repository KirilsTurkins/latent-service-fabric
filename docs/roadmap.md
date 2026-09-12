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
Phase 2 builds on that completed handoff under the scope below; local
catalog/build foundations remain Phase 1.

## Phase 2: packaging and supply chain — features delivered, gate pending

[Epic #139](https://github.com/KirilsTurkins/latent-service-fabric/issues/139)
and the [Phase 2 milestone](https://github.com/KirilsTurkins/latent-service-fabric/milestone/4)
track the package-to-execution and operator workflow. The following feature
surfaces are implemented. This documentation refresh is
[#157](https://github.com/KirilsTurkins/latent-service-fabric/issues/157);
[completion gate #158](https://github.com/KirilsTurkins/latent-service-fabric/issues/158)
remains pending. Feature delivery and individual test results do not substitute
for that collective acceptance review.

The [Phase 2 delivery notes](phase-2-delivery.md) summarize current features,
migration and recovery boundaries. They remain unreleased development notes.

| Delivered surface | Contract and scope |
| --- | --- |
| Package format and deterministic build/inspection (#140–141) | [Exact OCI package identity](protocol/package-format.md), capsule/browser/SSR package formats and [bounded packaging](component-development/packaging.md) from supplied bytes. Web formats do not implement a web runtime. |
| OCI distribution (#142) | [Scoped authenticated transfer](reference/oci-registry.md), exact immutable descriptors and bounded detached referrer discovery. |
| Publisher, builder and SBOM evidence (#143–145) | Separate [publisher trust](reference/publisher-trust.md) and [builder/source policy](reference/build-provenance.md), plus [observed inventory and SBOM associations](component-development/sbom.md). The maintained build remains nonhermetic. |
| Enforced admission and compatibility (#146–147) | [Current tenant/supply-chain admission](reference/package-admission.md), actual runtime requirements and [conservative exact-pair contract comparison](reference/release-compatibility.md). Transfer and diagnostic verification create no execution grant. |
| Durable release lifecycle (#148) | [Admission, revocation, retirement and evidence renewal](reference/release-lifecycle.md), owner-bound current capabilities, bounded operation outcomes and fail-closed recovery in local and enforced modes. |
| Replaceable raw cache (#149) | [Digest-verified file/buffer ownership](reference/raw-artifact-cache.md), bounded staging, pins and explicit reclamation. It cannot delete authoritative catalog content or confer trust. |
| Isolated compilation and native reuse (#150–151) | [Trusted-local Linux x86_64 producer and opt-in persistent loading](runtime/trusted-aot.md), protected local receipts, exact engine/source identity, child ownership through reap and page-rounded image permits. |
| Durable audit and observation (#152) | [Typed attempts, outcomes and diagnostics](phase-2-audit.md), one bounded worker, scoped queries, explicit loss/uncertainty and no per-invocation durable enqueue. |
| Rollout, canary and rollback (#153–155) | [Combined atomic catalog publication](phase-2-rollouts.md), [sealed full-window promotion](phase-2-canary-promotion.md) and [explicit original-base restoration](phase-2-rollback.md) through new monotonic generations. |
| Operator workflows (#156) | [Package build/inspect/verify/push/pull and authenticated control workflows](phase-2-operator-workflows.md), exact managed deployment receipts, finite reconciliation and lossless CLI output. |

The standalone node remains single-node and stateless. Supply-chain enforcement
requires explicit configuration; trusted-local mode retains real lifecycle checks without
inventing signing proof. Native reuse, durable audit and rollout management have
their own opt-in owners and limits. Native loading never turns cached bytes into
current permission.

Phase 2 extends the local deployment format through combined rollout state and
managed-operation history while retaining earlier decoding and omitted-field
semantics. Replay returns retained history; it never renews a grant, repeats an
evicted operation or restores a revoked release. Catalog durability, audit
acknowledgement and client outcome certainty remain distinct.

The retained Phase 0/1 measurements keep their original execution identities and
limitations. Phase 2 delivery makes no new 100k-scale, RSS, latency or production
SLO claim. Its gate must assess current evidence and documentation together.

## Phase 3: capabilities and application hosting

[Epic #201](https://github.com/KirilsTurkins/latent-service-fabric/issues/201)
defines the next capability-rich implementation phase. Issues #202–240
and the retained [Angular umbrella #44](https://github.com/KirilsTurkins/latent-service-fabric/issues/44)
are a concrete backlog, not claims of working providers. The context, logging and
clock surface already delivered in #10 remains the baseline.

The sequence starts with exact versioned contracts, durable grants and a sealed
broker. Shared I/O ownership, provider pools and descendant reservations then
support real external providers and isolated local service calls. Web ingress and
renderer work depend on those foundations and the existing package/lifecycle
boundary. SDK and operator work must exercise the actual implementations.

| Workstream | Planned capability and tickets |
| --- | --- |
| Exact authority and ABI | [Versioned capability ABI and host profiles #202](https://github.com/KirilsTurkins/latent-service-fabric/issues/202), [durable policies/grant revisions #203](https://github.com/KirilsTurkins/latent-service-fabric/issues/203), [sealed activation broker and handles #204](https://github.com/KirilsTurkins/latent-service-fabric/issues/204). |
| Shared resources and bindings | [Asynchronous I/O and stream ownership #205](https://github.com/KirilsTurkins/latent-service-fabric/issues/205), [provider pools/configuration epochs/shutdown #206](https://github.com/KirilsTurkins/latent-service-fabric/issues/206), [exact host and isolated-local bindings #207](https://github.com/KirilsTurkins/latent-service-fabric/issues/207). |
| Child calls and diagnostics | [Conserved descendant budgets/cancellation #208](https://github.com/KirilsTurkins/latent-service-fabric/issues/208), [broker-authorized local service calls #209](https://github.com/KirilsTurkins/latent-service-fabric/issues/209), [capability audit and resource visibility #210](https://github.com/KirilsTurkins/latent-service-fabric/issues/210). |
| Outbound HTTP | [Policy-scoped DNS/TLS/HTTP #211](https://github.com/KirilsTurkins/latent-service-fabric/issues/211) and [streaming bodies/backpressure #212](https://github.com/KirilsTurkins/latent-service-fabric/issues/212). |
| Immutable blobs | [Durable bounded local storage #213](https://github.com/KirilsTurkins/latent-service-fabric/issues/213) and [authenticated S3-compatible provider #214](https://github.com/KirilsTurkins/latent-service-fabric/issues/214). |
| Secrets | [Protected local references and atomic rotation #215](https://github.com/KirilsTurkins/latent-service-fabric/issues/215) and [bounded Vault KV-v2 provider #216](https://github.com/KirilsTurkins/latent-service-fabric/issues/216). |
| Events | [Real NATS JetStream publication #217](https://github.com/KirilsTurkins/latent-service-fabric/issues/217) and [external consumer triggers through shared scheduling #218](https://github.com/KirilsTurkins/latent-service-fabric/issues/218). This does not supply a transactional guest outbox. |
| Guest utilities | [Budgeted cryptographic randomness #219](https://github.com/KirilsTurkins/latent-service-fabric/issues/219) and [custom metrics with cardinality policy #220](https://github.com/KirilsTurkins/latent-service-fabric/issues/220). |
| HTTP application routing | [Request/response contracts #222](https://github.com/KirilsTurkins/latent-service-fabric/issues/222), [atomic scoped trigger routes #223](https://github.com/KirilsTurkins/latent-service-fabric/issues/223), [shared authenticated ingress #229](https://github.com/KirilsTurkins/latent-service-fabric/issues/229). |
| Browser storage and responses | [Exact renderer/asset release admission #225](https://github.com/KirilsTurkins/latent-service-fabric/issues/225), [immutable asset serving #231](https://github.com/KirilsTurkins/latent-service-fabric/issues/231), [safe HTTP response-cache policy #232](https://github.com/KirilsTurkins/latent-service-fabric/issues/232). |
| Angular SSR and hydration | [Execution-profile proof #224](https://github.com/KirilsTurkins/latent-service-fabric/issues/224), [bounded renderer cells #233](https://github.com/KirilsTurkins/latent-service-fabric/issues/233), [deterministic renderer/hydration packaging #234](https://github.com/KirilsTurkins/latent-service-fabric/issues/234), [browser isolation #235](https://github.com/KirilsTurkins/latent-service-fabric/issues/235), [real-browser reference workflow #236](https://github.com/KirilsTurkins/latent-service-fabric/issues/236), under [#44](https://github.com/KirilsTurkins/latent-service-fabric/issues/44). |
| SDKs and executable examples | [Typed guest bindings and Rust/C examples #221](https://github.com/KirilsTurkins/latent-service-fabric/issues/221), [six-SDK parity #227](https://github.com/KirilsTurkins/latent-service-fabric/issues/227), [real Rust transport #228](https://github.com/KirilsTurkins/latent-service-fabric/issues/228), [bounded TypeScript/browser client #230](https://github.com/KirilsTurkins/latent-service-fabric/issues/230). |
| Operators and completion evidence | [Policy/provider/web management #226](https://github.com/KirilsTurkins/latent-service-fabric/issues/226), [runbooks #237](https://github.com/KirilsTurkins/latent-service-fabric/issues/237), [adversarial isolation #238](https://github.com/KirilsTurkins/latent-service-fabric/issues/238), [resource/preparation measurements #239](https://github.com/KirilsTurkins/latent-service-fabric/issues/239), [collective gate #240](https://github.com/KirilsTurkins/latent-service-fabric/issues/240). |

Every provider must preserve exact tenant/grant/owner identity and fail closed
across revocation and configuration changes. Buffers, handles, connections,
streams, waits and descendants need finite shared reservations that survive
cancellation until actual cleanup. Provider responses and secret values cannot
escape into unrestricted logs or audit payloads. Pools, ingress listeners and
consumer loops belong to the node, not dormant services.

Angular support requires a selected and measured renderer profile; it does not
assume that the current generic Wasm backend can execute arbitrary Node.js
applications. Browser and SSR package schemas already exist in Phase 2, while
actual HTTP serving, renderer execution and hydration integration remain Phase 3
work. No application-owned listener or idle renderer is introduced by a package.

## Phase 4: state and effects

Transactional keyed state, optimistic concurrency, durable outbox, effect
dispatcher, idempotency and entity-key routing. Phase 3 external HTTP/event
operations do not claim an atomic guest-state transaction or exactly-once effects.

## Phase 5: cluster

Separate control plane, route watches, direct node invocation, mTLS identity,
artifact prefetch, state affinity and multi-zone placement. Phase 3 service calls
are isolated local calls; they do not establish distributed routing or remote
delegation.

## Phase 6: durable workflows

Explicit workflow state machines, durable timers, continuations, awaited effects,
replay and compensation. Ordinary provider deadlines, retries or consumer cursors
do not supply workflow suspension or replay.

## Phase 7: research promotion candidates

User-space state paging, continuation eviction, call-graph fusion, immutable
shared blobs, adaptive materialization, native software fault isolation and
hardware capability backends. These remain research candidates rather than
requirements of the Phase 2 or Phase 3 completion gates.
