# Phase 1 local release catalog

`latent-artifacts::DirectoryArtifactRepository` implements the local release
catalog used by the [Phase 1 standalone node](../reference/standalone-node.md).
The repository is also available directly as a Rust API.
Its owner holds one local release-catalog root exclusively for the lifetime of
the repository. Ownership is acquired with an operating-system file lock on
`.catalog.lock` before temporary cleanup or index rebuild. A second live opener
fails with `unavailable`; the OS releases the lock automatically on normal
close or process exit/crash. Never unlink `.catalog.lock` while a repository is
open: cooperating owners must lock the same file.

The supported persistence environment is a Linux local filesystem with file
locking, atomic same-directory rename, and file/directory synchronization, as
for the [deployment repository](../deployment-routing.md).

`open` may create a nonexistent nested root. It anchors relative input against
the current directory once before filesystem work, then canonicalizes that path and
synchronizes every directory from the catalog root through the filesystem root,
leaf first, before acquiring ownership or initializing catalog state. The same
sequence runs for an existing root: an interrupted or failed earlier open may
have left directory entries present without making them durable. All ancestor
directories must be readable and support directory synchronization. Pre-existing
symlinks and external mount provisioning remain the operator's responsibility.

If any ancestor synchronization fails, opening returns retryable `Unavailable`
with message `catalog-path-durability-uncertain`. Initialization and temporary
cleanup do not proceed. Created directories remain in place; retrying the same
path repeats the complete synchronization chain before normal ownership,
layout initialization and recovery. No catalog handle or successful publication
is acknowledged through a failed open. These guarantees assume the local
filesystem and storage honor successful synchronization, as in the deployment
repository.

The handle retains this canonical absolute path, and `root()` returns it. A
later process working-directory change cannot redirect publication, recovery or
cleanup away from the directory whose ownership lock the handle holds.

## Layout and publication

Completed releases live under `releases/<sha256>/` and contain `metadata.json`, canonical `manifest.json`, `component.wasm`, and a versioned `COMPLETE` integrity record. Publication validates the manifest, component identity, descriptor bounds, contract metadata and recovery-directory capacity before creating a private directory under `.tmp/`. It writes and fsyncs the payload files followed by the completion record, fsyncs the temporary directory, and renames that complete directory into its immutable digest location. It verifies the stored entry and fsyncs `releases/` before adopting the descriptor into the in-memory index.

Every successful publication/adoption path uses the same sync-and-adopt operation. Thus `publish -> Ok` implies immediate eligibility for `resolve`, `fetch`, and `list` on that handle. Identical publication is idempotent; different content under an existing digest or reference is rejected.

### Completion record and immutable metadata

`COMPLETE` must be a regular file, not a directory or symbolic link. It contains canonical JSON with these fields in the listed order:

| Field | Meaning |
| --- | --- |
| `format_version` | Integer `1`, identifying this completion-record format. |
| `component_digest` | The release's `sha256:` digest of component bytes. |
| `component_size_bytes` | Component byte length. |
| `metadata_digest` | SHA-256 of the exact stored `metadata.json` bytes, covering the descriptor and all contract metadata. |
| `manifest_digest` | SHA-256 of the exact canonical `manifest.json` bytes. |

The record has a fixed 1 KiB maximum, independent of configurable payload limits. Unknown versions or fields, duplicate fields, noncanonical serialization, missing or damaged records, and integrity mismatches are corruption errors. Verification checks the component digest against the record, descriptor, manifest and actual bytes, and checks byte length against the record and descriptor. The directory name must match the release digest. Recovery, fetch, identical retries and initial publication all verify before returning or adopting a completed artifact. Valid JSON alone cannot make a changed descriptor, contract or manifest acceptable.

The release identity remains SHA-256 of component bytes. Metadata fingerprints provide accidental-corruption detection under the existing locally trusted filesystem boundary; they do not authenticate a publisher or protect against an administrator who can replace both data and integrity records.

### Compatibility with legacy catalogs

