# API surface map

This map includes implemented APIs and architectural contracts. The current
implementation status is summarized in [the roadmap](roadmap.md). Generated
bindings and declared traits do not by themselves provide running services.

## Guest-facing WIT packages

| Package | Purpose |
|---|---|
| `latent:context` | Identity, trace, deadline, metadata, and remaining budget |
| `latent:log` | Budgeted structured logging |
| `latent:clock` | Monotonic and wall clocks |
| `latent:random` | Budgeted random values |
| `latent:blob` | Large immutable and staged binary values |
| `latent:state` | Transactional keyed state |
| `latent:events` | Durable event publication intents |
| `latent:http` | Policy-scoped outbound HTTP |
| `latent:secrets` | Scoped secret reads |
| `latent:timer` | Durable timer scheduling |
| `latent:telemetry` | Custom budgeted metrics |
| `latent:service` | Component-to-component invocation |
| `latent:platform/capsule` | Aggregate platform world |

Rust bindings for the aggregate runtime world and maintained echo fixture are generated into Cargo `OUT_DIR` by `latent-component-bindings`. The executable echo guest generates its canonical ABI exports in the final component crate from the same authoritative WIT.

The generic Wasmtime backend supports components with no imports and four
[activation capabilities](runtime/capabilities.md): filtered context, budgeted
structured logging, and monotonic/wall clocks. The other capability packages
describe later-phase surfaces. Dynamic exported value mapping follows the
[canonical WIT value protocol](protocol/wit-values.md).

## Protobuf services

| Service | Purpose |
|---|---|
| `ReleaseService` | Publish, inspect, and list release metadata |
| `ContractService` | Inspect contracts and compare compatibility |
| `CapabilityService` | Discover providers and explain grants |
| `AuditService` | Query administrative and security audit events |
| `DeploymentService` | Apply, inspect, list, delete, and watch deployments |
| `BindingService` | Apply bindings and validate binding graphs |
| `TriggerService` | Manage shared ingress triggers |
| `PolicyService` | Manage and explain policy decisions |
| `NodeService` | Register nodes and report inventory/health |
| `RouteService` | Retrieve and watch immutable route snapshots |
| `InvocationService` | Generic invocation, cancellation, and activation status |

`latent-rpc` generates Rust messages, Tonic clients, Tonic server traits/wrappers, and an embedded descriptor set for every checked-in Protobuf file. It contains no listener or service implementation.

