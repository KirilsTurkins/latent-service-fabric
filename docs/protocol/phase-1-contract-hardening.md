# Phase 1 contract hardening

Issue [#36](https://github.com/KirilsTurkins/latent-service-fabric/issues/36)
defines the pre-stabilization contract changes that every Phase 1 implementation
must consume. This document is normative for the affected Rust models,
Protobuf APIs, JSON schemas, WIT packages, and SDK surfaces.

## Budget and deadline semantics

`ResourceBudget` is a set of hard ceilings. Every numeric value is an exact
limit, so `0` means that no amount of that resource is granted; it never means
"use a platform default." This avoids an omitted/zero ambiguity across a
request, deployment, and node policy.

`wallTimeLimitMillis` / `wall_time_limit_millis` is the one optional member:

| Value | Meaning |
| --- | --- |
| absent / `None` | This layer supplies no wall-time constraint. |
| `0` | The activation receives no wall time. |
| positive value | A relative maximum measured from admission. |

Persistent capsule, deployment, and node documents must use only this relative
field. `wallDeadlineUnixMillis` is not valid in a schema and Protobuf field
number 3 is reserved so it cannot be repurposed. A caller's absolute deadline
appears only on `InvokeRequest.deadline_unix_millis` and
`ActivationEnvelope.deadline_unix_millis`.

At admission, the granted resource counters are the element-wise minimum of
the request, deployment, and node ceilings. The effective absolute deadline is
the earliest of the caller deadline and each configured relative limit measured
from that admission time:

```text
min(caller_absolute_deadline,
    admission_time + request.wall_time_limit,
    admission_time + deployment.wall_time_limit,
    admission_time + node.wall_time_limit)
```

Missing values are omitted from the minimum. Arithmetic saturates only at the
maximum representable Unix millisecond value, never to a shorter accidental
deadline.

## Cross-layer representation audit

| Concept | Rust/domain | Protobuf | JSON Schema | WIT | SDKs |
| --- | --- | --- | --- | --- | --- |
| Resource ceilings | `ResourceBudget` | both `ResourceBudget` messages | capsule/deployment limits | context `resource-budget` | Rust, Go, TypeScript, .NET, Java, C `ResourceBudget` |
| Caller deadline | `ActivationEnvelope.deadline_unix_millis` | `InvokeRequest.deadline_unix_millis` | not persistent | context deadline | invocation options / guest context |
| Platform detail | `Vec<ErrorDetail>` | repeated `detail_items` | not a declarative resource | `list<error-detail>` | typed list/array, never a flattened map |
| Terminal outcome | `ActivationOutcome` / `ActivationStatus` | invocation/status oneofs | not a declarative resource | `invocation-outcome` | `InvocationOutcome` and retained status unions |
| Route identity | `InvocationTarget` / tenant fields on routes | tenant fields on service/binding routes | required route tenant fields | tenant option on direct service target | generic target always carries tenant |
| Local upload | `CapsuleArtifact` seam | `CapsuleArtifactUpload` | `ReleasePublish.artifact` | not guest-visible | management transport is deferred to #37 |

The one intentional target difference is WIT direct service invocation:
`target.tenant = none` means the current invocation principal's tenant. The
generic external invocation API always requires a tenant. A supplied different
WIT tenant requires a future explicit grant; Phase 1 must deny it rather than
silently cross a tenant boundary.

## Invocation, errors, and status

An invocation has exactly one wire-visible terminal result:

- `success`: a guest completed successfully;
- `declared_error`: a guest/domain result; or
- `platform_failure`: infrastructure rejected, interrupted, or failed it.

Each result includes finalized `BudgetConsumption`. A platform error carries
an ordered list of `{ kind, fields }` details; a map-only transport shape is
not permitted because it loses both the detail kind and repeated detail
boundaries.

Cancellation returns an explicit disposition: `accepted`, `already-terminal`,
or `not-found`. Only malformed requests and transport/platform failures use an
RPC failure path. `GetActivation` retains its terminal state, typed terminal
outcome, final consumption, and terminal timestamp when known.

## Local release publication

Phase 1 `PublishRelease` uses the bounded unary `CapsuleArtifactUpload`:

- `capsule_manifest_json`;
- `component_bytes`;
- `component_digest`; and
- `component_media_type`.

The adapter must impose configured request/artifact byte limits before parsing
or storing content, verify the component digest, and derive any local storage
locator itself. `ReleaseDescriptor.artifact_reference` is therefore a
server-assigned opaque locator, never a client-visible filesystem path. The
JSON analogue is `schemas/release-publish.schema.json`.

## Tenant-qualified routes

Service IDs are not globally unique. Every compiled `ServiceRoute` has a
required `tenant`, and every `BindingRoute` has `consumer_tenant` and
`provider_tenant`. Resolution keys include the tenant before service, route,
contract, or function selection. A route compiler must reject or keep separate
same-named services from different tenants; it must not rely on a convention in
the service ID string.

## Standalone Phase 1 RPC subset

| Service/method | Phase 1 standalone behavior |
| --- | --- |
| `ReleaseService` publish/get/list | Supported locally. |
| `DeploymentService` apply/get/list/delete | Supported locally. |
| `DeploymentService.WatchDeployment` | Explicitly unimplemented. |
| `RouteService.GetRouteSnapshot` | Supported for current or retained local snapshots. |
| `RouteService.WatchRouteSnapshots` | Explicitly unimplemented. |
| `NodeService.GetNode` / `ListNodes` | Supported for the local node inventory only. |
| `NodeService.RegisterNode` | Explicitly unimplemented. |
| `NodeService.ReportInventory` | Explicitly unimplemented. |
| `NodeService.Heartbeat` | Explicitly unimplemented. |
| `ContractService`, `CapabilityService`, `AuditService`, `BindingService`, `TriggerService`, `PolicyService` | Explicitly unimplemented until their owning Phase 1/later ticket supplies an adapter. |

An adapter must return its transport's standard unimplemented status for every
listed unsupported method; it must never return an empty successful response.

## Compatibility record

This is a deliberate pre-Phase-1-stabilization source and wire break. The
repository has not released a stable Phase 1 API, and no generated client code
is committed. The changes replace ambiguity before persistent data or external
clients exist:

| Prior shape | Replacement | Protection |
| --- | --- | --- |
| `wall_deadline_unix_millis` field 3 | `wall_time_limit_millis` field 12 | Field 3 and its name are reserved in both Protobuf budget messages. |
| `PlatformError.details` map field 4 | repeated typed `detail_items` field 5 | Field 4 and its name are reserved. |
| `InvokeResponse.error` field 6 | `declared_error` field 8 and `platform_failure` field 9 | Field 6 and its name are reserved. |
| `CancelResponse.accepted` boolean field 1 | enum disposition field 2 | Field 1 and its name are reserved. |
| unscoped route services/bindings | required tenant fields | Schema fixtures and descriptor contract tests require the fields. |

`api/proto/phase1-field-contract.json` is a checked-in descriptor contract.
`tools/tests/test_phase1_contracts.py` verifies the reserved field numbers,
names, and replacement fields directly from the authoritative `.proto` files.
This is in addition to Buf descriptor validation.

## Integration boundary

This work is intentionally developed before #25/#2 are complete, but it is a
draft-only branch until the Phase 0 handoff is authorized. Before merge, it
must be reconciled with the finalized Phase 0 retained/replaced classification
and regenerated contract checks from #2.
