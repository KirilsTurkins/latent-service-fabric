# Embedded deployment catalog and local routing

`latent-control-store::DirectoryDeploymentRepository` is the standalone, node-owned implementation of `DeploymentStore`, `CompiledRouteStore`, `RouteCompiler`, `RouteSnapshotPublisher`, `RouteSnapshotSource`, and `RouteResolver`.

The implementation is available through Rust APIs and the
[standalone node](reference/standalone-node.md), whose
[management RPCs](reference/management-services.md) use this same repository.

It converts deployment metadata and verified release metadata into immutable local route indexes. It does not prepare Wasmtime modules, allocate execution cells, start runtimes, spawn tasks or threads, create listeners, or perform admission. Those operations belong to the node's execution path after resolution.

## Embedding and ownership

Construct one repository per node-owned directory and share it through `Arc`. Use the real `DirectoryArtifactRepository` as its release source:

```rust,ignore
use std::sync::Arc;
use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
use latent_control_store::{
    DeploymentStore, DirectoryDeploymentRepository, DirectoryDeploymentRepositoryConfig,
};
use latent_routing::RouteResolver;

let releases = Arc::new(DirectoryArtifactRepository::open(
    release_directory,
    DirectoryArtifactRepositoryConfig::default(),
)?);
let routes = Arc::new(DirectoryDeploymentRepository::open(
    deployment_directory,
    releases,
    DirectoryDeploymentRepositoryConfig::default(),
).await?);

let receipt = routes.apply_versioned(
    &authenticated_tenant,
    validated_deployment,
    Some(0), // Create only; require the deployment to be absent.
).await?;
// Return receipt.deployment to the caller; do not read the current object again.
let resolved = routes.resolve(&invocation_target, Some(routing_key))?;
// Pass this owned ResolvedRevision to admission/execution. Do not resolve it again.
```

Management methods perform synchronous local filesystem I/O despite implementing asynchronous trait seams. Run them on a control-plane worker, not on an invocation worker. They are trusted-local management interfaces, not tenant-authenticated HTTP endpoints. An API adapter must authenticate and authorize management operations, then supply the authenticated tenant to `apply_versioned`, `get_versioned`, `delete_versioned`, and `list_page`. The older global `get`, `list`, `apply`, `delete`, and `apply_many` operations remain trusted-local compatibility methods; management adapters must use the versioned, scoped port.

The directory has one exclusive advisory owner lock. A second independently opened handle is rejected; clone an `Arc` instead. Linux local filesystems with atomic same-directory rename, file synchronization, directory synchronization, and file locking are the supported persistence environment. The directory must remain under node ownership; the checksum and advisory lock are not protection against a malicious host administrator.

`open` may create a nonexistent nested catalog path. When its future is first polled, it anchors relative input once against the current working directory before filesystem work or asynchronous suspension. It canonicalizes the created path and synchronizes every directory from the catalog root through the filesystem root, leaf first, before acquiring ownership or initializing state. This includes the parent entries of all newly created components. The same sequence runs when the path already exists: a previous failed synchronization or process interruption may have left existing but not yet durable directory entries. A directory synchronization failure returns retryable `Unavailable` with reason `catalog-path-durability-uncertain`; initialization does not proceed. The ancestor directories must therefore be readable and support directory synchronization. Pre-existing symlinks and external mount provisioning remain the operator's responsibility.

The handle retains the canonical absolute root for locking, reads, staging, cleanup, commits and synchronization, matching the [artifact repository](development/local-release-catalog.md). A subsequent working-directory change cannot redirect operations to another catalog, including while opening awaits verification of restored release metadata. Constructing an unpolled `open` future does not yet resolve its path. The operator must keep the opened directory and its ancestors in place; external renames or hostile symlink replacement remain outside the ownership protocol.

## Deployment and route identity

Deployment IDs are globally unique within one catalog. `apply` is an upsert, but an existing ID cannot change tenant, namespace, or service. `apply_many` rejects repeated IDs within the same batch, rather than silently using the last occurrence. The ID `default` is reserved for the default route.

The effective route key is `(tenant, service, route)`. Because `InvocationTarget` has no namespace field, the compiler enforces an explicit invariant: **all deployments for the same `(tenant, service)` pair must use the same namespace, including whether a namespace is absent**. Ambiguous namespace combinations fail with `PermissionDenied`. Different tenants can freely use the same service ID and different namespaces without collision.

