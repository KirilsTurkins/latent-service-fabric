# Phase 1 local release catalog

The Phase 1 standalone node owns one local release-catalog root exclusively for the lifetime of its `DirectoryArtifactRepository`. Ownership is acquired with an operating-system file lock on `.catalog.lock` before temporary cleanup or index rebuild. A second live opener fails with `unavailable`; the OS releases the lock automatically on normal close or process exit/crash. Never unlink `.catalog.lock` while a repository is open: cooperating owners must lock the same file.

## Layout and publication

Completed releases live under `releases/<sha256>/` and contain `metadata.json`, canonical `manifest.json`, `component.wasm`, and a `COMPLETE` marker. Publication validates the manifest, component identity, descriptor bounds and contract metadata before creating a private directory under `.tmp/`. It fsyncs every file and the temporary directory, renames the complete directory into its immutable digest location, then fsyncs `releases/` before adopting the descriptor into the in-memory index.

Every successful publication/adoption path uses the same sync-and-adopt operation. Thus `publish -> Ok` implies immediate eligibility for `resolve`, `fetch`, and `list` on that handle. Identical publication is idempotent; different content under an existing digest or reference is rejected.

### Indeterminate durability and the mutation gate

A parent-directory sync failure after rename is returned as a publication failure. The completed destination may remain on disk while a newly published release remains hidden from that handle's readers. Under the writer mutex, the repository retains the pending release digest and rejects publications of any other digest with `unavailable`. This includes an otherwise nonconflicting release: the pending directory must not be bypassed for reference uniqueness, entry capacity, or aggregate index-byte capacity.

Retrying the pending artifact verifies the existing complete entry, re-syncs `releases/`, and adopts it before clearing the gate. A changed artifact with the same digest is not an identical retry and is rejected. Repeated sync/adoption failures keep the gate closed. Previously indexed releases remain readable. The alternative recovery is to drop all references to the repository and reopen its root; rebuild validates and accounts for every completed entry and syncs `releases/` before allowing new mutations. An unsuccessful publication acknowledgment therefore means the release may be recovered after restart, not that its bytes were rolled back.

The root lock means `.tmp` cleanup cannot delete another live repository handle's active stage. On startup, once ownership is acquired, all `.tmp` contents are treated as abandoned crash debris and removed. Final directories without `COMPLETE` are ignored as incomplete recovery debris and are never exposed. This protocol assumes cooperating publishers and a local filesystem supporting directory fsync and atomic directory rename; manual changes to an owned root are outside that protocol.

## Bounds and the metadata codec

The repository has independent bounds for completed index entries, conservatively accounted retained index bytes, per-descriptor bytes, list entry count, list response bytes, persisted metadata bytes, component bytes, and startup recovery-directory scans. Defaults are 250,000 completed entries, 64 MiB accounted index bytes, 1,000 rows per page, 4 MiB materialized descriptor bytes per page, 256 KiB per descriptor, 4 MiB persisted metadata, 256 MiB component bytes, and 1,000,000 recovery directories. Limits are simultaneous: the byte budget can be exhausted before the entry count.

Index accounting charges four times the canonical serialized descriptor size plus 1 KiB per release. Together with the independent entry-count and descriptor-size bounds, this bounds variable-size strings, annotations, layers, map/vector element counts, and duplicate reference-key retention. The accounting budget is not a measurement of total process RSS. Oversized descriptors and aggregate index exhaustion are rejected before staging a new release.

Contract field types have a maximum structural depth of 32 (the root type counts as one) and an aggregate limit of 16,384 type nodes across all contract parameters and results in an artifact. These checks precede recursive conversion and serialization, and apply again when reading persisted metadata. All recursive variants, including both result branches and tuple elements, participate. The JSON reader retains its normal recursion protection. Publication also decodes the exact serialized metadata bytes with the production decoder and checks descriptor/contract equality before writing any files; accepting data that fetch or reopen cannot deserialize is not permitted.

