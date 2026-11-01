# Durable publication retention pins and tombstones

## Delivery boundary

This is the native storage foundation for issue #662, not the completed
committed-publication deletion feature. The repository exposes trusted-host
pin/unpin and original-operation lookup APIs, a read-only deletion assessment,
a **native durable tombstone stage** that removes terminal publications from
visible indexes, and a separate **native capsule payload-reclamation stage**.
There is no operator pin/deletion CLI or public management transport in this
change. A tombstone alone is not a reclamation receipt and retains every payload
charge. Only an explicit, durably recorded capsule cleanup may release selected
immutable publication files and last-reference blobs. Componentless-web cleanup,
independent lifecycle/evidence history pruning, and authenticated CLI/audit
integration remain unfinished. Existing orphan reclamation is unchanged.
Do not manually remove catalog files or call this trusted-host foundation as an
operator cleanup tool.

A pin is **negative retention authority only**. It neither grants execution or
HTTP serving nor restores an expired, revoked or retired release. Generation
changes do not discard a pin. Clearing a pin does not authorize deletion.

## Exact bounded mutation

An authenticated host adapter must authorize the caller's scope and actor before
calling `publication_retention_snapshot` or `change_publication_retention`.
Supplying a tenant ID, operation ID, historical receipt or fence is not
credentials. The repository checks exact publication scope, expected generation,
and an opaque catalog fence covering lifecycle, componentless-web and retention
heads. Each installation receives an independent random retention identity;
copying equivalent publication bytes into another installation does not recreate
a fence. A complete stopped backup intentionally preserves that identity.

A request has one original operation ID and 1–32 strictly ordered, distinct
publication targets. The shared owner admits at most 1,024 current pins and 64
retained operation receipts, with separate byte ceilings (64 KiB per request,
4 MiB per head, and 4 MiB plus 4 KiB per intent). Encoding enforces its byte bound
while writing. A zero-allocation lexical prepass bounds nesting to 16 levels,
encoded strings to 4 KiB, and structural delimiters to 131,072 before typed
decoding. Encoding and preflight also check those ceilings on both the head and
intent envelopes, so an accepted write cannot exceed the reopen parser's bounds.
Canonical re-encoding and schema checks remain mandatory. The caller supplies a positive deadline of at most 30 seconds;
checks bracket bounded work and durability boundaries. Filesystem calls cannot
be forcibly cancelled: the shared owner and charges remain held until physical
I/O retires. There is no per-publication task, timer, collector or directory scan
on a pin batch.

The mandatory preflight callback runs outside reference/commit fences. A host
adapter must reserve required audit and response capacity there. All original
preconditions are rechecked after that callback and before the durable intent.
A publication or retention change during preflight refuses the stale request.
This callback contract is not an implemented management/audit integration.

## Persistence and original-operation recovery

The catalog stores a bounded checksummed `HEAD`, original-operation `INTENT` and
`INITIALIZED` record under `lifecycle/retention`. Before accepting the first pin
intent it durably promotes `LIFECYCLE_MODE` to
`lsf-release-lifecycle-retention-v1`. Older readers reject that marker before
cleanup. Do not downgrade or rewrite it. Checksums detect corruption; they are
not signatures or protection against an owner rewriting the whole installation.

The write sequence is intent file sync and parent sync, new head file sync and
parent sync, then intent unlink and parent sync. Only after the final sync is
memory/accounting adopted. An uncertain write poisons this incarnation's
lifecycle and web authority. Preserve the installation, stop its owner, reopen
with a compatible reader, and query the **original** operation ID. Reopen may
finish only the exact validated durable intent; it never invents a replacement
request. Incomplete format promotion with no intent does not invent a pin.

`Found` returns the original receipt, not current serving/rollback eligibility.
`Unknown` includes finite receipt eviction and proves neither nonexecution nor
permission to replay. A retained identical request returns its receipt; changing
its fields conflicts. An evicted original fence cannot silently apply again
because every successful mutation advances retention state. There is no retry
loop. Malformed, missing protected, foreign-mode or unsupported retention state
is refused before ordinary temporary cleanup.

