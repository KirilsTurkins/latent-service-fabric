# Release lifecycle and evidence renewal

Release lifecycle separates immutable catalog content from permission to use it.
Both trusted-local and enforced catalogs retain lifecycle records. An enforced
release additionally needs current publisher, builder, policy and host checks
from [package admission](package-admission.md) and
[release compatibility](release-compatibility.md).

`ReleaseDescriptor.admitted` remains historical publication metadata. It does
not authorize an invocation or describe current lifecycle eligibility. A revoked
or retired release keeps its original component digest, package bytes and
completion record. A rejected upload produces only a bounded operation outcome;
it cannot change an existing release's lifecycle record.

## Identity and scope

The management listener supplies the authenticated principal. The adapter uses
that principal's subject, kind and tenant for release operations; payload fields,
annotations, publisher names and operation IDs cannot override the actor.
The default management policy requires an administrator scoped to that exact
tenant. Tenant-neutral local releases remain an explicit trusted-host facility:
tenant RPCs neither disclose nor mutate them.

A catalog owns sealed lifecycle capabilities. Enforced execution composes the
lifecycle capability with a current signed admission grant; local execution has
no invented package identity or cryptographic proof. The node's runtime and
deployment store bind the exact catalog owner. A status document, copied receipt
or matching content digest cannot substitute for that owner-bound capability.

## Management calls and receipts

The generated `latent.control.v1.ReleaseService` adds four unary calls:

| Call | Input and result |
| --- | --- |
| `GetReleaseLifecycle` | A component digest selects a tenant-scoped historical record and live eligibility observation. Missing and foreign releases both have no optional status. |
| `GetReleaseOperation` | An operation ID returns `FOUND` with its immutable receipt, `UNKNOWN`, or `UNCERTAIN`. |
| `ChangeReleaseLifecycle` | Revoke or retire an existing release using an operation ID, exact positive expected generation and a permitted reason. |
| `RenewReleaseEvidence` | Supply the exact component/package identities, positive generation precondition and new detached evidence. |

`PublishReleaseRequest.operation` is optional field 4. Existing callers can omit
it; callers needing reconciliation retain their own ID before sending. Explicit
RPC publication requires a present zero generation and durable lifecycle absence. A
missing current proof does not make a revoked release absent.
`PublishReleaseResponse.operation`, field 3, reports the historical receipt
separately from the unchanged release descriptor and warnings.

For revoke, retire and renewal, missing operation metadata, a missing generation
or generation zero is invalid. The catalog checks the generation atomically.
Exact operation-ID/request replay returns the original receipt; changed input
under that ID conflicts. A replayed generation is historical, not fresh
eligibility. A new operation with a stale generation conflicts.

Revoke accepts `operator-revocation`, `security-incident` or `corrupt-content`;
retire accepts `superseded`, `end-of-support` or `operator-retirement`. These
fixed operator codes are not unbounded diagnostics or cryptographic findings.
There is no implicit restoration, and retirement is terminal.

The adapter checks the exact prospective success **or rejected-operation
response** before persistence. An unreturnable response stages no receipt.
Rejected publication remains a gRPC error; its bounded `release-operation`
detail contains the operation ID, disposition, fixed reason and optional
generation. Private error text and filesystem paths are excluded.

`UNKNOWN` includes absent, foreign and expired bounded retention; it proves
neither execution nor rollback. `UNCERTAIN` means commit durability is not yet
established. Reconcile retained operation status and recovery rather than
assuming a transport failure undid a change. Malformed, oversized and
unauthenticated requests create no durable rejected record. A rejected
`packageManifestDigest` hashes received bytes without asserting a valid package.

The corresponding Rust host methods are `ArtifactRepository::publish_managed`,
`get_release_lifecycle`, `get_release_operation`, `change_release_lifecycle`
and `renew_release_evidence`. Generic repositories return explicit unsupported
errors until implemented. Rust clients are generated from Protobuf; the other
language SDKs remain invocation interfaces. The delivered
[operator CLI](operator-cli.md) exposes publication, lifecycle/status and
operation lookup, revoke/retire and evidence renewal. Its
[workflow contract](../phase-2-operator-workflows.md) preserves caller-selected
operation IDs, exact preconditions and separate audit/durability outcomes.

The native `publish_managed` method also accepts the exact current positive
generation for identical content that remains admitted. This records a new
operation receipt while preserving the release record and generation. It cannot
replace content, restore a denied lifecycle state or renew evidence. The RPC's
explicit publication precondition remains create-only.

## Revocation cutover

Route selection, preparation, prepared-cache use and actual activation start
check current eligibility. A lifecycle mutation and a new activation's final
start decision share one fence. A call accepted at that decision may finish;
a call that only holds a route, queued compilation or ready object has not yet
been accepted. Revocation does not require interrupting an already accepted
guest or synchronously destroying its compiled code.

Healthy lifecycle reads and final activation decisions share a read fence;
they do not exclude one another. Durable lifecycle mutations and replacement
of the selected evidence proof hold an exclusive write fence. Only that
exclusive fence exposes lifecycle commit, keeping publication and its indexed
proof in one generation. Read-only lifecycle state snapshots also share access.
The separate signing authority retains its own currentness and clock checks.