Earlier catalogs wrote the literal `complete\n` marker without metadata fingerprints. Opening a legacy catalog returns `CorruptArtifact` with message `legacy catalog completion marker is unsupported`. A mixed legacy/new completed catalog also fails opening. The reader preserves committed files and never generates a new integrity record from unverified legacy contents.

To move an existing catalog forward, stop its owner and retain the entire old root. Re-register the trusted original component, manifest, descriptor and contracts through `ArtifactRepository::publish` into a fresh root, then open the application against that verified root. Do not manufacture completion records from possibly damaged old metadata or overwrite the old root during recovery. This compatibility policy does not change component digests or automatically migrate stored files.

### Indeterminate durability and the mutation gate

A verification, parent-directory sync or index-adoption failure after rename is returned as a publication failure. The completed destination may remain on disk while a newly published release remains hidden from that handle's readers. Under the writer mutex, the repository records the pending release digest before verifying the destination and rejects publications of any other digest with `unavailable`. This includes an otherwise nonconflicting release: the pending directory must not be bypassed for reference uniqueness, entry capacity, aggregate index-byte capacity, or recovery-directory capacity.

Retrying the pending artifact verifies the existing complete entry, re-syncs `releases/`, and adopts it before clearing the gate. A changed artifact with the same digest is not an identical retry and is rejected. Repeated sync/adoption failures keep the gate closed. Previously indexed releases remain readable. The alternative recovery is to drop all references to the repository and reopen its root; rebuild validates and accounts for every completed entry and syncs `releases/` before allowing new mutations. An unsuccessful publication acknowledgment therefore means the release may be recovered after restart, not that its bytes were rolled back.

The root lock means `.tmp` cleanup cannot delete another live repository handle's active stage. On startup, once ownership is acquired, all `.tmp` contents are treated as abandoned crash debris and removed, whether their completion record is absent, partial or complete. A digest-named final directory must contain a valid record: publication writes the record before the final rename, so a missing record is corruption and must not silently erase a release from recovery. Non-digest directories with no completion record remain invisible incomplete debris and count toward recovery capacity. This protocol assumes cooperating publishers and a local filesystem supporting directory fsync and atomic directory rename; manual changes to an owned root are outside that protocol.

## Bounds and the metadata codec

The repository has independent bounds for completed index entries, conservatively accounted retained index bytes, per-descriptor bytes, list entry count, list response bytes, persisted metadata bytes, component bytes, and recovery directories. Defaults are 250,000 completed entries, 64 MiB accounted index bytes, 1,000 rows per page, 4 MiB materialized descriptor bytes per page, 256 KiB per descriptor, 4 MiB persisted metadata, 256 MiB component bytes, and 1,000,000 recovery directories. Limits are simultaneous: the byte or directory budget can be exhausted before the completed-entry count.

Index accounting charges compact descriptor and manifest-summary strings, vectors and sparse metadata maps, plus 8 KiB per release for the boxed summary, index nodes and bookkeeping. Duplicate digest, reference, tenant and service keys are charged separately before insertion. The default 64 MiB byte ceiling therefore admits fewer entries than the independent 250,000-entry ceiling. This conservative accounting is not a measurement of process RSS. Oversized descriptors and aggregate index exhaustion are rejected before staging a new release.

The index also charges `size_of::<Option<PreparationMetadataFingerprint>>()`
per release, whether its optional stamp is present or absent. Per-repository
accounting includes a conservative 64-byte epoch allocation and the fixed five
atomic verification counters. These charges apply before publication and during
recovery; even an empty repository requires this fixed allowance. Page response
accounting excludes the private stamp because it is not returned in a page.

Contract field types have a maximum structural depth of 32 (the root type counts as one) and an aggregate limit of 16,384 type nodes across all contract parameters and results in an artifact. These checks precede recursive conversion and serialization, and apply again when reading persisted metadata. All recursive variants, including both result branches and tuple elements, participate. The JSON reader retains its normal recursion protection. Publication also decodes the exact serialized metadata bytes with the production decoder and checks descriptor/contract equality before writing any files; accepting data that fetch or reopen cannot deserialize is not permitted.

