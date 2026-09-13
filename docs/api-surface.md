# API surface map

This map distinguishes implemented APIs from declared architectural contracts.
Phase 1 and its performance extension are complete. The
[Phase 2 completion review](phase-2-completion.md) records its accepted delivery
scope and evidence. Generated bindings and schemas do not themselves implement a
service. [The roadmap](roadmap.md) maps Phase 3's concrete capability, provider,
web and SDK work without claiming it has shipped.

## Guest-facing WIT packages

| Package | Current status and intended purpose |
| --- | --- |
| `latent:context` | Implemented filtered activation identity, trace, deadline, metadata and remaining budget. |
| `latent:log` | Implemented budgeted structured logging. |
| `latent:clock` | Implemented monotonic and wall-clock interfaces. |
| `latent:random` | Declared; budgeted cryptographic randomness is Phase 3. |
| `latent:blob` | Declared; bounded local/S3 immutable values and staged transfer are Phase 3. |
| `latent:http` | Declared; policy-scoped outbound HTTP and streaming are Phase 3. |
| `latent:secrets` | Declared; protected local/Vault references and rotation are Phase 3. |
| `latent:telemetry` | Declared; guest custom metrics with cardinality policy are Phase 3. |
| `latent:service` | Declared; broker-authorized isolated local invocation and descendant budgets are Phase 3. |
| `latent:events` | Declared; real provider publication is Phase 3, while transactional durable event intents require Phase 4. |
| `latent:state` | Declared; transactional keyed state is Phase 4. |
| `latent:timer` | Declared; durable workflow timers are Phase 6. |
| `latent:platform/capsule` | Aggregate platform world; its declarations do not imply all imports are executable. |

`latent-component-bindings` generates Rust bindings for the aggregate runtime
world and maintained echo fixture into Cargo `OUT_DIR`. The executable echo
guest derives its canonical ABI exports from the same authoritative WIT.

The generic backend accepts components without imports and the four supported
[activation interfaces](runtime/capabilities.md): context, log, monotonic clock
and wall clock. Other imports fail explicitly. Dynamic exports use the
[canonical WIT value protocol](protocol/wit-values.md). Phase 3 must preserve
exact versioned ABI identity and actual host-profile compatibility when adding
providers; it cannot turn a declared import or caller-supplied grant into authority.

## Protobuf services

`latent-rpc` generates messages, Tonic clients/server wrappers and an embedded
descriptor set from the checked-in Protobuf. It opens no listener. The
[standalone node](reference/standalone-node.md) composes implementations through
one bounded authenticated loopback listener on Linux.

| Service | Implemented standalone surface |
| --- | --- |
| `InvocationService` | Invoke, Cancel and GetActivation through the local activation owner. |
| `ReleaseService` | Publish/Get/List, lifecycle status, retained operation lookup, revoke/retire and detached evidence renewal. Package publication uses independent current node admission. |
| `DeploymentService` | Apply/Get/List/Delete, optional managed operation IDs and exact object/state preconditions, coherent operation snapshots and GetDeploymentOperation. |
| `RolloutService` | Optional audited Start/Change/Evaluate/Get/List/GetOperation; Change includes manual stages, pause/resume/abort, sealed canary promotion and explicit rollback. |
| `AuditService` | Optional QueryPhase2Audit with typed scope/filter/cursor/coverage and a limited legacy QueryAudit projection. |
| `RouteService` | Tenant-scoped GetRouteSnapshot. |
| `NodeService` | GetNode and ListNodes for the configured node's bounded inventory. |
| `ContractService` | Declared registry/comparison RPCs; compatibility is currently a Rust host API used by local control compilation. |
| `CapabilityService` | Declared provider discovery and grant explanation; concrete Phase 3 work. |
| `BindingService` | Declared binding management and graph validation; concrete Phase 3 work. |
| `TriggerService` | Declared shared ingress trigger management; concrete Phase 3 work. |
| `PolicyService` | Declared policy management/explanation; supply-chain policy is currently explicit node/host configuration. |

WatchDeployment, WatchRouteSnapshots, RegisterNode, ReportInventory and Heartbeat
return explicit `Unimplemented`; they do not fabricate streams or cluster state.
Omitted optional owners also return explicit unsupported behavior after the
applicable authentication and validation. Managed deployment requests require
their audit composition and never silently downgrade to legacy writes.
See [management services](reference/management-services.md),
[invocation](protocol/invocation-service.md) and the retained
[Phase 1 contract](protocol/phase-1-contract-hardening.md).

