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

The retained Phase 0 echo backend implements its context/log imports. Generic
context/log hardening and clock binding remain Phase 1 #10 work; the other
capability packages describe later-phase surfaces.

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

Phase 1's planned standalone subset and the methods that must report explicit
unsupported/unimplemented behavior are defined in
[Phase 1 contract hardening](protocol/phase-1-contract-hardening.md).
Invocation adapters (#12), management adapters (#37), and listener composition
(#14) remain pending on the integration branch.

## Rust internal interfaces

| Crate | Primary seams |
|---|---|
| `latent-core` | IDs/errors/lifecycle models, `ActivationBudget`, `EffectiveActivationBudget`, reservations and terminal consumption |
| `latent-manifest` | `ManifestCodec`, `ManifestValidator`, bounded `JsonManifestCodec`, `Phase1ManifestValidator` |
| `latent-rpc` | generated Protobuf messages, Tonic clients/servers, descriptor set |
| `latent-component-bindings` | shared generated runtime/echo Component Model bindings |
| `latent-artifacts` | `ArtifactRepository`, `DirectoryArtifactRepository`, `ArtifactCache`, `ArtifactVerifier` |
| `latent-contracts` | `ContractRegistry`, `CompatibilityChecker`, `BindingCompiler` |
| `latent-policy` | `PolicyEngine`, `PolicyRepository` |
| `latent-routing` | `RouteResolver`, `RouteCompiler`, snapshot source/publisher |
| `latent-admission` | `AdmissionController`, `QuotaProvider`, `LocalAdmissionController`, `LocalQuotaProvider`, affine admission/execution permits |
| `latent-scheduler` | open `CellPool`, affine `CellLease`/`CellLeaseLifecycle`, `FixedCellPool`, `CellPoolSnapshot`, `ActivationScheduler`, `ClusterPlacement` |
| `latent-activation` | `ActivationManager`, `ActivationJournal` |
| `latent-executor` | `ExecutionBackend`, backend registry and cancellation |
| `latent-wasmtime` | engine factory, AOT compiler/cache/validator, shared echo host bindings |
| `latent-capabilities` | provider, broker, registry, handle model |
| `latent-blobs` | large-value storage, leases, and transfer |
| `latent-identity` | authentication, authorization, delegation, node identity |
| `latent-triggers` | trigger sources, cursors, mapping, and dispatch |
| `latent-ingress` | shared protocol adapters and ingress routing |
| `latent-commit` | atomic state/effect commit and recovery |
| `latent-state` | state backend and entity lease manager |
| `latent-effects` | effect store, dispatcher, and provider |
| `latent-workflows` | continuation store and workflow runtime |
| `latent-wire` | codec, duplex channel, request multiplexer |
| `latent-wrpc` | remote client/server and connection factory |
| `latent-node` | node registration/inventory/watch seams; `Phase0ActivationRunner`, `BudgetedActivationManager`, budget and cancellation registries |
| `latent-control-store` | desired-state persistence seams; `DirectoryDeploymentRepository` implements local deployment storage, route compilation/publication, and resolution |
| `latent-telemetry` | telemetry sink and activation observer |
| `latent-audit` | audit store and publisher |
| `latent-testkit` | conformance suite, deterministic async/process/resource utilities, invariant probes |

## Declarative schemas

The JSON Schemas in `schemas/` define capsules, deployments, bindings, policies, triggers, and compiled route snapshots.

The seventh schema defines locally trusted release-publication requests.
`latent-manifest` embeds the five manifest schemas and applies bounded
structural validation plus separate Phase 1 semantic rules; see the
[manifest codec contract](protocol/manifest-codec.md).

## Language SDKs

The Rust, Go, .NET, Java, TypeScript, and C directories define client and guest context surfaces. Transport-facing generated Rust is owned centrally by `latent-rpc`; cross-language transport generation remains a later implementation choice.