Startup reads inspect file length before allocation and reject persisted metadata, manifests, or components that exceed their configured limits with `ResourceExhausted`. An oversized completion record returns `CorruptArtifact` under its separate fixed bound. Publication releases caller payload buffers before reading back the stored component for verification. Retained non-digest incomplete directories count only toward the separate recovery-directory bound, never the completed-release index quota. Listing is served from the ordered in-memory digest index without directory scans per request, with ascending digest order and both row-count and descriptor-byte bounds.

### Scoped metadata reads

`get_catalog_entry` and `list_catalog_entries` expose only the authenticated tenant's compact descriptor and manifest summary. Ordered tenant/service indexes select rows without loading components, fetching full artifacts, or scanning unrelated tenants. Trusted local entries with no tenant remain outside these queries. Pages are bounded before cloning and ordered by digest; their fixed-size opaque tokens bind tenant, optional service, visible catalog generation and this open instance. A new visible publication or reopen expires tokens; an identical retry does not. The global content digest remains unique, so another tenant cannot replace its metadata or acquire an alias for the same bytes. See [management services](../reference/management-services.md) for the RPC upload codec and scope conventions.

### Verified preparation snapshots

Verified publication/adoption and recovery compute an optional compact
preparation stamp over the decoded descriptor, canonical manifest and typed
contracts. It preserves Wasmtime's existing ordered `Debug`-stream fingerprint;
the digest, charged bytes and required type depth occupy fixed-size fields.
It is an internal engine-version-scoped identity, not a replacement for the
release digest or persisted `COMPLETE` record. Its independent 16 MiB work bound
and 32-level type bound only determine optimization eligibility: exceeding them
disables the stamp without rejecting an otherwise valid publication.

`ArtifactRepository::preparation_source` defaults to `None`. The directory
implementation exposes a sealed borrowed `ArtifactPreparationSource` that binds
identity lookup and verified fetch to the same concrete owner. Its lookup reads
the bounded index without files or full metadata traversal; an invisible or
missing release is `NotFound`, while a visible unstamped release yields `None`
and requires that source's checked fetch. Pending publication is not exposed.
A custom adapter may delegate a source, but cannot replace that source's fetch.

Each open repository has a distinct epoch. A cloned token retains only that
small epoch allocation, so it cannot prolong the root's ownership lock. Reopen
verifies disk content and issues a new epoch. Reuse is of the verified admitted
snapshot; it does not promise per-invocation detection of external disk changes.
Cache misses, explicit fresh reads and recovery still verify content under the
existing local-filesystem trust boundary. No guest preparation happens during
stamp creation.

`verification_snapshot()` returns five fixed, saturating counters:
`full_fetch_attempts`, `metadata_fetch_attempts`,
`component_verification_attempts`, `component_bytes_hashed`, and
`metadata_fingerprint_attempts`. Attempts include failures once their stage is
entered. Hashed bytes include a prefix processed before a later failure, but
exclude a chunk rejected for exceeding the byte bound. Caller-buffer hashing
during publication is outside these disk-read counters. Snapshot fields are
sampled independently; warm identity lookups change none of them.

### Recovery-directory capacity

`max_recovery_directories` bounds every directory directly under `releases/`, including completed, pending-adoption and retained incomplete directories. Startup records that count under the publication mutex. A new publication checks the same capacity before creating its staging directory; holding the writer mutex reserves the available slot across staging and rename. Rename charges the slot before the parent sync and index adoption, so a post-rename error does not make that slot available to another release. A failure before a destination exists does not consume a slot. Identical publication and pending-release retries reuse their existing directory, including at the limit.

The count is maintained by the exclusive root owner, not recomputed with a per-publication directory scan. Index-entry and recovery-directory limits remain independent: configuring three index entries and two recovery directories is valid, but only two new releases can be published into an empty root. With both limits set to two and one retained incomplete directory, only one new release fits. Further publication returns `resource-exhausted` before staging, while all accepted releases remain retrievable after reopening with the same configuration.