Tenant and actor come from trusted authentication, not DTO claims. Missing and
foreign tenant-scoped objects share absence behavior. Node-level inventory and
audit need the trusted node-operator claim; it grants no cross-tenant access.

## Package and control Rust APIs

| Crate | Delivered seams and authority boundary |
| --- | --- |
| `latent-artifacts` | `ArtifactRepository`, `DirectoryArtifactRepository`, sealed preparation/verified metadata, `ReleaseUseEligibility`, `LifecycleAuthorityHandle`, historical execution snapshots and retained package sources. Managed publication, lifecycle and evidence methods retain bounded outcomes; historical metadata grants no execution. |
| `latent-artifacts::package` | Exact package, evidence, publisher-signature and builder-provenance formats and bounded associations. |
| `latent-artifacts` raw cache | `RawArtifactCache`, typed keys, affine write/read/reclaim owners, pins, `RawArtifactBytes`, limits and actual snapshots. Cached bytes are replaceable and authority-free. |
| `latent-packaging` | `build_package`, `inspect_bundle`, bounded directory/evidence I/O, SBOM generation/inspection, `compare_packages`, `PackageComparisonLimits`, sealed checked surfaces and exact-pair breaking allowances. Builds supplied bytes without executing guest/build scripts. |
| `latent-oci` | `HttpOciRegistry`, scoped registry configuration/credentials, `OciPulledPackage` leases and optional shared raw-cache integration. Transfer success is not admission. |
| `latent-policy::supply_chain` | `SupplyChainAuthority`, explicit policy/clock configuration, durable floors and current admission grants; `verify_package_once` returns a diagnostic report without durable floors or execution authority. |
| `latent-contracts` | Typed contract descriptors and conservative `CompatibilityChecker`; general `ContractRegistry` and `BindingCompiler` remain architectural interfaces. |
| `latent-manifest` | Bounded `JsonManifestCodec`, structural schemas, `Phase1ManifestValidator` and runtime requirement models. Schema acceptance is distinct from semantic/current-host validation. |
| `latent-control-store` | `DirectoryDeploymentRepository`, `DeploymentStore`, immutable route pins, scoped pages and combined catalog persistence. `deployment_operations` exposes sealed prepare/synchronous commit, exact receipt lookup/snapshot and `DeploymentReadLease`. `rollouts` owns plans, policies, target provenance and atomic cohort publication. |
| `latent-rollout` | `RolloutCoordinator`, `RolloutHandle`, one `RolloutWorker`, bounded tickets/control, response leases and explicit promote/rollback previews. `deployment_audit` shares exact receipt audit helpers without adding a deployment worker. |
| `latent-audit` | `AuditWorker`, `AuditHandle`, typed records, critical reservations/attempts, bounded query pages and retained response ownership. `BoundedPhase2AuditJournal` remains an explicit volatile embedding API. |
| `latent-telemetry` | Shared runtime/lifecycle observations plus `BoundedPhase2CanaryOutcomeWindow`, `CanaryCapture`, snapshots, thresholds and affine `SealedCanaryWindow`. Diagnostic evaluation does not authorize promotion. |

[Lifecycle](reference/release-lifecycle.md) composes a sealed catalog capability
with optional real signing proof. The node binds runtime and deployment owners
to that exact catalog. A delegating custom repository cannot pair arbitrary
metadata with a genuine historical token: the historical snapshot is sealed.
A retained package source grants bounded access to exact original comparison
bytes, not a refreshed execution grant.

[Managed operations](phase-2-operator-workflows.md) retain compact receipts in
catalog format 4 alongside rollout history. Exact replay precedes fresh state
checks; finite retention and mandatory original state preconditions prevent an
evicted create from executing again after delete. Leased snapshots and receipt
queries are coherent reads. Catalog commit, durability and audit outcome are
separate facts.

## Runtime and node APIs