Every deployment contributes to two route names: the service's `default` route and a named route equal to that deployment's ID. An absent optional route means `default`. An unknown supplied route fails; it never falls back to another route or tenant. A named deployment route selects only that deployment.

Within the selected route, candidates must export the requested contract and function. Missing routes return `RouteUnavailable`; an existing route without the requested endpoint returns `IncompatibleContract`. Exported contracts require complete function metadata. Duplicate contract, interface, or function IDs are rejected. Deployments for the same tenant/service cannot supply conflicting canonical schemas for the same contract ID, even when a descriptor's claimed digest is unchanged. Compatibility compares SHA-256 fingerprints computed from the full canonical metadata, including documentation, attributes, and type descriptions, rather than trusting the claimed digest. This uses the same collision-resistance assumption as release and revision identity.

## Versioned desired state and atomic preconditions

`VersionedDeployment { manifest, generation }` keeps the observed object version
separate from the declarative `DeploymentManifest`. Its generation is the catalog
publication stamp assigned by the object's last accepted apply. It is positive
and need not increase by one: other catalog publications may occur between its
updates. Unrelated writes and snapshot-only publications leave it unchanged.
Accepted unchanged applies still advance it. A batch assigns its one new stamp
to every affected object, retaining untouched versions. Deletion advances the
catalog generation, and recreating the ID receives a newer stamp without a
retained tombstone. Restart preserves these versions.

The versioned apply and delete methods accept an optional caller generation:

| Expected generation | Apply | Delete |
| --- | --- | --- |
| `None` | Unconditional upsert. | Delete an existing object; absence is `NotFound`. |
| `Some(0)` | Require absence, then create. | Existing object conflicts; absence is `NotFound`. |
| `Some(g)` with `g > 0` | Require a live object with exactly version `g`. | Require a live object with exactly version `g`. |

The explicit tenant scopes the operation, and an apply's manifest tenant must
match it. Scoped get returns no record for another tenant. Existing deployment
scope cannot be changed through an update. The Protobuf `Deployment.generation`
field is output-only; adapters ignore it in apply input and pass only
`expected_generation` as the precondition.

Caller preconditions are checked at commit under the writer mutex, even when an
early check also rejects obvious conflicts. A stale caller receives retryable
`StateConflict` with reason `deployment-generation-conflict` and must inspect
the object's current version before deciding to retry. The independent catalog
comparison can instead return `stale-route-generation` when a concurrent writer
invalidates compiled state. Recompile that operation with the original caller
precondition; an unrelated object's change does not invalidate the target's
observed version.

`DeploymentApplyReceipt` returns the exact normalized `deployment` installed by
the mutation and its `catalog_generation`. `DeploymentDeleteReceipt` returns the
`deleted` record with its old object version and the catalog generation that
published deletion. Neither receipt is assembled from a post-commit read that
could observe a later writer. Legacy mutation methods use the same version
bookkeeping and cannot bypass these publication rules.

## Bounded tenant and service pages

`DeploymentStore::list_page` accepts an owned `DeploymentPageRequest` containing
`tenant`, optional `service`, `page_size`, and optional `page_token`.
`DirectoryDeploymentRepository::list_deployment_page` borrows the request for the
same operation as a synchronous inherent method. The result contains `deployments`, an optional
`next_page_token`, and the observed `catalog_generation`.

Pages use ascending deployment-ID order within the explicit tenant and optional
service. Separate tenant/ID and tenant/service/ID indexes select only that scope.
One request inspects at most its returned records plus one lookahead and clones
only returned manifests; it does not clone the global catalog, fetch artifacts,
encode manifests, or scan unrelated tenant/service records. Cached record sizes
are computed when indexes are built and remain bound to the immutable catalog.

The repository page size must be in `1..=max_page_size`, whose default is 1,000;
zero is invalid. In the future #37 wire adapter, a missing `PageRequest` or zero
`page_size` selects the adapter's configured positive default within that limit.
Omitted and explicit zero are indistinguishable in the non-optional Protobuf
scalar. The default `max_page_bytes` is 4 MiB and bounds the sum of
compact encoded records, each `{"manifest":<canonical manifest>,"generation":<u64>}`.
The surrounding page envelope and continuation token are outside that accounting;
an RPC adapter must also bound its complete wire response. A record that would
exceed the byte budget is not cloned. If earlier records fit, the continuation
points after the last returned record; if the first record cannot fit, the
request fails with `ResourceExhausted` and `deployment-page-byte-limit`.

