# Standalone management services

`latent-wire::management::ManagementServiceAdapter` implements the generated
`latent.control.v1` services over the node's existing artifact repository,
versioned deployment store, compiled routes, inventory reporter, and optional
shared durable audit handle and rollout coordinator. It opens no
listener and creates no execution backend, guest instance, cell pool, or service
worker. The embedding application supplies these shared services and a trusted
authentication boundary. The [standalone Linux node](standalone-node.md)
supplies this composition and a configured loopback listener. The
[`latent` operator CLI](operator-cli.md) exposes release, deployment, route and
node calls with bounded local input validation, exact object versions, private
profiles, and one request per command. Audit RPCs currently require a generated
client; there is no audit CLI command. The [echo quickstart](../development/standalone-quickstart.md) uses its
generated package inputs through this RPC boundary.

## Supported calls

| Service | Supported calls | Standalone behavior |
| --- | --- | --- |
| Release | `PublishRelease`, `GetRelease`, `ListReleases`, `GetReleaseLifecycle`, `GetReleaseOperation`, `ChangeReleaseLifecycle`, `RenewReleaseEvidence` | Immutable publication, tenant-scoped metadata, durable lifecycle and bounded evidence renewal. |
| Deployment | `ApplyDeployment`, `GetDeployment`, `ListDeployments`, `DeleteDeployment` | Atomic tenant-scoped object versions and bounded pages. |
| Route | `GetRouteSnapshot` | Complete projection of the current catalog generation for one tenant. |
| Node | `GetNode`, `ListNodes` | The one configured node's bounded inventory snapshot. |
| Audit | `QueryAudit`, `QueryPhase2Audit` | Bounded durable history when the node's optional audit owner is configured. |
| Rollout | `StartRollout`, `ChangeRollout`, `EvaluateRollout`, `GetRollout`, `ListRollouts`, `GetRolloutOperation` | Optional audited stages and declared canary promotion over one tenant/service cohort. |

`WatchDeployment`, `WatchRouteSnapshots`, `RegisterNode`, `ReportInventory`, and
`Heartbeat` return explicit gRPC `Unimplemented`. They do not open an idle stream
or report fabricated cluster state.

An omitted audit owner makes both audit calls return `Unimplemented` after
authentication and scope validation. See [Phase 2 audit](../phase-2-audit.md) and
the node's [durable audit settings](standalone-node.md#optional-durable-audit).

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

Audit tenant queries require the same administrator and exact tenant association.
Typed node-scope queries additionally require the trusted node-operator claim
and forbid a tenant member. Operators cannot query another tenant's history.
The legacy `QueryAudit` call always uses the authenticated tenant, including
when its optional tenant field is absent.

See [release lifecycle](release-lifecycle.md) for authenticated actors, atomic
mutation preconditions, evidence renewal, operation retention and uncertain
outcomes. Historical descriptors and live eligibility are separate.

## Manual rollout control

The optional rollout adapter requires the same configured `AuditHandle` as the
other management services. Construction rejects mismatched owners. Every call
requires an administrator with an exact authenticated tenant; the node-operator
claim supplies no cross-tenant access. Actor and tenant are derived from this
identity, never supplied in the rollout request. Disabled calls return
`Unimplemented` after authentication and bounded request validation.

`StartRollout` names one existing base deployment and one new candidate for the
same tenant, namespace and service. The base must be the complete current
default-route cohort; broader cohorts are explicitly unsupported. Start requires
a positive base object generation, candidate ID absence, a zero candidate output
generation and a present operation revision of zero. The candidate's input
weight must equal the first stage. Candidate weights are strictly increasing
basis points from 1 through 10000, ending at 10000. Each route-changing commit
checks exact cohort membership, object versions and current source eligibility;
the two releases must have different component identities and compatible exports.

Start atomically installs stage zero and its receipt. `ChangeRollout` requires
a positive exact expected revision and an operation ID. Advance names exactly
the next step. Pause and Abort only change control state, preserving the same
route generation and grants even after trust or cohort drift. Abort ends forward
progress and does not itself roll back. Resume recompiles the same weights with current grants
and publishes a new route generation before returning to Running. A final
10000-basis-point stage atomically removes the base deployment and completes
the rollout. Plans without a canary policy retain these manual semantics.