## Accounting and backup

`PublicationStorageSnapshot.retention_control_bytes` includes conservative head,
intent and atomic-write exposure, not just currently allocated filesystem blocks.
It contributes to the existing storage limit and remaining capacity; conservative
metadata exposure contributes to the existing index limit. Pins do not refund
publication files or shared blobs. Shrinking pin metadata is accounted only after
the new durable head and intent-removal parent synchronization.

A backup is the **complete stopped installation**, including root markers,
`lifecycle`, `web`, committed publication directories, shared content and the
coupled protected control/audit stores. Preserve permissions and hard links.
Never copy just a retention head into another catalog. Restore using compatible
readers with the original protected authority; restoring an older installation
is not permission to replay external effects or unknown administrative mutations.
The native tests copy a stopped publication/control catalog pair and preserve
inode sharing, pins, tombstones, original receipts and terminal eligibility.
Reopening an older control catalog that still references tombstoned history is
refused rather than restoring the deleted publication. This is not qualification
of online backup, arbitrary external backup software, audit archival, or the
still-unimplemented physical deletion lifecycle.

Admission evidence, trust/revocation history and administrative audit have their
own owners and retention rules. Pin receipts neither replace audit nor permit
pruning any of those histories. This foundation does not change their retention.

## Native qualification and remaining issue scope

Run the registered Linux host suite with the exact source and the explicit
`development-test-host` fault-injection feature:

```sh
cargo test --locked -p latent-artifacts --all-features \
  --test publication_retention -- --nocapture --test-threads=1
cargo test --locked -p latent-artifacts --all-features --lib
```

The integration target uses actual `DirectoryArtifactRepository` files, locks,
rename, unlink and filesystem synchronization. Injected boundary failures are
not claims of power-loss testing. The componentless-web fixture injects a
non-cryptographic host authority; it does not qualify signature policy. Suite
registration alone is not execution evidence.

Issue #662 still requires componentless-web/history pruning and a supported
authenticated operator workflow with real finite audit admission/outcomes. The
capsule cleanup stage below qualifies native payload unlink/sync/refund, recovery
and coupled restore; it is not completion of the whole issue or qualification of
unimplemented web cleanup or independent evidence/lifecycle pruning.

## Native deletion assessment and physical ownership

`inspect_publication_deletion` is a bounded **read-only observation**, not a
preview receipt, reservation, deletion capability or promise about a later
request. It accepts 1–32 exact, sorted publications with scope, actor, original
operation ID, generation and catalog fence. It validates the complete selection
before returning pin/reference diagnostics, refuses admitted publications and
retention pins, and returns the observed control-store transaction only when
all negative checks succeed. It creates no intent, receipt, audit reservation,
tombstone, content unlink or capacity refund. Looking up that operation ID does
not establish a deletion outcome. `tombstone_publications` repeats
these checks and holds the same fences through its durable authority commit.
A future physical cleanup step must consume the committed negative authority;
it must not treat this assessment as authorization.

The standalone composition binds its real `DirectoryDeploymentRepository` once.
Trusted native embeddings using these two concrete owners must likewise call
`control.bind_publication_reference_authority(artifacts.as_ref())` on the actual
`Arc`-owned control store. This is an installation-composition operation, not a
way to provide caller-selected reference lists. Unsupported multiple independent
control stores are not a qualified deletion configuration. Missing, foreign,
dropped, unconfirmed or replacement owners refuse assessment. The artifact owner
keeps a weak reference to avoid an ownership cycle; rebinding after shutdown
requires reopening the complete coupled installation, not substituting an empty
control store.

The control writer and current immutable publication remain held across the
reference check. Deployment references use a compiled inverse index of record
positions, conservatively charged to the existing metadata budget **before**
allocation. The check does not rescan desired deployment manifests. HTTP rows
(maximum 256) and rollout rows (maximum 1,024) are scanned within their existing
finite limits, including denied/stale HTTP targets and both retained base and
candidate targets of terminal rollouts. Unknown publication associations fail
closed. Unrelated control commits can be observed without granting stale
reference authority; artifact/publication changes still invalidate the original
catalog fence.

