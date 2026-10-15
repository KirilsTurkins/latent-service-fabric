# API surface map

This map distinguishes implemented APIs from declared architectural contracts.
The published alpha.5 baseline includes the accepted Phase 1–3 standalone
profiles; [the completion records](development/engineering-records.md) retain
their exact sources and scope. Development adds explicit transaction and
activation-runtime profiles with separate remaining acceptance gates. Use
[Changes since alpha.5](start/development-changes.md) for that distinction.
Generated bindings and schemas do not themselves implement a service, install a
provider or qualify a packaged distribution.

## Guest-facing WIT packages

| Package | Current status and intended purpose |
| --- | --- |
| `latent:context` | Implemented filtered activation identity, trace, deadline, metadata and remaining budget. |
| `latent:log` | Implemented budgeted structured logging. |
| `latent:clock` | Implemented monotonic and wall-clock interfaces. |
| `latent:random` | Implemented configured [OS cryptographic randomness](runtime/random.md) with per-call and shared activation limits. |
| `latent:blob` | Implemented configured Linux [local](runtime/local-blobs.md) and [S3](runtime/s3-blobs.md) immutable blobs at 0.2.0. |
| `latent:http` | Implemented configured [buffered](runtime/outbound-http.md) and [streaming](runtime/streaming-http.md) providers. |
| `latent:secrets` | Implemented configured [protected local references](runtime/local-secrets.md), rotation and opaque credentials, plus the [Vault KV-v2 provider](runtime/vault-secrets.md). |
| `latent:telemetry` | Implemented configured [custom metrics](runtime/custom-metrics.md) with exact labels, bounded aggregation and shared export. |
| `latent:service` | Implemented configured [local invocation](runtime/local-service-invocation.md) with conserved descendant budgets. |
| `latent:events` | Configured [immediate NATS JetStream publication](runtime/nats-events.md) and [bounded inbound triggers](runtime/nats-triggers.md). [Deferred JetStream delivery](development/deferred-jetstream.md) has its separate transaction/dispatch authority. |
| `latent:runtime/activation@0.1.0` | Explicit finite activation ownership/waits bridge under the V5 host profile; language runtime ports retain independent qualification. |
| `latent:network/streams@0.1.0` | Owned stream contract; [development TCP installation](reference/standalone-streams.md) is feature-gated and unavailable in ordinary builds. |
| `latent:state/key-value@0.2.0` | Implemented command/query state owners under the explicitly selected [Phase 4 host profile](protocol/transactions.md), not an ordinary stateless deployment. |
| `latent:intents/staging@0.1.0` | Implemented bounded intent staging in the same host-owned transaction; only the host can commit and independently authorized dispatch performs external work. |
| `latent:timer` | Declared; durable workflow timers are Phase 6. |
| `latent:platform/capsule` | Aggregate platform world; its declarations do not imply all imports are executable. |

`latent-component-bindings` generates Rust bindings for the aggregate runtime
world and maintained echo fixture into Cargo `OUT_DIR`. The executable echo
guest derives its canonical ABI exports from the same authoritative WIT.

The generic backend accepts components without imports and the four supported
[activation interfaces](runtime/capabilities.md): context, log, monotonic clock
and wall clock. Configured broker adapters add local service calls, outbound HTTP,
local/S3 blobs, local/Vault secrets and NATS publication through the [current host profile](runtime/host-abi-profile.md).
Uninstalled provider imports fail explicitly. Dynamic exports use the
[canonical WIT value protocol](protocol/wit-values.md). Every profile preserves
exact versioned ABI identity and actual host-profile compatibility when adding
providers; it cannot turn a declared import or caller-supplied grant into authority.

The separate [Phase 4 matrix](../wit/host-abi-phase4-v1.json) and
[transaction protocol](protocol/transactions.md) describe command/query and intent
imports. Generic V5 recognition does not install that runtime or turn a stateless
deployment into a transaction. The node must bind the exact signed companion,
namespace, state/result policies and protected storage owners.

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
| `AuditService` | Optional `QueryPhase2Audit` with typed scope, filters, records, cursors and loss coverage. |
| `RouteService` | Tenant-scoped GetRouteSnapshot. |
| `NodeService` | GetNode/ListNodes plus authorized bounded activation-tree and immutable target inspection; inspection confers no execution or mutation authority. |
| `ContractService` | Declared registry/comparison RPCs; compatibility is currently a Rust host API used by local control compilation. |
| `CapabilityService` | Configured broker inspection through ListCapabilities and ExplainCapabilityGrant, with current deployment/policy/provider checks and bounded shared counters. |
| `BindingService` | Standalone registry/graph RPCs remain declared. Actual deployment bindings are compiled by their current owner; provider-binding management uses PolicyService. |
| `TriggerService` | Implemented shared HTTP trigger apply/get/list/delete and original-operation recovery under exact publication/deployment pins and audited CAS. |
| `PolicyService` | Optional durable capability-policy/provider-binding apply/get/list/delete, original-operation recovery and descriptive evaluation. Supply-chain admission remains a separate authority. |
| `StateService` | Opt-in namespace inspection/mutation, entity selection and supported checked state/effect management on the installed Phase4Runtime; operation support remains explicit. |
| `TransactionService` | Opt-in InvokeCommand/Query, original LookupCommand/LookupCommit, GetEffect and CancelCommand through current caller-scoped authority and retained physical owners. `ListEffectHistory` is declared and wrapped but unsupported by this owner (`Unavailable`). |
| `DispatcherService` | Opt-in InspectDispatcher, ControlDispatcher and original operation lookup with current operator authority; inspection and pause/resume do not prove provider delivery. |

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
| `latent-contracts` | Typed contract descriptors and bounded `compare_descriptors` analysis; general `ContractRegistry` and `BindingCompiler` remain architectural interfaces. |
| `latent-manifest` | Bounded codecs, structural schemas, stateless semantic validation and explicit transaction manifest/profile validation. Schema acceptance is distinct from semantic/current-host validation. |
| `latent-control-store` | `DirectoryDeploymentRepository`, `DeploymentStore`, immutable route pins, scoped pages and combined catalog persistence. `deployment_operations` exposes sealed prepare/synchronous commit, exact receipt lookup/snapshot and `DeploymentReadLease`. `rollouts` owns plans, policies, target provenance and atomic cohort publication. |
| `latent-rollout` | `RolloutCoordinator`, `RolloutHandle`, one `RolloutWorker`, bounded tickets/control, response leases and explicit promote/rollback previews. `deployment_audit` shares exact receipt audit helpers without adding a deployment worker. |
| `latent-audit` | `AuditWorker`, `AuditHandle`, typed records, critical reservations/attempts, bounded query pages and retained response ownership. `BoundedPhase2AuditJournal` remains an explicit volatile embedding API. |
| `latent-telemetry` | Shared runtime/lifecycle observations, configured `CustomMetricRegistry` and sealed custom records, plus `BoundedPhase2CanaryOutcomeWindow`, `CanaryCapture`, snapshots, thresholds and affine `SealedCanaryWindow`. Diagnostic evaluation does not authorize promotion. |

