# Phase 1 embedded deployment catalog and local routing

The standalone control plane uses `EmbeddedDeploymentCatalog` as the concrete implementation of `DeploymentStore`, `TenantDeploymentStore`, `RouteCompiler`, `RouteSnapshotSource`, `RouteSnapshotPublisher`, `CompiledRouteStore`, and `RouteResolver`.

The issue #5 implementation is additive to the existing control-store contract. `ReleaseCatalog`, `BindingStore`, `TriggerStore`, `ControlPolicyStore`, `NodeInventoryStore`, `ControlAuditStore`, and the original `DeploymentStore` and `CompiledRouteStore` method signatures remain available. Tenant-filtered deployment listing is exposed through the separate `TenantDeploymentStore` extension port.

## Runtime and resource topology

The catalog is process-local and directory-backed. It creates one mutation mutex, one short-held publication lock, immutable `Arc` snapshots, and bounded generation files. It creates no listener, worker, child process, thread, socket, execution cell, or other resource per deployed service. A service remains latent until a later invocation path asks the selected capsule runtime to execute it.

Readers clone the currently published `Arc<PublishedState>` while holding a read lock briefly. Resolution then runs entirely against that immutable generation. Writers compile and validate a complete candidate before persistence, write the complete state before its commit marker, and replace the published `Arc` once. Readers therefore see either the old generation or the new generation, never a partially updated deployment/route pair.

Default standalone bounds are:

- 200,000 deployment manifests;
- 256 MiB per complete persisted generation;
- 64 retained complete generations.

All three bounds are configurable through `EmbeddedCatalogOptions` and must be non-zero.

## Apply and delete transaction

An apply or delete is serialized with the catalog mutation mutex:

1. Clone the current immutable deployment map.
2. Apply the requested candidate mutation.
3. Validate every deployment and referenced release.
4. Enforce the tenant/service namespace invariant across the complete candidate state.
5. Compile the entire tenant-safe route snapshot with generation `current + 1`.
6. Build and validate the resolver index and canonical snapshot digest.
7. Persist deployment manifests and the complete snapshot as one checksummed generation.
8. Publish the generation by atomically renaming its commit marker. This rename is the sole transaction commit point.
9. Reconcile the process-wide immutable state to the committed generation before returning success, recovering the publication lock if the initial replacement fails.
10. Synchronize the commit directory and prune generations beyond the configured retention bound as best-effort post-commit maintenance.

Any failure before the commit-marker rename leaves the old deployment set, route snapshot, and generation visible. Once the marker rename succeeds, the mutation is caller-visible as committed and the in-memory generation is reconciled before return; a later directory-synchronization or first publication-attempt failure cannot be reported as a rolled-back transaction. A state file without a matching commit marker is an invisible orphan and is removed during restart or later maintenance.

Applying an exact duplicate ID returns `AlreadyExists` with `duplicate-deployment-id`. A changed deployment may replace the same ID only inside the same tenant, namespace, service, and normalized default/named route identity. Moving an existing deployment ID between namespaces therefore returns `StateConflict` with `deployment-identity-conflict`.

## Release admission boundary

Before a candidate can become visible, each `DeploymentManifest.release` is fetched by its exact immutable digest from the trusted `ArtifactRepository`. Admission verifies:

- the artifact descriptor, capsule manifest, and requested digest agree;
- the execution backend is the Wasmtime Component Model backend;
- the capsule state model is stateless;
- explicit release tenant constraints agree with the deployment;
- a namespace-scoped release is deployed in exactly that namespace, including rejection of a scoped-release/unscoped-deployment combination;
- release service metadata agrees with the deployment service;
- deployment resource limits do not exceed the release ceiling;
- every declared export has trusted contract metadata and at least one callable function;
- all revisions in one weighted route expose the same contract/function surface.

The last rule means deterministic weighting can never select a revision that lacks the contract/function being invoked.

## Tenant and namespace isolation invariant

The hardened Phase 1 invocation target carries tenant, service, optional route, contract, and function. It does not carry a separate namespace field. The embedded compiler therefore enforces the equivalent explicit invariant permitted by issue #5:

```text
for each (tenant, service), all deployments across every default and named route
must have exactly the same namespace identity, including scoped versus unscoped
```

Compilation rejects mixed namespaces before a snapshot can become visible. `RouteIndex::build` independently reconstructs the namespace identity from revision attributes and rejects persisted or externally published snapshots that violate the invariant. Consequently, the effective route key cannot select across namespaces even though namespace is not repeated in `InvocationTarget`.

A service route is keyed by:

```text
(tenant, service, optional canonical named route)
```

The default route has no name. A named route is selected with the deployment annotation `latent.dev/route`. Deployment and invocation route names are trimmed once. Empty or whitespace-only named routes are invalid. Resolution uses the same canonical route value for index lookup, deterministic selection hashing, returned pinned targets, and error details. It never falls back across tenants or from a named route to the default route.