Incomplete directories remain invisible and are not automatically deleted to make room. Stop the owner before inspecting/removing known incomplete debris, then reopen to rebuild the count and reclaim capacity. Live external filesystem changes are not part of the ownership protocol. Regression tests cover both configurations above, a root filled entirely with incomplete entries, rejection before staging access, pending retries/reopen, pre-rename filesystem failures, concurrent publishers competing for the last slot, and offline cleanup followed by publication and reopen.

### Owned preparation reads

`Arc<dyn ArtifactRepository>::owned_preparation_source` optionally delegates
identity, read bounds and blocking fetch to one sealed directory owner. Its
`read_bounds` copies the indexed component length and encoded document ceilings
without disk I/O or descriptor clones. Compiler jobs reserve those inputs before
queueing, then pass explicit ceilings to `fetch_blocking`. Reads intersect the
caller and repository limits and reject file growth before extending retained
buffers beyond the admitted component/document allowance. Completion records,
canonical manifest checks, metadata association and component hashes still apply.

Cloning the source only clones its concrete repository `Arc`. A running compiler
job retains that owner/root lock even after its callers cancel; cached runtimes
and delivered ready pins retain only their small epoch identity. A source with
no compact stamp still owns its fallback fetch. Repositories returning `None`
keep the ordinary awaited fetch interface; their private allocation/yield behavior
is outside the sealed source's guarantees. Document ceilings bound encoded input,
not total decoder or compiler heap usage.

## Trust boundary

Phase 1 is locally trusted. The catalog validates and canonicalizes capsule manifests and verifies SHA-256 agreement between transferred component bytes, the manifest component digest, and the immutable release digest. It does not claim signature, provenance, SBOM, registry-authentication, OCI, or trusted-AOT verification; those remain later-phase work. Registration validates catalog data without preparing or instantiating the component.

## Execution-resource invariant and acceptance evidence

Registration, recovery, resolve, fetch, and list are implemented inside `latent-artifacts`, which has no scheduler or execution-backend dependency. These operations do not instantiate capsules, prepare Wasmtime state, acquire execution cells, start child processes or service workers, or open listening sockets. One ownership-lock file descriptor belongs to the catalog root, not to each release.

The ordinary eight-entry index test checks precharged capacity and every scope-selection path. The larger `one_hundred_thousand_index_adoptions_are_bounded` metadata-only test is ignored by default and requires explicit selection with `--ignored --exact`. It provides no evidence of durable publication or runtime topology.

The separate Linux `latentd` integration target `catalog_scale` exercises the public production `ArtifactRepository` interface. Its isolated publisher process registers 100,000 distinct synthetic component artifacts with real manifest validation, digest verification, metadata encoding, staging, file/directory syncs, atomic renames, and index adoption. It lists, resolves and fetches every artifact. After that process exits, a second process opens the same on-disk root, rebuilds the full catalog, and lists, resolves and fetches all 100,000 artifacts byte-for-byte. No test-only publication or persistence bypass is used.

Each child owns a real fixed cell pool with two generic node-owned cells before establishing its baseline. The probe measures process identity, child processes across all tasks, thread count, owned socket descriptors, owned TCP/Unix listening sockets, open file descriptors, pool capacity/availability, active leases, queue depth and quarantined cells. Measurements are checked after opening, at publication checkpoints, after complete verification and after closing. JSON output reports baseline/after measurements, zero-growth assertions for service-specific resources, and fixed helpers separately: the isolated probe process, its observed harness threads, two generic cells, and one catalog lock FD. These are controlled catalog-integration measurements, not a claim to benchmark the full running node or Wasmtime allocation behavior.

The scale probe opts into a 1 GiB index-accounting budget to fit 100,000 records. It runs on the ordinary disk-backed temporary directory with production syncs enabled. Ordinary unit-test invocations compile but ignore the expensive integration tests. The maintained `Durable catalog acceptance` job in the existing CI workflow runs the probe and retains its logs only when a manual dispatch sets `run_catalog_scale` to `true` (default `false`). Normal pull requests, pushes, and default dispatches still run the catalog recovery, routing, and supervisor regressions.