[Lifecycle](reference/release-lifecycle.md) composes a sealed catalog capability
with optional real signing proof. The node binds runtime and deployment owners
to that exact catalog. A delegating custom repository cannot pair arbitrary
metadata with a genuine historical token: the historical snapshot is sealed.
A retained package source grants bounded access to exact original comparison
bytes, not a refreshed execution grant.

[Managed operations](phase-2-operator-workflows.md) retain compact receipts in
publication-aware catalog format 5, or 6/7 when bindings/HTTP route state are
present, alongside rollout history. Obsolete formats 1 through 4 are rejected;
there is no automatic compatibility reader. Exact replay precedes fresh state
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
| `latent-capabilities` | Sealed activation plans/sessions, policy/audit dispatch, affine I/O and shared provider pools. Configured service, HTTP, blob, secret, event, OS randomness and custom metric ports require exact current grants. |
| `latent-http` | `HttpProvider`, bounded destination/DNS/TLS/header configuration and buffered async HTTP; [profile and composition](runtime/outbound-http.md). |
| `latent-secrets` | `LocalSecretStore`, `LocalSecretProvider`, finite protected reloads, per-use raw read authorization and opaque provider credential bindings. |
| `latent-nats` | `NatsPublisher`, `NatsTriggers`, scoped TLS credentials, bounded publication and inbound scheduling, verified receipts and explicit uncertainty; [publisher](runtime/nats-events.md) and [trigger](runtime/nats-triggers.md) profiles. |
| `latent-vault` | `VaultSecretProvider`, exact KV-v2 references, bounded shared plaintext/cache owners and checked disclosure; [profile and composition](runtime/vault-secrets.md). |
| `latent-protected-files` | Shared bootstrap file policy and strict descriptor-anchored secret roots. |
| `latent-state` | Protected embedded storage, namespace/lifecycle authority, bounded fresh views and serializable command sessions under the installed native owner. |
| `latent-commit` | Host-owned complete atomic state/outbox/result envelopes, original command identity and durable recovery; no guest early-commit authority. |
| `latent-effects` | Retained effect rows, bounded claims/physical attempts, dispatch control and separately authorized provider reconciliation. |
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
future integrations: `latent-triggers`, `latent-ingress`,
`latent-workflows` and `latent-wrpc`. Concrete shared HTTP and NATS owners are
described above; those implementations do not complete every generic interface.
Identity/delegation interfaces do not
imply distributed identity is running. Current capability authority is provided
by `latent_capabilities::broker`, with bounded policy stores in
`latent_policy::capability` and supply-chain admission in
`latent_policy::supply_chain`. The earlier unused generic capability and policy
interfaces have been removed.

## Declarative schemas

[The schema index](../schemas/README.md) covers capsule/deployment/binding/policy/
trigger manifests and route snapshots; package formats, WIT locks and source
inputs; publisher/builder/SBOM evidence and trust policy; admission and lifecycle;
optional node audit/AOT/rollout/state settings; transaction companions and
preparation profiles; captured application dependencies/resources; canary policy;
and CLI evidence/registry profiles. `latent-manifest` embeds its manifest schemas and applies bounded
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
Development also exposes the explicit state/transaction groups described by
[transaction recovery](operations/transaction-recovery.md).
It performs one control RPC per command, keeps caller operation identities for
recovery and never retries a mutation automatically. New typed counters and
generations remain lossless decimal strings.

The Rust, Go, .NET, Java, TypeScript and C SDKs retain their invocation/guest
interfaces. All six request models expose optional activation/root/parent IDs
and cancellation/status by known activation ID. C cancellation uses a callback
with a separate transport-error channel. Their [contract fixtures](../sdk/README.md)
cover absence, lineage and in-flight ownership. All six native client transports
have maintained stateless workflows; Development additionally provides the
[six transaction facades](development/transaction-clients.md). Complete
management, real-node/browser and packaged matrices retain their own acceptance
requirements. Guest authoring SDKs are separate from these external clients.
