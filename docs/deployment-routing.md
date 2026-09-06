# Embedded deployment catalog and local routing

`latent-control-store::DirectoryDeploymentRepository` is the standalone, node-owned implementation of `DeploymentStore`, `CompiledRouteStore`, `RouteCompiler`, `RouteSnapshotPublisher`, `RouteSnapshotSource`, and `RouteResolver`.

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

routes.apply(validated_deployment).await?;
let resolved = routes.resolve(&invocation_target, Some(routing_key))?;
// Pass this owned ResolvedRevision to admission/execution. Do not resolve it again.
```

Management methods perform synchronous local filesystem I/O despite implementing asynchronous trait seams. Run them on a control-plane worker, not on an invocation worker. They are trusted-local management interfaces, not tenant-authenticated HTTP endpoints. An API adapter must authenticate and authorize management operations before calling the global `get`, `list`, `apply`, or `delete` methods.

The directory has one exclusive advisory owner lock. A second independently opened handle is rejected; clone an `Arc` instead. Linux local filesystems with atomic same-directory rename, file synchronization, directory synchronization, and file locking are the supported persistence environment. The directory must remain under node ownership; the checksum and advisory lock are not protection against a malicious host administrator.

## Deployment and route identity

Deployment IDs are globally unique within one catalog. `apply` is an upsert, but an existing ID cannot change tenant, namespace, or service. `apply_many` rejects repeated IDs within the same batch, rather than silently using the last occurrence. The ID `default` is reserved for the default route.

The effective route key is `(tenant, service, route)`. Because `InvocationTarget` has no namespace field, the compiler enforces an explicit invariant: **all deployments for the same `(tenant, service)` pair must use the same namespace, including whether a namespace is absent**. Ambiguous namespace combinations fail with `PermissionDenied`. Different tenants can freely use the same service ID and different namespaces without collision.

Every deployment contributes to two route names: the service's `default` route and a named route equal to that deployment's ID. An absent optional route means `default`. An unknown supplied route fails; it never falls back to another route or tenant. A named deployment route selects only that deployment.

Within the selected route, candidates must export the requested contract and function. Missing routes return `RouteUnavailable`; an existing route without the requested endpoint returns `IncompatibleContract`. Exported contracts require complete function metadata. Duplicate contract, interface, or function IDs are rejected. Deployments for the same tenant/service cannot supply conflicting canonical schemas for the same contract ID, even when a descriptor's claimed digest is unchanged.

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

Each successful apply, batch apply, delete, or explicit snapshot publication advances the generation exactly once. Empty batches are no-ops. Generation exhaustion returns `ResourceExhausted`, never wraps to zero.

Writers compile and validate outside the publication lock. Commit compares the expected generation with the live one under a writer mutex. Concurrent stale writers receive retryable `StateConflict` and must retry from the new desired state; they cannot overwrite a newer transaction.

Invocation resolution attempts the reader lock once with `try_read`. Contention returns retryable `Unavailable` immediately. A successful lookup performs immutable tree lookups, bounded input hashing, binary search over cumulative weights, and copying of the selected metadata. It performs no artifact fetch, filesystem access, remote control-plane access, compilation, await, or polling. The ordinary lookup borrows the catalog so it cannot become the final owner that destroys a retired catalog on the invocation worker.

The writer takes the reader lock only to replace the complete catalog pointer and generation. Large old-catalog destruction occurs outside that lock. A reader observes a complete old or complete new catalog, never an in-place mutation. An explicitly pinned view needs no reader lock; its final drop may release the retained metadata, so applications requiring strict teardown latency should release long-lived pins on their control-plane worker.

`RouteCompiler::compile` validates the supplied previous snapshot against the current complete snapshot and creates the next generation. `publish` and `CompiledRouteStore::put` accept only the exact next-generation snapshot compiled from current desired state. Arbitrary, partial, altered, or stale snapshots are rejected.

`RouteSnapshotSource::watch` is an immediate, coalescing local read: it returns either the current complete snapshot when newer than the cursor, or an empty vector. A future cursor is invalid. It does not maintain a per-service subscription, wait for a later generation, or retain unbounded history. `CompiledRouteStore::get` retains only the current generation. Local binding/policy compilation is outside this deployment-only implementation; binding resolution fails explicitly with `RouteUnavailable`.

## Persistence and recovery

The fixed node-owned files are `catalog.json`, `INITIALIZED`, and `.catalog.lock`. A mutation temporarily creates `.catalog.pending`. Deployment identifiers are metadata, never filesystem paths.

One versioned JSON record contains both desired deployments and the complete compiled snapshot. Its SHA-256 checksum covers the canonical payload. A mutation writes and synchronizes a complete pending record, atomically renames it over the current record, synchronizes the parent directory, and installs the complete in-memory catalog.

A failure before rename leaves old desired state and routing visible. Rename is the visibility commit point: a failure synchronizing the directory after rename returns `Unavailable` with reason `commit-durability-uncertain`, but installs the same complete renamed state in memory. Callers must inspect the current generation after this error rather than assuming rollback. Reapplying the same desired state is safe but consumes another generation.

Startup ignores interrupted pending files, bounds reads, verifies the format and checksum, decodes and validates deployments, verifies their releases, deterministically rebuilds indexes with the stored generation and timestamp, and compares the rebuilt snapshot with the persisted one. Missing releases, corrupt complete state, or changed contract metadata fail startup rather than silently changing routes. A valid checksum does not bypass the reconstructed-snapshot comparison.

The initialization marker distinguishes a new root from loss of an already initialized state file. Startup completes a missing marker when initialization stopped after the first state rename. A corrupt marker or a marker without its complete state is rejected.

## Limits and update cost

Defaults are 100,000 deployment entries, 64 MiB serialized state, 1,000,000 weighted endpoint index entries, 1,024 bytes per route identifier, and 4,096 bytes per routing key. These are independent limits; the byte budget can bind before the deployment-count limit. The manifest codec also applies its own document and collection bounds.

Compilation charges retained deployment/route metadata as it is accumulated. Exact transaction serialization stops at the configured byte budget, including JSON escaping, before publication. Resolution is bounded by configured input sizes, index sizes, and selected manifest metadata; it is not a hard real-time API.

Updates rebuild and persist a complete bounded catalog and verify each distinct referenced release. Use atomic batches rather than repeated single-deployment updates for bulk changes. The release repository seam returns component bytes during control-plane verification; those bytes are dropped immediately and never retained in routing snapshots or prepared for execution.

## Regression and acceptance coverage

Run `cargo test -p latent-control-store --lib --locked`. The maintained catalog acceptance job runs this suite alongside the artifact-catalog suite; no issue-specific workflow is needed.

Coverage includes tenant and named-route isolation, missing endpoints, invalid weights, duplicate IDs, unsupported backends/state models, contract-schema conflicts, release-integrity failures, generation exhaustion, deterministic weighting across reordered input and restart, revision identity, pinned readers, coordinated concurrent readers, stale concurrent writers, bounded mutation/read paths, complete-publication validation, checksummed-state tampering, interrupted writes, uncertain directory synchronization, initialization recovery, and reopening the real artifact and deployment catalogs together.

On Linux, an isolated, deadline-supervised test applies and resolves 1,000 dormant deployments against the real release repository. It compares process thread, child-process, file-descriptor, and socket counts before and after, and verifies that the deployment directory still contains only its three fixed files. Routing metadata may scale; runtime resources must not.