Run the acceptance probe explicitly with:

```sh
cargo test -p latentd --test catalog_scale --locked production_catalog_100k -- --exact --ignored --nocapture --test-threads=1
```

### Runtime budgets and diagnostics

This is a durability/resource-invariant acceptance test, not a minimum-publication-throughput benchmark. The earlier fixed 20-minute child deadline stopped a CI run after at least 70,000 successful publications, before it could establish the 100,000-release invariant. Production syncs and the release count must not be reduced to satisfy that deadline.

The publisher child now has a 60-minute absolute budget, including its full retrieval pass, and a 10-minute no-output watchdog. Publication and verification emit completed-record checkpoints every 1,000 releases with elapsed seconds. The reopen child has a separate 30-minute absolute budget including rebuild and full retrieval; its silence allowance is also 30 minutes because production index rebuild does not expose per-entry progress callbacks. Progress never extends either absolute deadline. The CI job budget is 120 minutes, covering both child budgets plus build, cleanup, and evidence upload. These are finite operational limits, not promised runtimes.

The supervisor runs only in the parent process, tails each child log with an independent read cursor in bounded 8 KiB chunks, and forwards output live without adding threads or file descriptors to the measured child. It checks child completion before declaring a timeout, propagates unsuccessful exits, and kills/reaps the child on timeout or supervisor failure. CI uses the runner's disk-backed temporary directory and sets `LSF_CATALOG_SCALE_LOG_DIR` to a retained workspace directory. Both `publish.log`/`reopen.log` and the combined `catalog-scale.log` are uploaded even when the probe fails; live forwarding also leaves progress in the Actions console. Local runs may set `LSF_CATALOG_SCALE_LOG_DIR` to retain the child logs outside temporary cleanup.

Fast supervisor regressions run in ordinary workspace tests and explicitly before the expensive CI probe. They cover healthy progress beyond the old deadline, silence timeout/reset, the non-extendable absolute deadline, silent bounded rebuild, and bounded log forwarding that resumes after EOF. Run only the fast integration-target tests with:

```sh
cargo test -p latentd --test catalog_scale --locked
```

The publication-visibility unit tests likewise observe writer errors/panics and deadlines; a deterministic coordination test forces completion between an absent resolve and the writer-status check, then verifies a fresh resolve/fetch after joining.

## Recovery procedure

For a root-initialization synchronization failure, preserve the directory and
retry `open` after resolving the filesystem error. A retry synchronizes the full
path even though it now exists. Bounded fault-injection tests verify the exact
leaf-to-root sequence, failure at each ancestor, full replay on retry, relative
nested paths, exclusive ownership, and preservation/reopening of a tiny release.
These tests verify operation ordering and error propagation; they do not simulate
physical power loss.

1. For a post-rename publication error, retry the exact pending artifact; do not assume failure removed its completed directory. Other publications receive `unavailable` until reconciliation.
2. Alternatively stop the standalone node and drop all repository handles so `.catalog.lock` is released. Preserve the root before any manual repair.
3. Remove only known abandoned `.tmp` content if manual cleanup is necessary; normal startup performs this automatically after acquiring ownership.
4. Do not promote directories lacking a valid `COMPLETE` record manually. A damaged digest-named final directory fails recovery; preserve it and recover from trusted source artifacts. Only non-digest incomplete debris is excluded from the visible index while counting against recovery-directory capacity, and may be inspected or removed offline.
5. Reopen the repository. Rebuild checks bounded/readable contract metadata, canonical manifests, digest-directory identity, component bytes, reference uniqueness and all configured limits. It syncs the release directory before exposing the rebuilt index and rebuilds the directory count before accepting publications.
6. Conflicting completed mappings, corrupt completed data or unsupported metadata are operator-visible open failures, never silently selected records. Preserve evidence and repair/remove the offending completed entry only offline; do not bypass bounds or JSON recursion protection to force startup.