Native physical reads share a nonblocking exclusion with assessment. Generic
borrowed and owned preparation sources retain a conservative catalog-wide count
until their last clone drops. The borrowed source is now `Clone`, not `Copy`:
copying implicitly must not evade physical ownership. Embeddings must quiesce and
drop these sources before maintenance; long-lived preparation owners can
therefore deliberately refuse assessment even for an unrelated publication.
There is no per-publication idle worker or task, and no waiting queue behind the
exclusion. A busy result does not authorize replay or deletion.

Web selections, cloned eligibility tokens and historical renderer snapshots
retain **exact publication** read references within the existing 32-read/64-MiB
owner. Reference-map overhead is charged before admission. Revocation does not
release these reads; only actual final-consumer retirement does. An unrelated
web selection does not pin an otherwise unreferenced target. Historical metadata
never restores serving eligibility.

The added native tests exercise both real filesystem catalogs, persisted denied
routes and terminal rollouts, reopen, foreign/dropped owners, original request
identity, retention pins, reader clones, a paused physical scan on another
thread, admission while the native control writer is held, unchanged bytes and
charges, and unrelated control changes. Componentless-web tests reuse the
explicitly non-cryptographic fixture authority; signing qualification is separate.
Run the owning libraries and the existing pin suite without relaxing any gate:

```sh
cargo test --locked -p latent-artifacts --all-features --all-targets
cargo test --locked -p latent-control-store --all-features --lib
```


## Durable native visibility removal

`tombstone_publications(request, timeout, preflight)` is the trusted-host native
entry point for the first deletion stage. It uses the same `PublicationDeletionRequest`
as assessment. Authenticate and authorize the exact scope and actor before calling
it. The callback must reserve the required finite audit attempt/outcome and
response capacity; it is **not** an implemented RPC, CLI or audit adapter. Do not
replace it with a no-op in an audited host.

The method validates all scoped target identities before reporting pins or
references, then requires terminal (`Retired` or `Revoked`) state. It prepares the
exact original receipt, runs preflight outside native fences, and rechecks the
original publication generations, catalog fence, pins, readers and actual control
revision. A reference-owner change or even an unrelated control commit during
preflight is a safe conflict, not permission to silently refresh the request.
An unrelated control commit before preparation is observed normally. The actual
native writer/current revision and physical read exclusions stay held through
the synchronized intent/head commit and visible-index cutover.

The common retention head has independent bounded pin and deletion histories.
There are at most **1,024 permanent tombstones** and **64 deletion receipts**,
in addition to the existing pin/receipt limits. Requests contain 1–32 exact
sorted targets; both byte and parser bounds may refuse a batch before these
count ceilings. Exhaustion refuses the entire batch. Tombstones are not evicted
to make publication IDs reusable, and no per-publication collector is created.
Original pin receipts and original publication receipts remain independent.

Before the first tombstone intent, the catalog durably promotes the root marker
to `lsf-release-lifecycle-deletion-v1`. Readers that do not support this marker
must refuse before cleanup. Do not downgrade it, including after later pin/unpin
operations. A marker promotion interrupted before the deletion intent retains
no deletion outcome: after reopen, the publication remains visible (but terminal)
and lookup is `Unknown`. There is no automatic retry.

The durable sequence is:

1. Reserve bounded control metadata/storage exposure, retaining the larger old or
   candidate charge until durability is established. Persist the format fence.
2. Sync the exact original-operation intent and parent; sync the new checksummed
   head and parent; unlink the intent and synchronize its parent.
3. Remove capsule entries from all public resolution/page indexes and mark web
   entries inaccessible, while retaining private metadata for original receipt
   recovery. Install the exact confirmed retention charge. Never unpin payloads
   or refund publication/content capacity in this stage.