Tokens bind the tenant, optional service, last returned ID and catalog generation
with a per-open fingerprint. They are opaque continuation data, not credentials
or a cryptographic authentication mechanism; explicit tenant scoping remains
independent of token contents. Reusing a token with another tenant or service,
transferring it to another repository, or reopening the repository invalidates
it. Any catalog publication expires an older generation's token, including an
unrelated write or snapshot-only publication. No historical page snapshot or
per-token server record is retained. A page remains internally coherent if a
concurrent writer publishes, but its continuation may already have expired;
restart listing from the first page in that case. Page size may change between
continuations within the configured limits.

Raw token input is bounded by `64 + 6 * max_identifier_bytes` bytes (6,208 bytes
with the default identifier bound), before parsing. Invalid page sizes return
`InvalidArgument` with `invalid-deployment-page-size`; invalid tenant/service
identifiers return `invalid-deployment-page-scope`. Invalid, damaged, cross-scope
or foreign-instance tokens return `invalid-deployment-page-token`; a token from
an older current-instance catalog generation returns `StateConflict` with
`expired-deployment-page-token`. These checks precede record selection/cloning.

## Deterministic logical revisions

`deployment_revision_id` derives the revision as follows:

1. Validate the deployment and normalize the release digest's hexadecimal spelling to lowercase.
2. Set `route_weight` to `1` in an identity-only copy. All other deployment fields remain included: ID, tenant, namespace, service, release, grants, resource budgets, placement, availability, labels, and annotations.
3. Encode that copy with the bounded canonical `JsonManifestCodec`.
4. Hash `b"lsf-deployment-revision-v1\0" || length || encoded_deployment`, where `length` is the byte length encoded as an unsigned 64-bit big-endian integer.
5. Return `revision-v1:sha256:<lowercase hexadecimal SHA-256>`.

There are no timestamps, random values, process identifiers, iteration-order dependencies, or route generations in this identity. Reopening the same persisted deployment produces the same logical revision. Reweighting does not create a new execution revision; changes to budgets, grants, scope, release, or other pinned deployment settings do.

A `ResolvedRevision` owns its exact revision, release digest, and generation. Its attributes contain the canonical deployment (`lsf.deployment`) and exported endpoint/schema information (`lsf.exports`). Updating or deleting the current deployment cannot modify a result already returned to an invocation.

For consumers that need several lookups against one generation, `pin()` returns a `PinnedRouteResolver`. It retains that complete immutable generation, including after deletion. Explicit pins retain metadata until their final owner drops them; they retain no execution runtime or per-deployment filesystem handle.

## Deterministic weighted selection

Weights must be in `1..=10_000`. For the eligible contract/function candidates, sort revisions by ascending `RevisionId` and construct checked 64-bit cumulative weights.

The selection hash is SHA-256 over `b"lsf-route-selection-v1\0"` followed by these six UTF-8 values, each prefixed by its unsigned 64-bit big-endian byte length: tenant, service, route, contract, function, and routing key. An absent route is `default`; an absent routing key is the empty string. Other spelling and case remain significant.

Interpret the first eight hash bytes as an unsigned 64-bit big-endian integer. The bucket is that integer modulo the sum of eligible weights. Select the first cumulative weight strictly greater than the bucket.

This is deterministic weighted selection, not random round-robin or consistent hashing. Without a varying routing key, requests select the same bucket. Reweighting or changing the candidate set can change selections. No canary controller, traffic feedback, or automatic rollback is implemented.

## Complete publication and reader behavior

Each successful apply, batch apply, delete, or explicit snapshot publication advances the catalog route generation exactly once. Empty batches are no-ops. Generation exhaustion returns `ResourceExhausted`, never wraps to zero. Object versions and deterministic revision IDs follow the separate rules above.

Writers compile and validate outside the publication lock. Commit compares the expected generation with the live one under a writer mutex. Concurrent stale writers receive retryable `StateConflict` and must retry from the new desired state; they cannot overwrite a newer transaction.

Invocation resolution attempts the reader lock once with `try_read`. Contention returns retryable `Unavailable` immediately. A successful lookup performs immutable tree lookups, bounded input hashing, binary search over cumulative weights, and copying of the selected metadata. It performs no artifact fetch, filesystem access, remote control-plane access, compilation, await, or polling. The ordinary lookup borrows the catalog so it cannot become the final owner that destroys a retired catalog on the invocation worker.

