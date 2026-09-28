# Phase 1 completion report

**Phase 1 status: COMPLETE — September 8, 2026.**

> Current status: [Phase 2](phase-2-completion.md) is also complete. The scope and
> measurements below remain the original Phase 1 evidence; current features and
> planned Phase 3 work are mapped in the [roadmap](roadmap.md).

The single-node stateless features are implemented. The full scale, soak and
benchmark suite passed and is retained with its exact executed binary and raw
measurements. Clean CI also passed the selected deterministic conformance
profile. Seven controlled historical/current pairs also passed, with both actual
executables and all original reports retained. This document maps the collective
evidence to [gate #16](https://github.com/KirilsTurkins/latent-service-fabric/issues/16)
and the [Phase 1 epic](https://github.com/KirilsTurkins/latent-service-fabric/issues/1).

The delivered engineering scope is the configured single-node stateless fabric,
with the measured limits below. The completion decision and integration evidence
are recorded at the end of this report; they do not require
relabeling an individual collector's deliberately incomplete gate field.
The full, paired, clean CI and separate-filesystem receipts are retained.
The August [Phase 0 authorization](phase-0-completion.md) and its raw evidence
retain their original scope and identity.

The later [Phase 1 performance extension](phase-1-extension-completion.md)
records separate optimization and infrastructure comparisons. It does not
replace this September 8 functional completion decision or its evidence.

## Implemented surface and limits

| Feature | Current behavior and boundary |
| --- | --- |
| [Build and contracts](development/build-foundation.md) | Pinned toolchain, generated bindings, versioned protobuf/WIT/JSON contracts and [strict manifest validation](protocol/manifest-codec.md). |
| [Release catalog](development/local-release-catalog.md) | Immutable content-digest identity, durable initialization/publication, bounded index, verified completion records and metadata integrity, scoped metadata reads and pagination. RPC publication requires an explicit authenticated tenant; tenant-neutral trusted-local records are omitted from scoped reads. |
| [Deployments and routing](deployment-routing.md) | Durable atomic publication, deterministic revisions and immutable route snapshots; per-object generation preconditions, receipts and scoped indexed pagination. Changed catalog generations expire page tokens. Caller preconditions are checked at the commit boundary. |
| [Budgets and admission](runtime/resource-budgets.md) | One admitted accounting ledger for CPU fuel, memory, accepted log bytes and monotonic wall/deadline limits. [Admission](admission-control.md) reserves bounded capacity for running and queued work. Later-phase budget dimensions are rejected. Persistent relative ceilings remain relative policy across restart and wall-clock passage. |
| [Scheduling](scheduling.md) | Fixed pools for up to five configured classes; bounded tenant queues, priority/deadline ordering within a tenant, aging and tenant fairness. Cancellation, expiry, handoff and shutdown release or conservatively quarantine owned cells. |
| [Wasmtime execution](runtime/wasmtime.md) | Generic Component Model dispatch, bounded preparation cache and a fresh store per activation. The [canonical value codec](protocol/wit-values.md) supports Phase 1 scalar/composite values with lossless integer/float framing; unsupported resources, futures, streams and async surfaces fail explicitly. |
| [Capabilities](runtime/capabilities.md) | Activation context, structured logs, wall and monotonic clocks use current identity and accounting. No ambient WASI filesystem, environment, process or network authority is installed. Metadata/claim/baggage disclosure and log redaction follow explicit policy. |
| [Activation lifecycle](activation-lifecycle.md) | Caller-chosen or server-assigned identity is available before completion; an owner pins the route, manages cancellation and final accounting, and publishes bounded terminal status. Status/cancel are tenant scoped. Lineage is opaque correlation, not authority or retained-ancestor validation. |
| [Telemetry and inventory](telemetry.md) | Shared bounded observation pipeline, redacted guest/lifecycle records, fixed metric labels and bounded inventory sources. Readiness distinguishes unavailable/stale pressure and a closed scheduler. Fixed topology and service-resident resources are reported separately; unavailable OS measurements are not invented. |
| [Invocation RPC](protocol/invocation-service.md) | Generic Invoke/Cancel/GetActivation with bounded conversion, authenticated context, original deadlines, distinct guest success/domain error/platform failure and public diagnostic redaction. A terminal failure before route resolution can carry the canonical absent revision pin. |
| [Management RPC](reference/management-services.md) | Bounded release transfer; release/deployment get/list/paging and mutation; route/node inspection. Unsupported cluster methods return explicit unsupported status. Digest and tenant identity remain consistent across publication and inspection. |
| [Standalone node](reference/standalone-node.md) | Linux local catalogs and a plaintext gRPC listener restricted to literal loopback addresses, configured bearer credentials, bounded connections/RPC/control jobs and owned graceful shutdown. At most 64 cells and 1,024 combined cells/queue slots; default component limit 16 MiB, configurable to 64 MiB; payload ceiling at most 1 MiB. Fixed worker/helper counts do not grow with deployed services. |
| [Operator CLI](reference/operator-cli.md) | Local validation and generated-client publication, deployment, invocation, cancellation, status, routes and node inspection. Inputs are validated before connecting; returned data is checked for scope and request association. [The quickstart](development/standalone-quickstart.md) uses separate caller/node directories and publishes bytes over RPC. No automatic invocation retry is implied. |
| [SDK contracts](../sdk/README.md) | Six language fixtures cover optional invocation identity, lineage, preterminal status/cancel and asynchronous cancellation results. These are executable API-contract fixtures using fake clients, not implementations or proof of six network transports. |
| [Testkit and evidence](testing/phase-1-conformance.md) | Reusable real-manager/backend harnesses, fixed deterministic cases, bounded process ownership/probes and strict evidence validation. Separate [measurement collectors](testing/phase-1-measurements.md) implement explicit scale, soak and benchmark jobs with versioned raw, aggregate and comparison schemas. |

This composition has no cluster controller or separate execution-host process.
OCI trust/distribution, general outbound/state/blob/secrets capabilities,
transactional effects, clustered placement/routing and durable workflows remain
future phases. Single-host measurements do not establish a production SLO,
arbitrary-duration fairness, or safety for every future deployment configuration.

## Acceptance map

The fifteen rows preserve #16's acceptance scope. “Demonstrated” means the named
evidence and owning tests establish the stated bounded behavior; it does not
promise unmeasured behavior. Case names refer to the fixed
[conformance manifest](../benchmarks/phase1/cases.json). Existing owner suites
remain necessary alongside the selected profile.

| # | Acceptance criterion | Evidence and current disposition |
| --- | --- | --- |
| 1 | Clean-checkout echo release-to-invocation CLI workflow over RPC | Demonstrated by the [CLI workflow](../apps/latent/tests/standalone_cli/workflow.rs), [standalone node integration](../apps/latentd/tests/standalone_node.rs) and [scriptable quickstart](development/standalone-quickstart.md). Publication sends component bytes through RPC. |
| 2 | Dormant registrations at 100/1,000/10,000/100,000; fixed node topology, zero service-specific execution-resource growth | Demonstrated by the [full retained scale report](../benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/REPORT.md#dormant-catalogs-at-four-scales) and [actual scale collector](../apps/latentd/src/standalone/measurements/scale.rs). Catalog RSS growth is explicitly reported. |
| 3 | Reclamation after mixed success/error/trap/timeout/cancel/malformed/memory workloads; bounded resources and warmed RSS | Demonstrated within the fixed finite policy by [three full soaks](../benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/REPORT.md#three-mixed-workload-reclamation-runs), [idle-owner checks](../apps/latentd/src/standalone/measurements/soak/idle.rs) and [lifecycle drop/deadline tests](../crates/latent-node/tests/activation_lifecycle/deadline_abort.rs). General kernel timer registrations are not enumerated; owned timer/drop/helper behavior is tested separately. |
| 4 | Fault containment and healthy/concurrent recovery | Demonstrated by `mixed-outcomes`, `healthy-recovery`, `tenant-isolation`, [Wasmtime containment](../crates/latent-wasmtime/tests/generic_backend/containment.rs) and [lifecycle cleanup](../crates/latent-node/tests/activation_lifecycle/cleanup.rs). |
| 5 | No previous input/output/context/metadata/trace/log/clock/budget/guest-memory state exposed on cell reuse | Demonstrated by `fresh-store`, `capability-context`, `adapter-rpc-parity`, [fresh-store dispatch tests](../crates/latent-wasmtime/tests/generic_backend/dispatch.rs) and capability [context](../crates/latent-wasmtime/tests/capabilities_backend/context.rs), [clock](../crates/latent-wasmtime/tests/capabilities_backend/clocks.rs) and [telemetry](../crates/latent-wasmtime/tests/capabilities_backend/telemetry.rs) tests. Calls identify the reused cell; this is not an arbitrary host-memory scan. |
| 6 | Same service identifier isolated across tenants through catalog/route/invoke/status/telemetry/management | Demonstrated by `tenant-isolation`, same-service echo/capabilities telemetry pairs, [scoped routes](../crates/latent-control-store/src/deployments/tests/scoped_routes.rs) and management [release](../crates/latent-wire/tests/management_service/release/authorization.rs)/[deployment](../crates/latent-wire/tests/management_service/deployment/authorization.rs) authorization tests. |
| 7 | In-flight route pinning, new-call snapshot switching and stable unchanged revision after restart | Demonstrated by `route-update`, [the concurrent policy case](../apps/latent/tests/phase1_conformance/cases/concurrency/route.rs), [lifecycle identity](../crates/latent-node/tests/activation_lifecycle/identity.rs) and [versioned persistence tests](../crates/latent-control-store/src/deployments/tests/versioned/persistence.rs). |
| 8 | Queue bounds, fairness, overload, cancellation dispositions and every Phase 1 budget dimension | Demonstrated by `queue-admission`, cancellation/deadline/fuel/memory/log cases, [scheduler acceptance tests](../crates/latent-scheduler/tests/fair_scheduler.rs) and [scoped pending-status/cancel tests](../crates/latent-wire/tests/invocation_service/lifecycle.rs). The queue witness requires the other tenant to finish while two uncancelled spin owners remain running; expiry cannot satisfy it. |
| 9 | Persistent relative ceilings remain valid after wall passage and intersect caller deadlines | Demonstrated by `persistent-wall-ceiling` and [its observations](../apps/latent/tests/phase1_conformance/cases/wall/observe.rs): node age exceeds five seconds, persisted deployment age exceeds one second, and a caller deadline wins when earlier. Stored relative policy remains unchanged. The node case measures the composed transport/admission ceiling. |
| 10 | Direct-adapter/RPC outcome, structured-error, context, deadline, budget, trace and accounting equivalence | Demonstrated by [eight outcome pairs](../apps/latentd/src/standalone/parity/cases.rs) and [three capability pairs](../apps/latentd/src/standalone/parity/capabilities.rs) through one real manager/backend and one reused cell. Each receipt/status/span/log is bound to its own identity and consumption; distinct clock/trace values are not erased to manufacture equality. |
| 11 | Management bounds/pagination/unsupported cluster methods and no shared caller/node filesystem | Management behavior is demonstrated by [release](../crates/latent-wire/tests/management_service/release/pagination.rs), [deployment](../crates/latent-wire/tests/management_service/deployment/pagination.rs) and [inspection](../crates/latent-wire/tests/management_service/inspection.rs) tests plus CLI workflows. The [separate-mount-namespace receipt](../benchmarks/phase1/conformance/2026-09-08-namespace-proof/README.md) passed and is retained unchanged. |
| 12 | Required deterministic CI, failure artifacts and explicit heavy jobs/schemas | Implemented by [contracts validation](../tools/validate_contracts.sh), [required CI](../.github/workflows/ci.yml), [explicit measurement workflow](../.github/workflows/phase1-measurements.yml) and [measurement documentation](testing/phase-1-measurements.md). PR #93's [retained clean receipts](../benchmarks/phase1/conformance/2026-09-08-ci93-aee91e5/README.md) passed replay; PR #95 also passed all six checks and independent artifact replay. |
| 13 | Completion report with environment/configuration/topology, measures, Phase 0 comparison and raw links | Delivered by this review, the [full measurement report](../benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/REPORT.md), [controlled paired report](../benchmarks/phase1/paired/2026-09-08-container-linux-e7e06f7/REPORT.md), retained raw archives and replay tools. Startup and other unmatched boundaries remain explicitly identified rather than fabricated. |
| 14 | Retained Phase 0 regression paths isolated from product dispatch | Demonstrated by the explicit [Phase 0 adapter](../crates/latent-wasmtime/src/phase0.rs), generic backend tests and [opaque product payload test](../crates/latent-node/tests/activation_lifecycle/outcomes.rs). Historical CLI/JSON and containment conventions are not generic product dispatch rules. |
| 15 | Roadmap completion only after all criteria and dependencies | All functional dependencies, including #94, are merged and closed. This report supplies the remaining documentation criterion and records the collective acceptance decision in [the roadmap](roadmap.md). Gate #16 and epic #1 record the final integration and closure. |

The audit's small correctness follow-ups are also implemented: SDK identity and
cancellation (#65); artifact root durability and metadata integrity (#66/#68);
deployment generations/pagination (#67); relative deployment root anchoring
(#73); explicit catalog lock release with cloned descriptors (#82); and
under-capacity dispatch contention (#90). Their deterministic owner tests remain
part of normal validation; another scale run is not a substitute for them.

Timer ownership is supported by concrete owners and tests, without claiming a
kernel-wide timer census. The [lifecycle control future](../crates/latent-node/src/activation_manager/control.rs)
owns one active-stage sleep, and the bounded scheduler's
[wait registration](../crates/latent-scheduler/src/local/mod.rs) owns its deadline
sleep. [Transport destruction tests](../apps/latentd/src/standalone/transport/tests/ownership.rs)
keep request/body/control-job capacity until the actual future is destroyed;
[telemetry shutdown tests](../crates/latent-telemetry/src/pipeline/tests.rs) check
timeout aborts and dropped shutdown futures. The single
[load-sampling interval](../apps/latentd/src/standalone/load.rs) has an owned
stop/join path and abort fallback. [Wasmtime factory tests](../crates/latent-wasmtime/src/factory/tests.rs)
verify explicit epoch-helper join, repeated Drop, and continued helper ownership
when a backend survives a busy shutdown. Full-run shutdown receipts corroborate
these paths; OS timer registrations remain an unenumerated quantity.

## Clean deterministic CI evidence

[PR #93's CI run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/34221947356)
passed all six checks. Its synthetic tested merge source is
`aee91e53432e4cbb070ee3f2d2d882b1853fe179`, tree
`f717a2f31c4bf4d0bebe0ae1079874d171307b4c`, with `source_dirty=false`.
The final repository merge `0bffa4abf6238bd8b9989fb2bf39f17c1c53f5bc` is recorded
separately and is not substituted for the executed CI identity.

| Selected CI run | Result | Attempted Invokes | Counted commands | Recorded duration |
| --- | --- | ---: | ---: | ---: |
| Deterministic `run-_kg8prun` | 19/19 required cases passed | 54 | 151 | 24.846 s |
| Measurement smoke: scale | passed | 0 | 38 | 0.170910701 s |
| Measurement smoke: soak | passed | 24 | 57 | 2.534501862 s |
| Measurement smoke: benchmark | passed | 85 | 225 | 5.958540920 s |

The deterministic profile partitions into 22 adapter attempts/44 commands and
32 process attempts/107 commands. Its global cap remains 64 attempted Invokes
and 256 commands, including rejected and malformed calls. Existing owner suites
and the separately bounded measurement smoke run are outside that cap.

Independent replay checked the source identity, current Cargo lock digest, all
19 case associations, raw measurement statistics, schemas and process/data
cleanup receipts. All measurement summaries report clean shutdown. CI's binary
and fixture hashes are bound within its receipts; the downloaded CI artifacts
did not supply the collector executable for an independent local binary rehash.
The full measurement package below separately retains its executed ELF.

The CI environment is Linux x86_64, kernel `6.17.0-1022-azure`, AMD EPYC 7763 with
four visible logical CPUs and Microsoft virtualization, Rust/Cargo 1.97.1 and
Wasmtime 47.0.3. Smoke and deterministic reports intentionally retain
`phase1_completion: incomplete`; their small populations are not full resource
calibration or historical performance deltas.

The [durable CI package](../benchmarks/phase1/conformance/2026-09-08-ci93-aee91e5/README.md)
preserves both original artifact directories and their internal paths:
`phase-1-bounded-conformance-aee91e53432e4cbb070ee3f2d2d882b1853fe179/run-_kg8prun`
and `phase-1-measurement-smoke-aee91e53432e4cbb070ee3f2d2d882b1853fe179/smoke-rkqwlynh`.
The 413,399-byte `conformance.json` has SHA-256
`8001a15308df62db12cd49b7e2dc967ab5f5aae8ae5610ed932a37f722d40cd5`.
The 151,508-byte smoke `aggregate.json` has SHA-256
`cd099860a3a7ca34a0e04236fa9eb76e7d8afe24ae0ff0777eae9a5517852663`.
Its [file manifest](../benchmarks/phase1/conformance/2026-09-08-ci93-aee91e5/files.manifest.json)
binds all 312 downloaded files plus the original independent review. Semantic
validation, aggregate replay and all 152 raw-row schemas passed again from the
retained copies without execution. Git attributes preserve their exact bytes.

## Full measurements retained

The [full measurement report](../benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/REPORT.md)
contains all per-run tables, exact configurations and limitations. The clean
measured source is `d72c99b6f3320572ed318226304f1039cf7c4b80`, tree
`d5df7561de3c2c194e212d18e5a6092c7ed190c0`. This release-built collector composes
the actual node in an Intel i7-11850H Linux/WSL2 container with a four-CPU quota;
its process observations include fixed libtest/client overhead. This identity
is distinct from both CI and the historical native Ryzen reference.

At 100, 1,000, 10,000 and 100,000 releases/deployments, fixed topology remains one
process, six tasks/threads, 19 descriptors, seven socket descriptors referring
to five unique sockets, one listener and no descendants. Both cells remain idle,
with zero prepared entries and stores created. Catalog RSS grows from
13,762,560 bytes empty to 2,326,077,440 bytes at 100,000. Direct resolver medians
are 1,776 / 2,845 / 5,348 / 12,720.5 ns, each from 10,000 samples. Zero
service-specific execution growth does not imply constant catalog RSS.

Each of three soaks includes 1,000 warmup and 100,000 measured mixed calls.
Maximum idle RSS growth above each own warm baseline is 417,792 / 106,496 /
212,992 bytes, below the unchanged 67,108,864-byte policy allowance; descriptor
growth is zero against allowance two. Transient owners return to zero at sampled
idle checkpoints. Journal and telemetry retention remain within configured
count/byte bounds. These finite observations do not prove arbitrary-duration
leak freedom or enumerate general OS timers.

Each of seven independent benchmark processes attempts 8,440 Invokes, with
40 warmup calls and 400 samples per repeated boundary. Median-of-run-medians:
warm RPC 1,541 us, backend total 172 us, guest call 67.5 us and resource reclamation
28 us; initial preparation 32,762 us, cache-reset preparation 31,406.5 us and cache
hit 58 us. All outliers and fault/recovery populations remain retained. These
boundaries cannot be added or interchanged: guest call includes safe canonical
post-return, and individually named cleanup timers omit some result framing.

All eleven processes passed, totaling 362,080 attempted Invokes and 939,916
commands. Each has clean shutdown, zero transient owners, telemetry flush,
epoch-helper join and verified parent reaping/output/data cleanup. The
[50,544,383-byte archive](../benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/raw-evidence.tar.gz)
retains every original evidence file, including the 197,010,104-byte executed
ELF and three component fixtures. Its manifest and checksum are linked in the
report. Safe extraction and aggregate/comparison replay passed without rerunning
the workloads.

## Filesystem separation and controlled comparison

The separate-filesystem workflow passed one real echo Invoke in 25.569 seconds
for the entire proof. Client and node mount namespace IDs are `4026532293` and
`4026533068`; the node has no mounted caller directories. The unique caller
package path is absent from the node before RPC publication and after
invocation. RPC deployment/status/inspection/deletion succeed, retained status
is `completed`, and shutdown reports zero transient owners with a joined epoch
helper and flushed telemetry. This establishes the namespace boundary that
merely deleting caller files after publication would not establish.

The [durable namespace package](../benchmarks/phase1/conformance/2026-09-08-namespace-proof/README.md)
retains the original `latent.cli.namespace-proof.v1` receipt log and proof script
with byte hashes, including recorded CLI/node/component/input identities and
cleanup results. The original UTF-16 log is unchanged. Its one-call/debug-binary
provenance remains distinct from the release-built full measurement suite. The
receipt has no source commit/tree field, so this review adds no source identity
or clean-checkout claim for that separate proof.

The retained
[general comparison](../benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/comparison.json)
correctly reports 189 `not_comparable` observations and no causal deltas against
the unchanged August reference. Host, ABI/fixture, grant and timing-boundary
differences prevent treating those observations as equivalent measurements.

The separate [controlled #94 report](../benchmarks/phase1/paired/2026-09-08-container-linux-e7e06f7/REPORT.md)
passed seven independent pairs: 14 processes and 6,160 successful semantic Echo
calls, including 40 leading warmup and 400 measured calls per process. It uses
the actual clean historical `52ac47542a05c0a1263f78a14c04a5c2e6b761f3` runtime and
clean current `e7e06f7d568617d0d54c9cc77c268d7bb034c035` standalone node on the same
observed Linux container host. Shared maintained guest logic, semantic input,
fuel/memory/wall/log grants and the release recipe are bound; each arm retains
its own ABI-compatible component and exact executable.

Historical/current medians of process medians are 103/176 us for backend total,
21/27 us for actual activation-resource reclamation and 31,597/34,710 us for
initial preparation. Median within-pair differences are respectively +75, +7
and +833 us; these are paired statistics, not subtractions of aggregate medians.
Backend total is higher in all seven pairs. The wider invocation entrypoints
differ: historical prepared-envelope execution versus current persistent
loopback RPC. Their 135/1,459 us medians and +1,330.5 us median paired difference
describe the broader product path, not isolated transport or scheduler cost.

Both arms consume 3,062 fuel and 1,179,648 peak guest-memory bytes per call.
Current structured log accounting charges 330 bytes versus the historical 115,
reflecting different complete-record representations. All calls use fresh
stores and settle owned resources; all 14 processes exit and are reaped. Actual
process observations are four threads/no listener for the historical collector
and six threads/one listener for the current node with its collector. Different
diagnostic retention and probe/serialization work preclude an isolated runtime
RSS-saving claim. Startup exclusions remain unmatched, and cleanup fragments
are not summed into an invented equivalent interval.

The [paired archive](../benchmarks/phase1/paired/2026-09-08-container-linux-e7e06f7/raw-evidence.tar.gz)
retains 168 files, including both executed binaries, components, source proofs,
all arm reports and parent cleanup receipts. Its bounded extraction, hashes and
semantic replay passed. The [method](testing/phase-1-controlled-comparison.md)
keeps every measured call and alternates process order. These descriptive
productionization observations establish neither statistical significance nor
an SLO or isolated causal cost. They do not rewrite the August native reference.

## Completion decision and integration evidence

The collective evidence satisfies all fifteen Phase 1 gate criteria within the
documented stateless scope. Functional dependencies are merged into
`development` and closed, including the audit corrections and the controlled
comparison. This report and the updated roadmap supply the final documentation
criteria. [Gate #16](https://github.com/KirilsTurkins/latent-service-fabric/issues/16)
and [epic #1](https://github.com/KirilsTurkins/latent-service-fabric/issues/1)
record the final report PR, CI, merge and dependency reconciliation.

The final functional [PR #95](https://github.com/KirilsTurkins/latent-service-fabric/pull/95)
merged as `ff10ccd746951681d1e71d493ec82a1f8200b896` after all six checks passed:
[main CI](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/34229271704)
and [runtime regression](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/34229271702).
Its clean tested synthetic merge is `a8a5fcdab26e6d1605195e37853d9f5b0acf02f4`,
tree `5f9399d3bd20f8128c1d9ba5cea6cbbb14d24204`, identical to the PR head's tree.
Independent downloaded-artifact replay passed: 19 conformance cases, 54 Invokes,
148 commands and 17.867 seconds, plus all three measurement smoke collectors
(0/24/85 Invokes). Schemas, all 152 raw measurement rows, source/lock identity,
downloaded Echo bytes and cleanup receipts passed verification. The downloaded
CI artifacts did not include the collector executable; the full and paired
archives separately retain their exact executed binaries.

The individual bounded, measurement and paired reports retain
`phase1_completion: incomplete` because no one profile alone decides the
collective gate. Their original bytes and measured source identities remain
unchanged by this completion decision.

Earlier dated audit notes and measurement-report observations preserve what was
known when collected. The retained full and paired reports and this acceptance
map provide their September 8 resolution. Unsupported future phases and
unmeasured quantities remain explicit. Issue closure and a clean working tree
do not replace the raw evidence and reviewed acceptance decision.
