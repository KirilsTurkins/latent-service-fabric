# Phase 1 local release catalog

The Phase 1 standalone node owns one local release-catalog root exclusively for the lifetime of its `DirectoryArtifactRepository`. Ownership is acquired with an operating-system file lock on `.catalog.lock` before temporary cleanup or index rebuild. A second live opener fails with `unavailable`; the OS releases the lock automatically on normal close or process exit/crash.

## Layout and publication

Completed releases live under `releases/<sha256>/` and contain `metadata.json`, canonical `manifest.json`, `component.wasm`, and a `COMPLETE` marker. Publication writes a private directory under `.tmp/`, fsyncs every file and the temporary directory, renames the complete directory into its immutable digest location, then fsyncs `releases/` before the descriptor is adopted into the in-memory index.

A parent-directory sync failure after rename is returned as a publication failure. The complete destination may remain on disk, but it is not indexed by that handle. Retrying the same artifact verifies the existing entry, re-syncs the parent directory, and only then adopts it into the index. Consequently every successful publication/adoption path has the same finalization step, and `publish -> Ok` implies the release is immediately eligible for `resolve`, `fetch`, and `list` on that repository handle.

The root lock means `.tmp` cleanup cannot delete another live repository handle's active stage. On startup, once ownership is acquired, all `.tmp` contents are treated as abandoned crash debris and removed. Final directories without `COMPLETE` are ignored as incomplete recovery debris and are never exposed.

## Bounds

The repository has independent explicit bounds for completed index entries, conservatively accounted retained index bytes, per-descriptor bytes, list entry count, list response bytes, persisted metadata bytes, component bytes, and startup recovery-directory scans. Defaults are 250,000 completed entries, 64 MiB accounted index bytes, 1,000 rows per page, 4 MiB materialized descriptor bytes per page, 256 KiB per descriptor, 4 MiB persisted metadata, 256 MiB component bytes, and 1,000,000 recovery directories.

Index accounting charges four times the canonical serialized descriptor size plus 1 KiB per release. Together with the independent entry-count and descriptor-size bounds, this places a deterministic upper bound on variable-size strings, annotations, layers, map/vector element counts, and duplicate reference-key retention. Oversized descriptors and aggregate index exhaustion are rejected before a new release becomes visible or is staged.

Startup reads inspect file length before allocation and reject persisted metadata, manifests, or components that exceed their configured limits. Incomplete final directories count only toward the separate recovery-scan bound; they never consume the completed-release index quota.

Listing is served from the in-memory ordered digest index and does not scan the release directory per request. Pages are deterministic in ascending release-digest order and are bounded by both row count and descriptor bytes.

## Trust boundary

Phase 1 is locally trusted. The catalog validates and canonicalizes capsule manifests and verifies SHA-256 agreement between the transferred component bytes, manifest component digest, and immutable release digest. It does not claim signature, provenance, SBOM, registry-authentication, OCI, or trusted-AOT verification; those remain later-phase work.

## Execution-resource invariant

Registration, recovery, resolve, fetch, and list are implemented entirely inside `latent-artifacts`; the crate does not depend on the scheduler or execution backend and these paths do not instantiate a capsule, prepare Wasmtime state, allocate execution cells, create service-specific worker threads, start child processes, or open listening sockets. The scale acceptance probe runs in an isolated child test process and drives the repository's common durable-adoption/finalization path for 100,000 unique dormant descriptors while asserting unchanged process identity, child-process count, thread count, and socket-descriptor count. Fixed catalog-owned runtime helpers are zero.

## Recovery procedure

1. Stop the standalone node so it releases `.catalog.lock`.
2. Preserve the catalog root before manual repair.
3. Remove only known abandoned `.tmp` content if manual cleanup is necessary; normal startup performs this automatically after acquiring ownership.
4. Do not promote directories lacking `COMPLETE` manually. They are ignored by rebuild and may be inspected or removed offline.
5. Reopen the repository. Rebuild validates completed metadata, canonical manifests, digest-directory identity, component bytes, reference uniqueness, and all configured resource bounds before replacing the live index.
6. Any conflicting completed reference/digest mapping or corrupt completed entry is an operator-visible open failure rather than silently selecting one record.
