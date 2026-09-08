# Standalone management services

`latent-wire::management::ManagementServiceAdapter` implements the generated
`latent.control.v1` services over the node's existing artifact repository,
versioned deployment store, compiled routes, and inventory reporter. It opens no
listener and creates no execution backend, guest instance, cell pool, or service
worker. The embedding application supplies these shared services and a trusted
authentication boundary. Standalone process composition and CLI commands are
separate Phase 1 work.

## Supported calls

| Service | Supported calls | Standalone behavior |
| --- | --- | --- |
| Release | `PublishRelease`, `GetRelease`, `ListReleases` | Immutable local publication and tenant-scoped metadata queries. |
| Deployment | `ApplyDeployment`, `GetDeployment`, `ListDeployments`, `DeleteDeployment` | Atomic tenant-scoped object versions and bounded pages. |
| Route | `GetRouteSnapshot` | Complete projection of the current catalog generation for one tenant. |
| Node | `GetNode`, `ListNodes` | The one configured node's bounded inventory snapshot. |

`WatchDeployment`, `WatchRouteSnapshots`, `RegisterNode`, `ReportInventory`, and
`Heartbeat` return explicit gRPC `Unimplemented`. They do not open an idle stream
or report fabricated cluster state.

`GetRelease` and `GetDeployment` return an absent optional record for both missing
and foreign-tenant objects. `GetNode` returns an absent optional inventory for an
unknown node ID. Deleting an absent or foreign deployment returns `NotFound`.

## Authentication and tenant scope

The listener supplies an `AuthenticatedInvocationContext` request extension,
using the same principal boundary as the [invocation service](../protocol/invocation-service.md).
The adapter validates the principal and consults the supplied `PrincipalPolicy`
and `ManagementPolicy`. Request metadata, manifest annotations, and descriptor
claims never create or override this trusted context.

The default `LocalManagementPolicy` requires an `Administrator` principal for
all supported management calls. Release, deployment, and route operations use
that principal's exact tenant. Administrator status does not grant access to a
different tenant. RPC publication requires the capsule's tenant to be present
and equal to the authenticated tenant; deployment application requires the same
for deployment metadata. Tenant-neutral artifacts remain a trusted local API
facility and are hidden from tenant RPC reads.

Node inventory can include information about the whole node. Its default policy
therefore additionally requires the trusted claim `latent.node.operator=true`.
Adding that text to payload metadata does not grant operator access. Inventory
reads never become a tenant-filtered approximation of global resource usage.

## Publishing a release

`PublishReleaseRequest.artifact` carries all publication inputs:

- `capsule_manifest_json`: the validated Phase 1 capsule manifest.
- `component_bytes`: the component bytes, subject to the configured upload cap.
- `component_digest`: the canonical lowercase `sha256:` content identity.
- `component_media_type`: `application/vnd.wasm.component.v1+wasm` or
  `application/wasm`.
- `contract_metadata_json`: the versioned, typed export descriptor document.

The component hash, manifest digest, tenant, and exported contract descriptors
must agree. Publication validates the local catalog representation and its
prospective response before committing. The immutable catalog verifies its
completion record and payload association; see the
[local release catalog](../development/local-release-catalog.md).

The optional `release` descriptor may supply matching informational claims and
annotations. Nonempty digest, service, semantic version, world, and media type
claims, a nonzero size claim, and a present tenant claim must agree with the
upload. Artifact reference, publisher, creation timestamp, and admission state
are output fields: input reference/publisher must be empty, timestamp zero, and
`admitted` false. The server assigns an opaque locator, derives service/version/
world from the manifest, and measures the uploaded size. Clients must never
interpret the locator as a filesystem path. No persisted creation timestamp is
available, so the response uses zero. `admitted=true` means catalog publication
validation succeeded; invocation still performs routing, admission, preparation,
and runtime contract validation.

An identical publication is retryable through the repository's immutable
identity rules. A digest does not permit replacing its descriptor, contract
metadata, manifest, or tenant association. A lost response should be reconciled
with `GetRelease` before deciding whether to repeat publication.

### Typed contract metadata

Use the public `latent_artifacts::encode_contract_metadata` and
`decode_contract_metadata` functions with `ContractMetadataLimits`. The document
envelope is `{"format_version":1,"contracts":[...]}`. It is independent of
filesystem completion records and contains these descriptor fields:

| Record | Fields |
| --- | --- |
| Contract | `id`, `package_name`, `semantic_version`, `interfaces`, `dependencies`, `digest` |
| Interface | `id`, `functions`, `documentation`, `digest` |
| Function | `id`, `name`, `asynchronous`, `parameters`, `results`, `documentation`, `attributes` |
| Parameter/result field | `name`, `value_type`, `documentation` |

IDs, names, digests, documentation, and dependencies are strings; interfaces,
functions, fields, and dependencies use arrays; attributes map strings to
strings. Documentation is optional/null. Value types use the following JSON
representation, with case-sensitive tags:

| Type | Representation |
| --- | --- |
| Primitive | A string: `Bool`, `U8`, `U16`, `U32`, `U64`, `S8`, `S16`, `S32`, `S64`, `F32`, `F64`, `Char`, `String`, or `Bytes` |
| List/option | `{"List":TYPE}` or `{"Option":TYPE}` |
| Result | `{"Result":{"ok":TYPE_OR_NULL,"error":TYPE_OR_NULL}}` |
| Tuple | `{"Tuple":[TYPE,...]}` |
| Named record/variant/resource | `{"Record":"name"}`, `{"Variant":"name"}`, or `{"Resource":"name"}` |
| Future/stream descriptor | `{"Future":TYPE}` or `{"Stream":TYPE}` |

The descriptor codec preserves type information; this does not enable a later
phase runtime capability. The Wasmtime backend independently rejects unsupported
execution types. Human-readable function signature text is not a substitute for
these descriptors.

Unknown fields, duplicate JSON keys, unsupported format versions, and exceeded
byte, string, structural, or retained-allocation limits are rejected. Contract
value types additionally have a depth cap of 32 and a total node cap of 16,384.
The bounded encoder and decoder accept the same configured representation.

## Deployment versions and receipts

Deployment IDs must equal `metadata.name`. The adapter preserves Phase 1 grants,
placement, availability, metadata, and all resource budget fields. It rejects
unsupported Phase 1 resource dimensions rather than discarding them. The public
conversion helpers preserve optional wall-time budgets, including absent versus
present zero; semantic validation then decides whether a request is admissible.

`Deployment.generation` is an output-only object version. Apply ignores any input
value in that field. The separate optional `expected_generation` is passed to
the repository's atomic mutation operation unchanged:

| Precondition | Apply | Delete |
| --- | --- | --- |
| Absent | Unconditional upsert. | Delete the existing object. |
| Zero | Require absence, then create. | Require absence, then return `NotFound`; a present object conflicts. |
| Positive | Require that exact live object version. | Require that exact live object version. |

The repository checks the caller precondition at commit. The adapter does not
perform a separate read/check/write. An unrelated sequential catalog mutation
does not invalidate an unchanged object's version. Deletion and recreation
assign a new version, so an old version cannot overwrite the recreated object.
An overlapping catalog compilation can still conflict independently of the
caller version. Apply returns the exact normalized record captured by its own
commit, without rereading whatever a later writer installed.

Stale object versions produce gRPC `Aborted`. Reread the object and reconsider
the desired change before retrying that precondition. A lost response or a
durability-uncertain failure can follow a committed mutation; reconcile current
state before retrying. Bounded public error details retain supported catalog
reasons and commit evidence such as operation, object/catalog generation, and
`committed=true`, while excluding arbitrary repository diagnostics and paths.

## Pages, routes, and inventory

Release and deployment lists are ordered, bounded repository pages scoped to the
authenticated tenant and optional service filter. A present empty service is
invalid. A missing page or zero `page_size` selects the configured positive
default; the wire does not distinguish omitted from explicit zero. The defaults
are 50 records per page and a maximum of 1,000. Repository page limits must be
configured coherently with the adapter.

Continuation tokens are opaque and bound to their tenant, service filter,
catalog generation, and repository instance. A page size may change between
requests. A mutation in the corresponding catalog expires existing tokens;
a repository reopen also invalidates them. Scope mismatch or malformed tokens
are invalid arguments. Restart a listing after token expiry rather than
combining pages from different catalog generations. Indexed list/get operations
do not fetch component bytes or scan a global catalog and then filter it.

Route reads return every selected route row for the tenant, or fail with
`ResourceExhausted`; they never silently truncate a snapshot. The optional
generation selects the current generation only. Older or future generations
return `NotFound`. The returned tenant and digest cover that tenant's canonical
projection, including the catalog generation and timestamp, instead of exposing
a global snapshot digest. Phase 1 projections contain no bindings or policies.
The route row limit counts default and deployment-named routes separately.

`ListNodes` returns zero or one node after applying trust-class, region, and zone
filters. It has no continuation token and rejects any supplied token. Inventory
preserves readiness, health, scheduler capacity and acceptance, pressure
availability, quotas, cache costs, and topology availability/completeness.
Unmeasured values remain explicit; cache accounting does not imply process RSS.

## Bounds and embedding

The default management limits permit a 20 MiB request, 16 MiB component, 1 MiB
manifest, 1 MiB contract metadata document, and 4 MiB response. Per-string,
identifier, collection, metadata, page, and route limits also apply. Trusted
authentication context has its own `InvocationLimits` bounds. Checks account
for retained string/vector capacity and conservative collection bookkeeping
before conversion, in addition to protobuf encoded size. Small encoded data can
therefore exceed a configured allocation budget. Returned pages also obey the
repository's separate record byte budget and the adapter's complete response
limit. Ordinary release/apply receipts are checked before mutation.

Use `release_server()`, `deployment_server()`, `route_server()`, and
`node_server()` when constructing generated Tonic servers so decoding and
encoding ceilings match the adapter. The listener remains responsible for
authentication, transport security, and worker/shutdown composition. Durable
catalog mutation performs synchronous filesystem work and belongs on bounded
control-plane workers, separate from invocation workers. These adapters do not
add automatic retries, an invocation lifecycle, or cluster reconciliation.

The focused Linux test entry point is
`cargo test -p latent-wire --test management_service`. It uses generated clients
and servers over an in-memory duplex connection, real small directory catalogs,
fixed authenticated fixture principals, and five-second transport/shutdown
bounds. No guest workload, scale publication, or long-running soak is required.