A successful receipt has `stage: visibility-removed`. `publication_deletion_operation`
returns `Found`, `Unknown`, or `Uncertain`. A retained identical request returns
its original receipt with `replay: true`; it performs no new mutation. A changed
request conflicts. Receipt eviction yields `Unknown`; the permanent tombstones
still prevent reusing that operation ID for a different batch. Replaying an
original publish or pin receipt cannot restore visibility or create a current
retention pin. New lifecycle/evidence selection of a tombstoned ID is refused.

Failures after possible intent/commit retire this incarnation's lifecycle/web
authority. Capacity lookup then reports unavailable, not falsely reclaimed
space. Stop, preserve the whole coupled installation, reopen with a compatible
reader, and query the original deletion operation. Reopen validates and completes
only the already-durable intent, checks all tombstone associations/generations,
and removes visibility before exposing the reopened repository. Missing,
corrupt, downgraded or unsupported protected records are refused. The retained
metadata and payload files remain part of a valid backup and must not be pruned.

### Native qualification and measured boundary

The owning control-store suite uses both actual filesystem-backed repositories,
not a replacement reference-store model. The development fault feature is a
dev-dependency only; production host dependencies do not enable fault injection.

```sh
cargo test --locked -p latent-control-store --all-features --lib tombstones \
  -- --nocapture --test-threads=1
cargo test --locked -p latent-artifacts --all-features --all-targets
cargo test --locked -p latent-control-store --all-features --lib
```

Cases cover exact 32/33-target batches, 1,024/1,025 tombstone capacity, deletion
receipt eviction, native writer retention, reader/pin/preflight races, foreign
selection, low metadata capacity, capsule/web reopen, each injected durability
boundary, shared hard links, coupled stopped restore and mismatched older control
authority. The full tombstone-count fixture uses the supported eight-operation
**lifecycle** receipt window to bound setup; it does not reduce the 1,024-tombstone
ceiling or the independent 64-deletion-receipt window. Boundary-error injection
uses actual writes/rename/synchronization; it is not physical power-loss proof.

A locally executed finite fixture publishes three trusted-local capsule
associations sharing component bytes, retires two, then commits one two-target
tombstone batch. Its source test is
`native_tombstones_preserve_shared_blobs_and_unrelated_eligible_publications`.
Rust 1.97.1, debug test profile with debug info disabled, Linux local filesystem:

| Conservatively charged inventory | Before tombstones | After tombstones |
| --- | ---: | ---: |
| Retained publications | 3 | 3 |
| Shared blobs | 8 | 8 |
| Shared blob bytes | 4,125 | 4,125 |
| Publication-link file bytes | 5,653 | 5,653 |
| Retention control bytes | 0 | 20,923 |

These are actual native fixture observations, not a growth forecast, signed-site
soak, physical allocation measurement or reclaimed-byte claim. The test prints
its own machine-readable observation so a source/toolchain change can be measured
again rather than silently reusing these numbers. The unchanged payload/count
charges are intentional: completing visibility removal is not completing cleanup.

## Bounded physical-reclamation assessment

The trusted native host can call `inspect_publication_reclamation` with the exact
original `PublicationDeletionRequest`, explicit `PublicationReclamationLimits`,
and a positive timeout of at most 30 seconds. The original deletion receipt must
still be retained and the request must match it completely. A missing or evicted
receipt returns `publication-reclamation-original-operation-unavailable`; do not
reconstruct it from a tombstone or automatically retry a fresh deletion. The host
must authenticate and authorize the scope and actor before invoking this API.

The assessment retains the same native lifecycle, publication writer, retention,
preparation/read and actual control-reference owners as deletion admission. It
checks the tombstones and terminal generations before examining payloads, then
hashes each selected publication file and each distinct canonical blob. Capsule
and componentless-web content use the same reference accounting. It examines
only the selected publication directories and their indexed blob names, not the
rest of the publication catalog or blob directory.

