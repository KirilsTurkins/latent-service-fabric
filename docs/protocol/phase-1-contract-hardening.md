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

Caller activation, root, and parent IDs are optional and are preserved across
all six SDK request surfaces. Their absence, lineage validation, known-ID
cancellation/status, local-wait cancellation, and compatibility rules are
specified in the [SDK contract](../../sdk/README.md#invocation-identity-and-cancellation).
The server assigns missing activation IDs; SDKs do not silently generate them
or reinterpret a present empty ID as absent. This does not add an automatic
retry policy or make an activation ID an idempotency key.

An invocation has exactly one wire-visible terminal result:

- `success`: a guest completed successfully;
- `declared_error`: a guest/domain result; or
- `platform_failure`: infrastructure rejected, interrupted, or failed it.

Each result includes finalized `BudgetConsumption`. A platform error carries
an ordered list of `{ kind, fields }` details; a map-only transport shape is
not permitted because it loses both the detail kind and repeated detail
boundaries.

`latent-rpc::platform_error` provides the canonical conversion between the Rust
`PlatformError` domain type and both generated Protobuf `PlatformError` types.
Stable codes use the documented lower-kebab-case spelling. Unknown wire codes
are rejected with `UnknownPlatformErrorCode` instead of being coerced to a known
classification. The conversion preserves message, retryability, detail order,
detail kind, and every bounded field exactly through Prost serialization.

The Rust execution boundary mirrors that distinction before an activation is
mapped: GuestOutcome has separate Returned, DeclaredError, Trapped, and
Interrupted variants. A backend must convert a typed guest/domain result to
DeclaredError at that boundary. The activation runner must not infer a
declared error from payload bytes, media types, or a service-specific
convention.

Cancellation returns an explicit disposition: `accepted`, `already-terminal`,
or `not-found`. Only malformed requests and transport/platform failures use an
RPC failure path. `GetActivation` retains its terminal state, typed terminal
outcome, final consumption, and terminal timestamp when known.

For a retained success, the summary carries committed_state_version,
effect_ids, and metadata; the Rust domain summary, Protobuf
ActivationSuccessSummary, and every SDK retain the same three fields.

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

## Deployment generations and pagination

The [deployment repository](../deployment-routing.md) supplies the atomic
versioned port consumed by management adapters in #37. The generated
`Deployment.generation` field is output-only: adapters ignore it in apply input
and preserve its full unsigned 64-bit value in responses. The optional
`expected_generation` field is the caller's only precondition:

| Expected generation | Apply | Delete |
| --- | --- | --- |
| Absent | Unconditional upsert. | Delete an existing object; missing is `NotFound`. |
| `0` | Require absence, then create. | Existing object conflicts; absent object is `NotFound`. |
| Positive | Require the exact current object version. | Require the exact current object version. |

An object version is its last mutation's catalog stamp. Unrelated writes do not
change it; unchanged applies do. Delete/recreate receives a new stamp. The
repository checks caller expectations at atomic commit and returns the committed
record/version directly. Adapters must not substitute read/check/write sequences
or read the current object afterward to construct a mutation response. Internal
compilation conflicts are separate from stale caller versions: a concurrent
unrelated write may require recompilation with the same caller precondition.

Get, list and delete requests obtain their tenant from the authenticated local
principal; the wire messages' missing tenant fields do not authorize global
catalog access. An apply's manifest tenant must match that principal. Adapters
must use the tenant-scoped repository operations, bound input and response sizes,
and map structured errors without exposing another tenant's state.

Deployment pages are ordered by deployment ID within one tenant and optional
service filter. Tokens are opaque and bound to that scope and repository
generation; any catalog publication or repository reopen expires them. They do
not authenticate or authorize callers. Limits and token validity are checked
before selecting or cloning records, and pagination does not fetch artifacts.
Changing page size between continuations is permitted within the configured
limits. The repository rejects page size zero. In #37's wire adapter, a missing
`PageRequest` or zero `page_size` selects the adapter's configured positive
default within the repository limit: Protobuf cannot distinguish an omitted
non-optional scalar from explicit zero. The repository's page byte budget covers
encoded records; adapters also bound the entire wire response. #37 must test
generation conversion, preconditions, scoped pagination and
unsupported watch behavior through its generated client/server path; this
repository feature does not expose a management listener.

## Tenant-qualified routes

Service IDs are not globally unique. Every compiled `ServiceRoute` has a
required `tenant`, and every `BindingRoute` has `consumer_tenant` and
`provider_tenant`. Resolution keys include the tenant before service, route,
contract, or function selection. A route compiler must reject or keep separate
same-named services from different tenants; it must not rely on a convention in
the service ID string.

## Standalone Phase 1 RPC subset

This table is the implementation contract for #12, #37, and #14. Those adapters
and the standalone listener are not yet merged; generated messages and service
traits alone do not make these methods callable.

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

api/proto/phase1-descriptor-contract.json is a normalized, checked-in
FileDescriptorSet golden. tools/validate_contracts.sh builds the authoritative
descriptor with Buf and tools/validate_phase1_descriptor.py compares field
types, cardinality, oneof membership, enum values, service signatures, and
reservations with that golden. tools/tests/test_phase1_contracts.py exercises
the validator's drift detection and the cross-SDK surface requirements.

## Integration boundary

Phase 0 gate #25 and the executable build foundation in #2 are complete. This
work is reconciled with the finalized Phase 0 retained/replaced classification
and with `development`'s generated Rust, Component Model, and RPC ownership.
The hardened Protobuf services compile through `latent-rpc`, and the normalized
Buf descriptor golden is verified from the same exhaustive Protobuf manifest.

No dependency gate remains on this merged contract work. Changes are checked
by the normal `CI` workflow and the path-filtered `Phase 0 runtime regression`
workflow, including Phase 1 descriptor/SDK checks and retained executable
containment coverage. The Phase 0 full completion gate and heavy catalog scale
probe require explicit manual selection; see [validation](../../VALIDATION.md).