Phase 1's standalone subset and the methods that report explicit
unsupported/unimplemented behavior are defined in
[Phase 1 contract hardening](protocol/phase-1-contract-hardening.md).
[Invocation adapters](protocol/invocation-service.md) (#12) implement Invoke,
Cancel, and GetActivation through the local manager.
[Management adapters](reference/management-services.md) (#37) implement release,
versioned deployment, tenant-scoped route and operator inventory methods.
The [standalone node](reference/standalone-node.md) (#14) serves these adapters
through one bounded, authenticated loopback listener on Linux.

## Rust internal interfaces

| Crate | Primary seams |
|---|---|
| `latent-core` | IDs/errors/lifecycle models, `ActivationClock`, `ActivationBudget`, `EffectiveActivationBudget`, reservations and terminal consumption |
| `latent-manifest` | `ManifestCodec`, `ManifestValidator`, bounded `JsonManifestCodec`, `Phase1ManifestValidator` |
| `latent-rpc` | generated Protobuf messages, Tonic clients/servers, descriptor set |
| `latent-component-bindings` | shared generated runtime/echo Component Model bindings |
| `latent-artifacts` | `ArtifactRepository`, `DirectoryArtifactRepository`, sealed `VerifiedArtifactMetadata` and `ArtifactPreparationSource`/`OwnedArtifactPreparationSource`, bounded preparation reads, compact `ArtifactPreparationIdentity`, `ArtifactVerificationSnapshot`, `ArtifactCache`, `ArtifactVerifier` |
| `latent-contracts` | `ContractRegistry`, `CompatibilityChecker`, `BindingCompiler` |
| `latent-policy` | `PolicyEngine`, `PolicyRepository` |
| `latent-routing` | `RouteResolver`, `RouteCompiler`, snapshot source/publisher |
| `latent-admission` | `AdmissionController`, `QuotaProvider`, `LocalAdmissionController`, `LocalQuotaProvider`, affine admission/execution permits |
| `latent-scheduler` | open `CellPool` with nonqueueing acquisition/change notifications, affine `CellLease`/`CellLeaseLifecycle`, `FixedCellPool`, `LocalScheduler`, `AdmittedSchedulingRequest`, `ScheduledActivation`, `SchedulerSnapshot`, `SchedulingCancellation`, `LocalNodePlacement` |
| `latent-activation` | `ActivationRequest`, bounded `ActivationRequestBuilder`, `ActivationIdSource`, `ActivationManager`, `ActivationJournal` |
| `latent-executor` | `ExecutionBackend::prepare_ready_from_repository`/`materialize_ready`, compatible `prepare_from_repository`, `PreparedActivation`, `PreparedReadiness`, affine `PreparedUse`, backend registry and cancellation |
| `latent-wasmtime` | `WasmtimeComponentEngineFactory`, generic `WasmtimeBackend`, bounded preparation/value policy, `WasmtimeHostServices`, `ContextExposurePolicy`, `StructuredLogSink`, dynamic exports and cleanup proof; `IsolatedAotCompiler`, `ValidatedAotProfile` and affine `TrustedAotOutput`; retained Phase 0 facade |
| `latent-capabilities` | provider, broker, registry, handle model |
| `latent-blobs` | large-value storage, leases, and transfer |
| `latent-identity` | authentication, authorization, delegation, node identity |
| `latent-triggers` | trigger sources, cursors, mapping, and dispatch |
| `latent-ingress` | shared protocol adapters and ingress routing |
| `latent-commit` | atomic state/effect commit and recovery |
| `latent-state` | state backend and entity lease manager |
| `latent-effects` | effect store, dispatcher, and provider |
| `latent-workflows` | continuation store and workflow runtime |
| `latent-wire` | Generated `InvocationServiceAdapter`, `LocalInvocationRuntime`, bounded `ActivationCleanupOwner`/`ActivationCleanupHandle` and `ActivationCleanupSnapshot`, `ManagementServiceAdapter`, scoped principal/trace services and lossless converters; codec, duplex channel, request multiplexer seams |
| `latent-wrpc` | remote client/server and connection factory |
| `latent-node` | `LocalActivationManager`, immediate-ID `ActivationHandle` with trusted `interrupt_for_cleanup`/`ActivationTransportInterruption`, `ActivationReceipt`, scoped status/cancel, bounded `LocalActivationJournal`; retained Phase 0/budget adapters and node registration/inventory/watch seams |
| `latent-control-store` | `DeploymentStore` versioned mutations, committed receipts and bounded tenant/service pages; `DirectoryDeploymentRepository` implements persistence, route compilation/publication, and resolution |
| `latent-telemetry` | `TelemetryRuntime`, bounded `TelemetryHandle`, `StructuredLocalSink`, typed payload-free `ActivationObserver`, `SharedActivationObserver`, and borrowed `GuestLogObserver` |
| `latent-audit` | audit store and publisher |
| `latent-testkit` | conformance suite, deterministic async/process/resource utilities, invariant probes |

The [local scheduler](scheduling.md) consumes admission permits and returns an
affine cell/quota assignment. Its cooperative enqueue futures use the caller's
runtime and the activation owner's cancellation state. The
[local activation manager](activation-lifecycle.md) composes those owners with
catalog pinning, preparation, execution, and bounded terminal publication.
Repository-backed preparation returns the pinned runtime and its declared
imports together. The directory repository's sealed source binds verified
snapshot identity and cold fetch to one concrete owner; custom repositories
default to fully verified fetching. The [runtime contract](runtime/wasmtime.md)
describes cache compatibility, fresh activation state, and the retained direct
artifact preparation API.
`latentd::config::{NodeConfig, NodeSettings}` and
`latentd::standalone::StandaloneNode` provide validated single-node composition;
`latentd serve --config PATH` owns its fixed runtimes and command lifecycle.
`NodeSettings` is opaque: embedders configure `NodeConfig` before deriving a plan
and use read-only worker-count/shutdown accessors to construct outer runtimes.

[Shared telemetry](telemetry.md) observes that existing lifecycle owner directly.
`StandaloneInventoryReporter` implements bounded node snapshots from configured
classes and shared resource sources, including explicit unavailable observations.

## Declarative schemas

The JSON Schemas in `schemas/` define capsules, deployments, bindings, policies, triggers, and compiled route snapshots.

The seventh schema defines locally trusted release-publication requests.
`latent-manifest` embeds the five manifest schemas and applies bounded
structural validation plus separate Phase 1 semantic rules; see the
[manifest codec contract](protocol/manifest-codec.md).

## Language SDKs

The Rust, Go, .NET, Java, TypeScript, and C directories define client and guest context surfaces. Transport-facing generated Rust is owned centrally by `latent-rpc`; cross-language transport generation remains a later implementation choice.

All six invocation request models expose optional caller activation/root/parent
identity and cancellation/status by known activation ID. C cancellation uses a
callback with a separate transport-error channel. The [SDK contract](../sdk/README.md)
documents absence and lineage rules, callback ownership, compatibility, and
the executable fake-client checks for operations before invocation completion.