The invocation target also contains the contract and function. A route that exists but does not expose that pair returns `IncompatibleContract` with `contract-function-mismatch` rather than resolving an unusable revision.

## Deterministic revision identity and weighting

A `RevisionId` is a BLAKE3 identity over a length-delimited canonical representation of the complete deployment configuration, its immutable release digest, and its sorted contract/function surface. Namespace is included in the canonical deployment representation. Map ordering and placement list ordering are normalized, so the same effective deployment receives the same revision identity on another standalone node or after restart. A material change to deployment configuration receives a different revision identity.

Revisions are sorted by `RevisionId`. Selection hashes the compiled route's tenant, service, canonical route, requested contract, requested function, and optional routing key, maps the hash into the sum of positive route weights, and selects by cumulative weight. The same complete route set and routing key therefore select the same pinned `(RevisionId, ReleaseDigest)` independent of deployment insertion order or harmless surrounding whitespace in an invocation route.

Each individual weight must be between 1 and 10,000 and the aggregate for one route must be between 1 and 10,000.

## Durable complete generations

The directory layout is:

```text
<root>/
  generations/
    00000000000000000001.json
  commits/
    00000000000000000001.commit
```

A generation file contains the complete deployment map and complete route snapshot in a versioned envelope. The envelope and commit marker both carry a BLAKE3 checksum of the canonical persisted state. Files are written to a same-directory temporary file, synchronized, and renamed atomically. The state rename and its directory synchronization complete before marker construction. The commit-marker rename is the only commit point; its following directory synchronization is durability maintenance and cannot change the caller-visible transaction outcome.

On restart, the highest committed generation is loaded, checksum-verified, converted into domain types, namespace-invariant checked, and indexed. Corruption in the latest committed generation is a hard startup error; the catalog does not silently route from unverifiable state. Uncommitted generation files and interrupted temporary files in both `generations/` and `commits/` are ignored and removed. Valid state files and commit markers are never selected by temporary-file cleanup. The zero generation is an in-memory empty baseline and is never persisted.

`RouteSnapshotSource::watch(after)` is intentionally a bounded local replay of retained complete snapshots. It is not a distributed watch protocol.

## Stable error kinds

The implementation returns structured `PlatformError` details with stable kinds, including:

| Condition | Code | Detail kind |
| --- | --- | --- |
| Referenced release absent | `NotFound` | `missing-release` |
| Exact deployment duplicate | `AlreadyExists` | `duplicate-deployment-id` |
| ID crosses tenant/namespace/service/route identity | `StateConflict` | `deployment-identity-conflict` |
| Unsupported backend | `InvalidArgument` | `unsupported-execution-backend` |
| Unsupported state model | `InvalidArgument` | `unsupported-state-model` |
| Release/deployment tenant conflict | `StateConflict` | `tenant-scope-conflict` |
| Release/deployment namespace conflict | `StateConflict` | `namespace-scope-conflict` |
| Mixed namespaces for one tenant/service | `StateConflict` | `namespace-route-identity-conflict` |
| Empty invocation or deployment route name | `InvalidArgument` | `invalid-route-name` |
| Invalid revision weight | `InvalidArgument` | `invalid-route-weight` |
| Invalid aggregate weight | `InvalidArgument` | `invalid-route-weight-total` |
| Weighted contract disagreement | `IncompatibleContract` | `weighted-contract-surface-mismatch` |
| Missing tenant-safe route | `RouteUnavailable` | `route-not-found` |
| Missing contract/function | `IncompatibleContract` | `contract-function-mismatch` |
| Non-sequential publication | `StateConflict` | `non-monotonic-route-generation` |
| Persisted checksum mismatch | `CorruptArtifact` | `route-state-checksum-mismatch` |
| Invalid snapshot digest | `CorruptArtifact` | `route-snapshot-digest-mismatch` |
| Persisted namespace invariant violation | `CorruptArtifact` | `compiled-namespace-route-identity-conflict` |

## Coverage

The embedded catalog tests cover apply/get/list/delete, original and additive store ports, failed-transaction rollback, duplicate IDs, tenant isolation, mixed-namespace rejection, namespace-changing updates, scoped-release admission, default and named routes, canonical invocation routes, whitespace-only route rejection, missing routes and functions, monotonic generations, deterministic weighting, insertion-order independence, revision identity, restart recovery, concurrent whole-snapshot replacement, compiler/publisher/source behavior, bounded replay/retention, state and marker temporary-file cleanup, post-marker directory-sync failure reconciliation, post-commit in-memory publication failure recovery, subsequent mutation and restart consistency, and semantic verification of the checked-in route snapshot digest.