Start and Change return the exact committed receipt, a separate durability
value, audit acknowledgement and replay flag. A matching retained operation ID,
request, actor and scope replays its original receipt before revision checks.
Different content conflicts. Only committed receipts are retained; validation,
preflight or CAS rejection has no durable rollout receipt. State-only changes
advance the rollout revision and shared state version without changing routes.
Response preflight runs before durable audit acceptance and catalog mutation.
Audit failure cannot rewrite a real committed result.

`GetRolloutOperation` distinguishes Found, Unknown and Uncertain. Unknown includes
missing work, failed precommit work, foreign scope and evicted receipts; it never
establishes that a change did not happen. Uncertain means the selected complete
catalog lacks durable confirmation. The exact receipt and separate durability
status prevent a post-rename sync failure from appearing to undo the mutation.
Reconcile before issuing another operation. Retained rollout IDs are not deleted
or recycled, and receipt eviction cannot make an old expected revision current.

`GetRollout` hides missing and foreign records with the same absent status.
List is tenant scoped with optional service/state filters and bounded cursors
that expire on catalog publication or reopen. Returned status is historical
control data and supplies no execution grant. Current cohort drift can be
reported as Conflicted without mutating retained history.

Requests are capped at 64 KiB (8 KiB for reads), with bounded identifiers,
collections and caller capacities checked before conversion. Replies are capped
at 64 KiB and retain one charged response owner through protobuf encoding, HTTP
body ownership and retained byte frames. An absolute deadline covers queueing,
work and final conversion. Cancellation does not release accepted worker
ownership early. Audited errors reuse the bounded `latent-audit-status` and
`latent-audit-attempt` metadata described below. Current rollout calls require
a generated client; there is no rollout CLI command yet. See the node's
[manual rollout settings](standalone-node.md#optional-manual-rollouts).

### Restoring a retained rollout base

New Starts capture one immutable `rollback_target` in status: format version 1,
the route generation immediately before Start, and the digest of the exact
original base deployment manifest. Read it with `GetRollout`; it is never an
input to Start. Older plans without this field remain readable and replayable,
but a fresh rollback reports target unavailable. No target is inferred from a
receipt, current object generation or arbitrary historical route snapshot.

`ChangeRollout.rollback` requires the usual operation ID and exact current
revision, plus a positive `target_generation` equal to that stored target.
For example, a status at revision 4 with historical target generation 12 permits
this Protobuf JSON request:

```json
{
  "id": "checkout-v2",
  "operation": {"operationId": "restore-v1", "expectedRevision": "4"},
  "rollback": {"targetGeneration": "12"}
}
```

Rollback restores the original base weight, grants, resources and placement,
removes the candidate, and publishes a fresh route generation atomically with
the RolledBack state and receipt. Unrelated deployments remain. The receipt's
`route_generation` is the new publication; its `rollback_target` identifies the
older restoration origin. The step and candidate weights preserve historical
progress and do not describe the restored traffic weights.

Running, Paused, Completed and Aborted plans can roll back only while their
current managed cohort still matches. Conflicted or already RolledBack plans
reject new rollback operations. The target must be available, intact and
currently eligible under lifecycle, trust and runtime policy. Compatibility is
checked from the served candidate toward the restored base; a compatible
forward update does not prove a compatible rollback. A revoked candidate can
still supply intact historical comparison bytes, but a revoked target cannot
receive new traffic.

Rollback needs no canary hub, elapsed interval or healthy proof. A committed
rollback retires the current observation and does not register another window.
Already-started calls keep their original revision and budget; later route
selection uses the restored base. Exact retained operation replay returns the
original receipt without another mutation, including after restart. Rejections
have bounded audit acknowledgement and no committed rollout receipt. Audit
attempts preserve the requested target separately from a committed outcome's
validated target and new route generation. See [atomic rollback](../phase-2-rollback.md)
for recovery and durability boundaries.

### Declared canary evaluation and promotion

Start may include an immutable `canary_policy`; omission keeps the existing manual
plan. A canary plan has at least two stages and requires the node's optional
observation hub. Its explicit format is described by
[rollout-canary-policy.schema.json](../../schemas/rollout-canary-policy.schema.json):

```json
{
  "formatVersion": 1,
  "observationMillis": 30000,
  "minimumCandidateSamples": 100,
  "maximumFailureBasisPoints": 100,
  "latencyThresholdMicros": 100000,
  "maximumSlowBasisPoints": 100
}
```

These are declared thresholds, not a measured universal SLO. Both zero-valid
basis-point thresholds require protobuf presence. Latency thresholds must be
one of the eight fixed inclusive histogram boundaries. Candidate minima use the
candidate's own selected terminal outcomes, including failed admission, domain
and platform errors, deadlines and cancellation. At least one admitted terminal
and one successful candidate call are required. Missing, incomplete, open,
draining or insufficient observations cannot establish health.

`EvaluateRollout` requires an exact positive expected revision and returns a
bounded report for the registered base/candidate revisions. It may start a missing
fresh interval and return Collecting; it never changes weights. Reports show
explicit selected/admitted/terminal counts, all outcome classes and nine latency
buckets. Timing starts at successful window registration and measures host
activation duration, not network request latency. Get/List do not register windows.

For a canary plan, `ChangeRollout.promote` names exactly the next step and uses
the normal operation ID and expected revision. The ordinary Advance command is
rejected for that plan. Promotion uses only the coordinator's exact-owner sealed
window, then rechecks cohort, generation and release eligibility at atomic commit.
No submitted report, healthy flag, window ID or copied counter grants permission.
Already-started calls keep their original revision and budget.

Successful promotion receipts include a bounded decision summary binding policy,
control state, evidence and candidate/base counters. Exact committed replay works
after restart without collecting replacement evidence. Rejected promotion receives
a fixed error with audit acknowledgement; it creates no committed rollout receipt.
Evaluate returns the full diagnostic report. Typed audit outcomes retain bounded
decision identities, verdict, reason, declared thresholds and assessed counters,
including rejected promotion decisions, so those facts remain inspectable after
restart. The audit summary is historical evidence and cannot authorize promotion.

Start, Resume and Promote may return an optional observation status separately
from the receipt and durability result. Registration pressure after commit cannot
undo that commit. Pause/Abort retire observations; Resume refreshes the same
weights and requires a fresh interval before later promotion. Without the optional
hub, Resume can still refresh weights and reports observation unavailable.
Restart preserves policy and stage, but no prior elapsed interval or healthy proof.

## Publishing a release

`PublishReleaseRequest` requires exactly one upload. The additive `package`
field performs [authenticated package admission](package-admission.md) in an
enforced catalog; it forbids the caller `release` descriptor entirely. The
repository derives publisher and metadata, and the adapter preflights its exact
response before any durable staging. An enforced repository rejects the legacy
`artifact` path.

In trusted-local mode, `PublishReleaseRequest.artifact` carries these inputs:

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
available, so the response uses zero. `admitted=true` means historical catalog
publication validation succeeded. It does not distinguish local compatibility
from authenticated package admission or promise current eligibility after a
trust change. Invocation still performs routing, current admission, preparation,
and runtime contract validation.

An identical publication is retryable through the repository's immutable
identity rules. A digest does not permit replacing its descriptor, contract
metadata, manifest, or tenant association. A lost response should be reconciled
with `GetRelease` before deciding whether to repeat publication. The optional
`operation` input retains a caller ID for exact operation reconciliation through
`GetReleaseOperation`; zero generation then requires durable lifecycle absence.

With audit configured, package verification may submit a lossy diagnostic
observation after the authority's verification call returns. That diagnostic
does not establish a durable publication attempt or authorize a commit. The
critical publication audit begins only after the exact response and receipt
preflight succeeds, before durable catalog mutation, on the bounded control
worker outside lifecycle and authority fences. Consequently, a rejected
response preflight can leave a verification diagnostic while leaving no
critical mutation attempt. See [audit ordering and recovery](../phase-2-audit.md).

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

## Audit acknowledgements and queries

Audited `PublishRelease`, `ChangeReleaseLifecycle`, `RenewReleaseEvidence`, and
`ApplyDeployment` responses carry the additive `audit_ack` member. Its optional
`attempt_sequence` identifies the durable attempt; its status describes audit
coverage separately from the mutation's catalog result:

| Status | Meaning |
| --- | --- |
| `DURABLE` | A durable audit outcome establishes the known operation disposition, which may be committed or rejected. |
| `OUTCOME_UNKNOWN` | The audit attempt exists, but its definitive outcome was not durably established. |
| `AUDIT_UNAVAILABLE` | An audit attempt could not be obtained; emergency revocation may still commit its mandatory lifecycle receipt. |
| `DISABLED` | The protocol's explicit unaudited status; this node preserves compatibility by omitting `audit_ack` when audit is not configured. |

`DeleteDeployment` retains its `Empty` response. Its acknowledgement uses
bounded gRPC response metadata: `latent-audit-status` and, when available,
`latent-audit-attempt`. The status values are `durable`, `outcome-unknown` and
`audit-unavailable`; the attempt value is a decimal `uint64`. Mutation errors
also carry this metadata when the adapter obtained an acknowledgement. Errors
before the audit boundary need not include it. Disabled audit adds no metadata.

Audit pressure normally rejects a critical operation before mutation. Emergency
revocation alone may proceed with its durable lifecycle receipt and explicit
audit degradation. A terminal audit-write failure after a catalog commit cannot
turn that commit into a rejection: retain the real mutation result and
reconcile unknown outcomes using the existing operation or deployment APIs.
An audit acknowledgement is neither an execution capability nor evidence of
rollback. Lost network responses require the same reconciliation.

`QueryPhase2Audit` returns typed observations, attempts and outcomes, with exact
identities where known. Actor and time filters apply to stored records; kind
filters select the corresponding observation kind. The durable query time
range uses `accepted_at_unix_millis`, the journal's acceptance timestamp, rather
than the producer's `occurred_at_unix_millis`. Continuation tokens bind the
journal identity, exact scope, filters and captured high watermark. Later
appends do not silently extend that page sequence.

Coverage includes the retained floor, high watermark, scanned count, stopping
reason, dropped observations and durable unknown outcomes. A scan may stop at
its record, byte or scan limit. After reopening,
`previous_session_loss_unknown` reports that prior volatile diagnostic loss
cannot be reconstructed. Reaching the end does not establish complete audit
coverage or erase those limitations.

`QueryAudit` returns a limited legacy projection of the same tenant-scoped
records. Its action filter accepts supported observation names; unsupported
actions and any resource-prefix filter are rejected. Use the typed call for
full identities and coverage. Scope/filter cursor mismatches, malformed filters
and invalid time ranges are `InvalidArgument`; foreign scopes are
`PermissionDenied`. Page or owner pressure returns `ResourceExhausted`.

Audit requests are capped at 8 KiB and encoded responses at 64 KiB, subject to
lower embedding limits. The journal independently bounds page records, scan
work and retained response owners. A page allowance remains owned through
conversion, delayed protobuf encoding and HTTP body/frame consumption or drop;
transport-retained bytes still count. The absolute query deadline includes
conversion and is at most five seconds. These calls do not perform audit work
on the invocation path. See [Phase 2 audit](../phase-2-audit.md) for persistence,
loss accounting, producer scope and shutdown guarantees.

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

Use `release_server()`, `deployment_server()`, `route_server()`, `node_server()`,
and `audit_server()` when constructing Tonic servers so decoding and encoding
ceilings match the adapter. The audit wrapper also retains the page allowance
through HTTP body and frame ownership. `ManagementServices.audit` receives the
same concrete `AuditHandle` for queries and control operations. The listener remains responsible for
authentication, transport security, and worker/shutdown composition. Durable
catalog mutation performs synchronous filesystem work and belongs on bounded
control-plane workers, separate from invocation workers. These adapters do not
add automatic retries, an invocation lifecycle, or cluster reconciliation.

The focused Linux test entry point is
`cargo test -p latent-wire --test management_service`. It uses generated clients
and servers over an in-memory duplex connection, real small directory catalogs,
fixed authenticated fixture principals, and five-second transport/shutdown
bounds. No guest workload, scale publication, or long-running soak is required.