| Crate | Delivered runtime seams |
| --- | --- |
| `latent-core` | IDs, errors, lifecycle models, `ActivationClock`, budgets, reservations and terminal consumption. |
| `latent-rpc` / `latent-component-bindings` | Generated control transport and shared Component Model bindings. |
| `latent-routing` | `RouteResolver`, route compiler and immutable snapshot source/publisher contracts used by local routing. |
| `latent-admission` | `LocalAdmissionController`, `LocalQuotaProvider`, affine admission/execution permits and their public interfaces. |
| `latent-scheduler` | `FixedCellPool`, `LocalScheduler`, nonqueueing acquisition/change notifications, cell lifecycle, fair bounded queues and scoped cancellation. |
| `latent-activation` | Bounded activation request construction, activation ID source, manager and journal contracts. |
| `latent-executor` | Repository-backed preparation/readiness, `PreparedReadiness`, affine `PreparedUse`, materialization, backend registry and cancellation. |
| `latent-wasmtime` | Generic component factory/backend, bounded value/host policy, fresh stores, cleanup proof and prepared-cache ownership. Opt-in `IsolatedAotCompiler`, `TrustedAotOutput`, `NativeAotSettings`, `NativeImageLimits`, `with_catalog_and_aot` and aggregate native usage. |
| `latent-node` | `LocalActivationManager`, immediate-ID handles, scoped cancel/status, bounded journal, transport cleanup interruption and inventory seams. |
| `latent-wire` | Invocation/management adapters, trusted principal/trace boundaries, finite request conversion and response services. Audit, deployment and rollout response leases remain attached through body/frame ownership. |
| `latent-testkit` | Deterministic async/process/resource helpers and invariant/conformance probes. |

Repository preparation returns the pinned runtime and its declared imports
together. Its sealed source binds verified identity and cold fetch to one owner;
generic repository fallbacks perform verified fetching rather than claiming a
directory identity. Scheduling consumes admitted permits only after readiness;
each activation still creates fresh guest state.

The [native loader](runtime/trusted-aot.md) authenticates persisted receipts and
exact immutable bytes before its private copying load. There is no public
arbitrary-byte restoration or native-load constructor. Both local and enforced
catalogs retain independent lifecycle/admission checks. Standalone
[`isolatedAot`](reference/standalone-node.md#optional-isolated-aot-compilation)
is opt-in, adds no RPC/distributed compiler service, and leaves the default
portable compilation path available as explicit configuration.

`latentd::config::{NodeConfig, NodeSettings}` and
`latentd::standalone::StandaloneNode` provide validated composition.
`latentd serve --config PATH` owns fixed runtimes and shutdown. Opaque
`NodeSettings` is derived from mutable configuration before opening resources;
embedders use read-only worker/shutdown accessors for outer runtimes. Audit,
rollout, native-cache and canary owners must match the configured catalogs and
clock. Omitting rollout configuration still permits bounded historical catalog
recovery while disabling rollout RPCs. An initialized durable audit owner cannot
silently downgrade to volatile or absent audit on reopen.

The following crates still contain primarily architectural interfaces for
future integrations: `latent-capabilities`, `latent-blobs`, `latent-triggers`,
`latent-ingress`, `latent-state`, `latent-commit`, `latent-effects`,
`latent-workflows` and `latent-wrpc`. Identity/delegation and generic
`PolicyEngine`/`PolicyRepository` traits likewise do not imply distributed
identity or general provider policy management is running.

## Declarative schemas

[The schema index](../schemas/README.md) covers capsule/deployment/binding/policy/
trigger manifests and route snapshots; package formats, WIT locks and source
inputs; publisher/builder/SBOM evidence and trust policy; admission and lifecycle;
optional node audit/AOT/rollout settings; canary policy; and CLI evidence/registry
profiles. `latent-manifest` embeds its manifest schemas and applies bounded
structure checks plus separate semantic validation.

Canonical stored records and protobuf JSON projections have distinct contracts.
For example, lifecycle records use stored scope and integer fields, while the
API projection uses symbolic enums and decimal-string `uint64`. Closed schemas,
duplicate-key rejection, finite decoding and exact associations remain required.
Schema success neither grants permission nor proves durability, and no schema
adds a JSON management listener.

## CLI and language SDKs

The [operator CLI](reference/operator-cli.md) exposes local package
build/inspect/verify, scoped OCI push/pull, release evidence/lifecycle and
operation lookup, legacy or managed deployment writes, coherent operation reads,
rollout/canary/rollback, audit queries and retained invocation/route/node calls.
It performs one control RPC per command, keeps caller operation identities for
recovery and never retries a mutation automatically. New typed counters and
generations remain lossless decimal strings.

The Rust, Go, .NET, Java, TypeScript and C SDKs retain their invocation/guest
interfaces. All six request models expose optional activation/root/parent IDs
and cancellation/status by known activation ID. C cancellation uses a callback
with a separate transport-error channel. Their [contract fixtures](../sdk/README.md)
cover absence, lineage and in-flight ownership. Phase 2 does not claim complete
management/provider transports in all six languages. Phase 3 adds typed guest
bindings, cross-language parity and actual Rust/TypeScript transport workflows.