`maximum_files` bounds publication-file observations **plus** distinct canonical
blob observations, with a hard ceiling of 1,024. `maximum_bytes_hashed` counts
both sides of a hard link: publication-file bytes plus each selected canonical
blob's bytes once. Its default is 64 MiB and hard ceiling is 1 GiB. Budget checks
against the retained index precede payload reads. Deadline checks bracket file
operations and every 16 KiB hashing chunk. Kernel filesystem calls are not
forcibly cancellable; owners remain held until the current call returns.

The result reports selected publication-file counts/bytes, last-reference blob
counts/bytes, shared blobs that other publications still retain, and actual bytes
hashed. Repeated links to one blob are counted as separate references but the
canonical blob is counted only once. Unselected publications still protect their
blobs even when retired or tombstoned. An unrelated publication can add a shared
reference after an earlier assessment, so the result includes the **current**
catalog fence and native control revision separately from the original deletion
request's pre-deletion fence. Never reuse an estimate as a commit authorization.

These are potential **namespace/accounting** changes, not filesystem block usage
or proven freed storage. Separate lifecycle, evidence-revision, audit and
retention-control stores are outside the totals and retain their own policies.
Original admission side files inside a publication directory are included in
its logical byte total; that total is not permission to discard evidence.

A successful assessment changes no file, charge, receipt or eligibility state.
It does not reserve audit capacity, authorize unlink or enable a cleanup CLI.
The separate capsule mutation below rechecks authority and bytes, commits a
bounded cleanup record and uses its own recognized-intent recovery protocol.
No committed-content unlink or refund is performed by this assessment.


## Durable native capsule payload reclamation

`reclaim_tombstoned_capsules` is an explicit trusted-host mutation, not a public
management route or CLI. Its `PublicationReclamationRequest` contains the exact
retained original deletion request, a **fresh** assessment catalog fence, and
finite limits. The host must authenticate scope and actor and reserve finite
audit outcome/response capacity in preflight. The callback is an integration
contract, not an implementation of those checks; a no-op callback is appropriate
only in explicit native test fixtures. Componentless-web targets fail with
`publication-reclamation-capsule-target-required` before preflight or mutation.

Fresh mutation hashes the selected publication files and each canonical blob,
prepares and bounds both durable record envelopes, invokes preflight without the
commit locks held, then rechecks the exact fence, control revision, references,
readers/preparation clones and content. Each of the two hashing passes receives
half the request's file/byte limit. The receipt's `content.bytes_hashed` reports
one verified pass; total fresh-mutation hash work is twice that value and cannot
exceed the request limit. Both passes share the caller's deadline (positive,
maximum 30 seconds). Native filesystem calls cannot be forcibly cancelled; no
owner is released while its call is still running.

The durable sequence is:

1. Promote and synchronize `LIFECYCLE_MODE` to
   `lsf-release-lifecycle-reclamation-v1`. Older readers reject it before cleanup.
2. Commit a bounded cleanup intent/head under the existing retention owner. It
   binds the exact original request, current control revision, compact capsule
   identities, and selected file/blob names, lengths and digests. Admission and
   recovery allow at most 32 targets and a 1 MiB encoded cleanup plan; existing
   64 KiB request, 4 MiB head, parser and retention accounting ceilings remain.
3. Keep the real lifecycle, publication writer, read/preparation exclusions and
   bound control writer/revision held. Unlink only exact selected files, sync the
   emptied publication directory, remove it and sync the publication parent.
4. Release selected committed content references. Unlink a canonical blob only
   when its last committed reference is gone, and sync the blob parent **before**
   refunding its charge. Other publications protect shared blobs even if retired
   or tombstoned. No unrelated publication directory is scanned.
5. Commit the original-operation completion receipt. Publish refunded index
   metadata and publication-directory capacity only after the synchronized
   namespace removals and completion record. No positive lifecycle or serving
   grant is created. Original deletion receipts still report `VisibilityRemoved`.