The writer takes the reader lock only to replace the complete catalog pointer and generation. Large old-catalog destruction occurs outside that lock. A reader observes a complete old or complete new catalog, never an in-place mutation. An explicitly pinned view needs no reader lock; its final drop may release the retained metadata, so applications requiring strict teardown latency should release long-lived pins on their control-plane worker.

`RouteCompiler::compile` validates the supplied previous snapshot against the current complete snapshot and creates the next generation. `publish` and `CompiledRouteStore::put` accept only the exact next-generation snapshot compiled from current desired state. Arbitrary, partial, altered, or stale snapshots are rejected.

`RouteSnapshotSource::watch` is an immediate, coalescing local read: it returns either the current complete snapshot when newer than the cursor, or an empty vector. A future cursor is invalid. It does not maintain a per-service subscription, wait for a later generation, or retain unbounded history. `CompiledRouteStore::get` retains only the current generation. Local binding/policy compilation is outside this deployment-only implementation; binding resolution fails explicitly with `RouteUnavailable`.

## Persistence and recovery

The fixed node-owned files are `catalog.json`, `INITIALIZED`, and `.catalog.lock`. A mutation temporarily creates `.catalog.pending`; first initialization can also create `.INITIALIZED.pending`. Deployment identifiers are metadata, never filesystem paths.

One versioned JSON record contains desired deployments, their object generation stamps, and the complete compiled snapshot. Its SHA-256 checksum covers the canonical payload. Format version 2 stores a sorted `object_generations` list of `{id, generation}` entries alongside the manifests. The key set must match the live deployments, and each stamp must be positive and no greater than the catalog generation. A mutation writes and synchronizes a complete pending record, atomically renames it over the current record, synchronizes the parent directory, and installs the complete in-memory catalog.

A failure before rename leaves old desired state and routing visible. Rename is the visibility commit point: a failure synchronizing the directory after rename returns `Unavailable` with reason `commit-durability-uncertain`, but installs the same complete renamed state in memory. A versioned mutation adds a `deployment-mutation` structured detail containing `deployment_id`, `object_generation`, `catalog_generation`, `operation` (`apply` or `delete`), and `committed=true`, captured from that exact transaction. For delete, the object stamp is the deleted record's old version. Callers must not assume rollback or mistake a later read for the original mutation's receipt. An unconditional reapply consumes another generation; a conditional retry with the old object version conflicts after a committed update.

Existing format-version-1 catalogs are accepted only after the existing checksum,
manifest and reconstructed-route validation succeeds. Since they have no object
versions, every live deployment deterministically receives that persisted
catalog generation as its initial stamp. Opening does not rewrite the committed
file; the next normal mutation writes version 2 through the existing atomic
publication protocol. An empty legacy generation-zero catalog remains empty.
The fixed initialization marker keeps its existing meaning independently of the
record version. Unsupported or inconsistent persisted version data is corruption,
never silently reset state.

Startup ignores interrupted pending files, bounds reads, verifies the format and checksum, decodes and validates deployments, verifies their releases, deterministically rebuilds indexes with the stored generation and timestamp, and compares the rebuilt snapshot with the persisted one. Missing releases, corrupt complete state, or changed contract metadata fail startup rather than silently changing routes. A valid checksum does not bypass the reconstructed-snapshot comparison.

The initialization marker distinguishes a new root from loss of an already initialized state file. After synchronizing the complete catalog record and its directory entry, initialization writes `.INITIALIZED.pending`, synchronizes that file, atomically renames it to `INITIALIZED`, then synchronizes the containing directory again. An interruption after creation or during writing leaves only a non-authoritative temporary marker. After acquiring the exclusive root lock, startup removes that regular staging file and completes a missing marker only after verifying/rebuilding the complete catalog. A corrupt completed marker, a marker without its complete state, or a corrupt complete record is still rejected. Existing malformed completed markers are not silently reclassified as staging files.

The directory durability sequence follows the Linux `fsync(2)` requirement to synchronize the containing directory separately from the object: <https://man7.org/linux/man-pages/man2/fsync.2.html>. These guarantees assume successful storage synchronization and the supported local filesystem environment; process-restart tests are not a simulation of every possible power-loss behavior.

## Limits and update cost