Startup reads inspect file length before allocation and reject persisted metadata, manifests, or components that exceed their configured limits. Incomplete final directories count only toward the separate recovery-scan bound, never the completed-release index quota. Listing is served from the ordered in-memory digest index without directory scans per request, with ascending digest order and both row-count and descriptor-byte bounds.

## Trust boundary

Phase 1 is locally trusted. The catalog validates and canonicalizes capsule manifests and verifies SHA-256 agreement between transferred component bytes, the manifest component digest, and the immutable release digest. It does not claim signature, provenance, SBOM, registry-authentication, OCI, or trusted-AOT verification; those remain later-phase work. Registration validates catalog data without preparing or instantiating the component.

## Execution-resource invariant and acceptance evidence

Registration, recovery, resolve, fetch, and list are implemented inside `latent-artifacts`, which has no scheduler or execution-backend dependency. These operations do not instantiate capsules, prepare Wasmtime state, acquire execution cells, start child processes or service workers, or open listening sockets. One ownership-lock file descriptor belongs to the catalog root, not to each release.

The fast `one_hundred_thousand_index_adoptions_are_bounded` unit test tests only index accounting/adoption. It intentionally provides no evidence of durable publication or runtime topology.

The separate Linux `latentd` integration target `catalog_scale` exercises the public production `ArtifactRepository` interface. Its isolated publisher process registers 100,000 distinct synthetic component artifacts with real manifest validation, digest verification, metadata encoding, staging, file/directory syncs, atomic renames, and index adoption. It lists, resolves and fetches every artifact. After that process exits, a second process opens the same on-disk root, rebuilds the full catalog, and lists, resolves and fetches all 100,000 artifacts byte-for-byte. No test-only publication or persistence bypass is used.

Each child owns a real fixed cell pool with two generic node-owned cells before establishing its baseline. The probe measures process identity, child processes across all tasks, thread count, owned socket descriptors, owned TCP/Unix listening sockets, open file descriptors, pool capacity/availability, active leases, queue depth and quarantined cells. Measurements are checked after opening, at publication checkpoints, after complete verification and after closing. JSON output reports baseline/after measurements, zero-growth assertions for service-specific resources, and fixed helpers separately: the isolated probe process, its observed harness threads, two generic cells, and one catalog lock FD. These are controlled catalog-integration measurements, not a claim to benchmark the full running node or Wasmtime allocation behavior.

The scale probe opts into a 256 MiB index-accounting budget to fit 100,000 records. It runs on the ordinary disk-backed temporary directory with production syncs enabled. Ordinary unit-test invocations compile but ignore the expensive integration tests. The maintained `Durable catalog acceptance` job in the existing CI workflow explicitly runs the probe and retains its log, without adding an issue-specific workflow.

Run the acceptance probe explicitly with:

```sh
cargo test -p latentd --test catalog_scale --locked production_catalog_100k -- --exact --ignored --nocapture --test-threads=1
```

Both subprocess waits have deadlines and collect diagnostic logs without unbounded pipe buffering. The publication-visibility unit tests likewise observe writer errors/panics and deadlines; a deterministic coordination test forces completion between an absent resolve and the writer-status check, then verifies a fresh resolve/fetch after joining.

## Recovery procedure

1. For a post-rename publication error, retry the exact pending artifact; do not assume failure removed its completed directory. Other publications receive `unavailable` until reconciliation.
2. Alternatively stop the standalone node and drop all repository handles so `.catalog.lock` is released. Preserve the root before any manual repair.
3. Remove only known abandoned `.tmp` content if manual cleanup is necessary; normal startup performs this automatically after acquiring ownership.
4. Do not promote directories lacking `COMPLETE` manually. Rebuild ignores them; they may be inspected or removed offline.
5. Reopen the repository. Rebuild checks bounded/readable contract metadata, canonical manifests, digest-directory identity, component bytes, reference uniqueness and all configured limits. It syncs the release directory before exposing the rebuilt index.
6. Conflicting completed mappings, corrupt completed data or unsupported metadata are operator-visible open failures, never silently selected records. Preserve evidence and repair/remove the offending completed entry only offline; do not bypass bounds or JSON recursion protection to force startup.