An error after intent retires the live catalog owners. Capacity reads are then
unavailable, never falsely reported as reclaimed. Stop the embedding and reopen
its coupled protected roots; do not delete the intent or retry a new identity.
On reopen, the retained cleanup record is checked **before** ordinary temporary
cleanup. Compact identities are cross-checked against independent lifecycle
history, tombstones and exact terminal generations. Recovery first validates
**all** surviving selected file names and bytes, canonical blobs and surviving
references; only then may it continue the exact already committed cleanup.
Missing selected names are acceptable only within that recognized active plan.
Corrupt, foreign, extra, symlinked or downgraded authority refuses cleanup.
A completed cleanup cannot silently reintroduce an older publication directory.

`publication_reclamation_operation(scope, operation_id)` returns `Found`,
`Unknown`, or `Uncertain`. Exact retained completion replay returns the original
receipt and performs no unlink/refund. The independent cleanup receipt window
is 64 operations; its eviction is UNKNOWN and cannot authorize reconstruction or
replay. Compact removed identities share the existing 1,024-tombstone ceiling,
remain after receipt eviction, and refuse re-publication under either the old
or a fresh operation ID. Reclaimed publish replay returns
`publication-payload-reclaimed-query-original-operation`, not a corruption
claim. Inspecting an already cleaned original request returns
`publication-reclamation-already-committed-query-original-operation` when its
original deletion receipt remains retained.

This stage returns publication-directory slots, immutable publication-file
charges, last-reference canonical blob charges and their in-memory indexes.
It does **not** prune independent lifecycle rows, evidence revisions, audit,
retention pins or tombstones. These budgets remain finite and independently
exhaustible. Do not report filesystem allocated blocks, signed evidence history
or business-state reclamation from these namespace/accounting receipts.

### Cleanup backup and native measurements

A stopped, coupled backup must retain artifact and control roots together,
including lifecycle/retention HEAD and recognized INTENT, format/installation
identity, compact removed identities, pins, original receipts, shared surviving
files and protected permissions. Do not mix older control snapshots into a
newer artifact snapshot or restore missing payloads into a completed cleanup.
The native fixture copies actual stopped trees, preserving hard links/modes,
and checks both a partially unlinked intent and a completed cleanup against the
same-root reopen, survivor reads, pin state and capacity accounting.

The owning native tests execute actual writes/unlinks/parent synchronization,
including interrupted intent, head, format promotion, publication-file removal,
publication-parent sync, blob removal, blob-parent sync, and before/after final
receipt. They also cover exact 32-target cleanup, reader clones, real held
control writer/revision, preflight races, 64-receipt eviction and low metadata or
storage capacity. Existing physical-resource tests remain enabled. Fault hooks
are test-only and are not a physical power-loss campaign. Trusted-local fixtures
do not qualify signature policy or a network filesystem.

`native_cleanup_finite_release_sequence_reclaims_payload_not_independent_history`
publishes, retires, tombstones and cleans three sequential trusted-local capsules
with distinct 1 MiB component payloads. One local Rust 1.97.1 debug-profile run
on Linux (debug info disabled) observed the following accounting bytes:

| Iteration | Charged before cleanup | Charged after cleanup | Publication files removed | Last-reference blobs removed |
| --- | ---: | ---: | ---: | ---: |
| 0 | 2,120,725 | 23,998 | 1,050,474 | 1,050,474 |
| 1 | 2,127,244 | 29,923 | 1,050,474 | 1,050,474 |
| 2 | 2,133,166 | 35,857 | 1,050,474 | 1,050,474 |

Publication and canonical blob byte charges were zero after each cleanup; the
remaining reported charge was retained control metadata. The two removed byte
columns count hard-linked namespaces, not two independent allocations of disk
blocks. Serialized installation/fence bytes can vary, so retained-control values
are observations of this run, not golden constants or a universal growth rate.
The test prints `CAPSULE_RECLAMATION_SEQUENCE` rows for each fresh execution and
checks that final live and reopened accounting agree. This is not a signed-site
soak or qualification of unfinished componentless-web cleanup.