Defaults are 100,000 deployment entries, 64 MiB serialized state, 1,000,000 weighted endpoint index entries, 1,024 bytes per route identifier, 4,096 bytes per routing key, 1,000 records per page, and 4 MiB of encoded records per page. These are independent limits; the byte budget can bind before the deployment-count limit. The manifest codec also applies its own document and collection bounds. Pagination's retained index keys and cached record-size entries consume the existing compilation metadata budget.

Compilation charges retained deployment/route metadata and compact compatibility fingerprints as they accumulate. Fingerprint charges include their keys, digest strings, and conservative per-entry bookkeeping; they are checked before insertion. Exact transaction serialization stops at the configured byte budget, including JSON escaping, before publication. Resolution is bounded by configured input sizes, index sizes, and selected manifest metadata; it is not a hard real-time API. `max_state_bytes` is not a total-process heap limit.

Updates rebuild and persist a complete bounded catalog and verify each distinct referenced release. Use atomic batches rather than repeated single-deployment updates for bulk changes. The compiler sorts borrowed deployment references by `(release digest, deployment ID)` and processes one release group at a time. Each release is fetched exactly once per compilation. Its full artifact metadata is dropped **before** fetching the next release; there is no aggregate full-artifact cache. Component bytes are dropped immediately after verification and are never retained in routing snapshots or prepared for execution.

Canonical contract trees and encoded bytes exist only while fingerprinting one contract of the current release. The per-release cache and the cross-release tenant/service compatibility map retain only computed SHA-256 fingerprints, not canonical trees, documentation, attributes, or type descriptions. The current release's fingerprints are reused across all its deployments. The transient metadata working set is therefore bounded by one release's metadata and its canonicalization scratch space, not the sum across releases. With the production artifact repository, per-release metadata reads retain their configured bound (4 MiB by default); custom artifact repositories must also bound individual fetch results. This does not impose a global limit on concurrent management calls or explicitly pinned old snapshots; their scheduling and lifetimes remain the embedding node's responsibility.

Grouping is an internal compilation order only. Published services and revision candidates keep their existing deterministic ordering. Canonical schema fingerprints, revision IDs and weighted selection remain unchanged by the versioned management port; the persisted record upgrade is described above.

## Regression and acceptance coverage

Run `cargo test -p latent-control-store --lib --locked`. The maintained catalog acceptance job runs this suite alongside the artifact-catalog suite; no issue-specific workflow is needed.

Coverage includes tenant and named-route isolation, missing endpoints, invalid weights, duplicate IDs, unsupported backends/state models, contract-schema conflicts, release-integrity failures, generation exhaustion, deterministic weighting across reordered input and restart, revision identity, pinned readers, coordinated concurrent readers, stale concurrent writers, bounded mutation/read paths, complete-publication validation, checksummed-state tampering, interrupted writes, uncertain directory synchronization, initialization recovery, and reopening the real artifact and deployment catalogs together.

Versioned-mutation regressions exercise caller preconditions at commit, competing
writers, delete/recreate, unrelated writes, exact receipts and restart. Tiny
interleaved tenant/service fixtures count selected entries and cloned manifests
directly, verify no artifact fetches during paging, and cover exact record-byte
limits, continuation order, invalid scopes/tokens, and expiry on publication or
reopen. They do not require a large catalog or execution workload. Generated
management-adapter integration coverage remains #37 work.

Thread-local filesystem failpoints exercise empty and partial staging-marker writes, marker file synchronization, rename, and directory synchronization. Traces assert the initialization ordering and synchronization of every component of a nonexistent nested path. Failures at each ancestor stop initialization, and retries with the now-existing path repeat the full synchronization sequence. Completed-marker/state corruption and loss remain hard errors. These are operation-order and fault-propagation tests, not physical power-cut experiments.

On Linux, an isolated, deadline-supervised test applies and resolves 1,000 dormant deployments against the real release repository. It compares process thread, child-process, file-descriptor, and socket counts before and after, and verifies that the deployment directory still contains only its three fixed files. Routing metadata may scale; runtime resources must not.

A separate memory regression uses fresh publication, application, and restart subprocesses with 32 real persisted releases, each containing 3 MiB of interface documentation. It tests both distinct releases in one scope and one shared release across distinct scopes, catching aggregate artifact retention and aggregate canonical-tree retention independently. Each resulting catalog is smaller than 512 KiB, and peak resident growth during apply/reopen must stay below a fixed 64 MiB regression allowance. That allowance is test headroom, not an API heap quota. A grouping regression also verifies one fetch per distinct digest despite interleaved deployment IDs.
