# API surface map

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

## Rust internal interfaces

| Crate | Primary seams |
|---|---|
| `latent-artifacts` | `ArtifactRepository`, `ArtifactCache`, `ArtifactVerifier` |
| `latent-contracts` | `ContractRegistry`, `CompatibilityChecker`, `BindingCompiler` |
| `latent-policy` | `PolicyEngine`, `PolicyRepository` |
| `latent-routing` | `RouteResolver`, `RouteCompiler`, snapshot source/publisher |
| `latent-admission` | `AdmissionController`, `QuotaProvider` |
| `latent-scheduler` | `ActivationScheduler`, `CellPool`, `ClusterPlacement` |
| `latent-activation` | `ActivationManager`, `ActivationJournal` |
| `latent-executor` | `ExecutionBackend`, backend registry and cancellation |
| `latent-wasmtime` | engine factory, AOT compiler/cache/validator |
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
| `latent-node` | node registration, inventory, route watch, directory |
| `latent-control-store` | desired-state persistence seams |
| `latent-telemetry` | telemetry sink and activation observer |
| `latent-audit` | audit store and publisher |
| `latent-testkit` | conformance suite and invariant probes |

## Declarative schemas

The JSON Schemas in `schemas/` define capsules, deployments, bindings, policies, triggers, and compiled route snapshots.

## Language SDKs

The Rust, Go, .NET, Java, TypeScript, and C directories define client and guest context surfaces only. Transport and code generation remain open implementation choices.