Lifecycle reads and final activation decisions fail immediately on contention
with an exclusive writer, using retryable `Unavailable` reason
`release-lifecycle-busy`.
The caller may retry within its existing deadline; the runtime does not wait
for a lifecycle mutation. A just-published index entry can encounter this
short contention window while its final publication fence is released, even
though its immutable files are already complete. Retired or poisoned owners
instead return nonretryable `release-lifecycle-unavailable`; contention retries
must not hide that failure or any content-integrity or authority rejection.

Revocation and retirement do not require still-valid publisher evidence. An
authenticated operator can deny further use when proofs have expired or the
current host is incompatible. Recorded time is a historical observation, not a
new verification grant. Unavailable time is represented explicitly rather than
inventing freshness.

An otherwise valid enforced policy whose validity interval has expired can open
the catalog for historical status and lifecycle management with no positive
verification grants. Invalid policy configuration, corrupt durable floors and
unusable clock state still abort opening; this is not a fallback to local mode.

After a durable lifecycle change, old held capabilities cannot acquire the new
generation. A deploy or rollback cannot restore a revoked or retired release.
Uncertain persistence blocks positive eligibility until recovery establishes
the committed state; a failed response does not establish rollback.

## Evidence renewal and route refresh

Renewal supplies new detached evidence for the retained exact package and
component. It does not upload replacement component layers or rewrite the
original completion record. The catalog verifies the new signature, provenance
and required SBOM associations against current policy and host requirements,
then commits an immutable evidence revision and its lifecycle generation
together. Revoked and retired releases cannot regain eligibility through renewal.

Existing route snapshots keep their old capabilities. A fresh bounded control
compilation, including startup deployment recovery, can acquire current
capabilities for a release that remains admitted and passes current checks.
Invocation does not renew proofs or compile a replacement route implicitly.
Explicit deployment changes use the same control compilation boundary.

Lifecycle and evidence generations also define the eligibility boundary for
derived caches. The [raw download cache](raw-artifact-cache.md) retains no
execution authority and never evicts authoritative catalog content. Retiring a
release therefore cannot break retained deployment or rollback dependencies by
deleting their original bytes. Persistent native artifacts use the separate
native execution boundary described in [trusted AOT](../runtime/trusted-aot.md).
That optional cache is implemented: it authenticates exact native bytes while
retaining independent current lifecycle and signed-admission checks. Neither a
resident prepared hit nor a persistent native hit revives an old grant.

## Bounds and serialization

Status records have a 4 KiB hard ceiling and operation receipts 8 KiB. Operation
IDs are at most 128 UTF-8 bytes, without whitespace or control characters;
actors and local tenant identifiers are at most 512 bytes. Enforced admission
retains its stricter tenant bound. Checks include retained spare capacity before
copies. The aggregate management response cap also applies.

The shared owner defaults to 256 recent operation outcomes. Catalog and
lifecycle quotas both bound records; revoked/retired records consume capacity
rather than being evicted to admit another release. Lifecycle metadata is capped
at 128 MiB and staged intent at 32 KiB. These ceilings are not per-release
allocations or work.

Native callers configure positive downward bounds through
`DirectoryArtifactRepository::open_with_lifecycle_limits(root, config, limits)`
or `open_enforced_with_lifecycle_limits(root, config, admission_limits,
authority, limits)`. The existing constructors use `LifecycleLimits::default()`.
The recent-operation ring size is recorded in the durable mode marker and must
remain unchanged on reopen. Other limits can be lowered only when the retained
state fits; lowering a quota does not discard records or outcomes.

Renewal requires one signature and one provenance envelope, and zero or one
SBOM. Each configuration is exactly `{}`. Transport caps each manifest at
256 KiB and payloads at 4 KiB, 49,152 bytes and 1 MiB respectively. The aggregate
management request cap remains 20 MiB by default. The store's evidence-revision
cap is 2 MiB including bounded encoded association data; total retained revisions
are capped at 256 MiB by default. Lower configured limits and remaining storage
capacity can reject an otherwise transport-valid upload.

The [canonical record schema](../../schemas/release-lifecycle-record.schema.json)
and [operation receipt schema](../../schemas/release-operation-receipt.schema.json)
describe stored Rust JSON: integer generations, explicit nullable optional
fields and tenant/local-unscoped scope. The
[API projection schema](../../schemas/release-lifecycle-api.schema.json) has named
definitions for Protobuf JSON: symbolic enums, decimal-string `uint64` and omitted
optional fields. These are distinct representations. Schema success does not
authorize use or establish durability. The node still serves Protobuf RPC;
these schemas add no JSON listener.

A small [shared record and receipt fixture](../../tools/tests/fixtures/release_lifecycle/pair.json)
is checked against these schemas in Python and against the actual Rust
serializer and decoder. Its fixed timestamp is diagnostic test data and its
local record has no package or policy proof.
