# Protected transaction checkpoint

The external checkpoint is a bounded recovery record outside the actual
business-store root. It describes the installed store identity, checkpoint
generation, protected clock authority epoch, durable dispatcher owner epoch and
clock floor in milliseconds. It grants no execution authority or restore
approval. The supported file session uses the same Linux x86-64 ext4 profile and
fixed recovery workers as the [protected storage owner](protected-state-root.md).

`ExternalCheckpoint` uses the closed `LTC\0\x01` binary format: a two-byte
big-endian identity length, four big-endian unsigned 64-bit fields, the canonical
ASCII store identity and a SHA-256 checksum of the preceding bytes. Identities
are one to 128 bytes; every integer is positive. The full record is at most 199
bytes. Decoding checks format, exact length, checksum and canonical fields before
allocating the identity. Advances cannot reduce any epoch or floor, wrap the
checkpoint generation or change the store identity. The checksum detects record
damage; it is not authentication.

The protected file is `transaction-checkpoint.v1`, with a separate exclusive
root-owner lock. Both roots retain their actual directory anchors. The ancestry
comparison refuses equal roots, a checkpoint inside the business root and a
checkpoint root containing the business root. Siblings may share ancestors.
Named-inode, ancestry, permission, owner and length checks surround file work.
No public result exposes a file, protected root or cloned native resource.

Only `start_bound_validated_view_with_clock` can produce fresh initialization
evidence. Its one existing initializer validates the logical registry, proves
the engine empty, commits the installed store identity and verifies the original
root fences before publishing the owner. `take_initialization_witness` consumes
that evidence once. A matching persisted identity, lost witness or restart after
the identity transaction never produces another witness. A missing checkpoint
without this original witness is refused. Existing empty, malformed, unsupported
or mismatched files are preserved for explicit recovery.

The host opens a finite checkpoint session with an original recovery reservation
from the installed global native owner. It reserves the actual work-buffer
footprint before opening native files, then uses the existing recovery worker
and pre-reserved destruction path. Reads and updates keep that original deadline.
Dropping a waiter detaches observation and retains native ownership through
destruction; it cannot refund the original permit or certify a write aborted.
The retirement witness becomes positive only after actual resource destruction,
global keeper destruction and local physical reservation release.

Before accepting commands, the standalone bootstrap must validate the old
checkpoint against the installed identity and one coherent
`DispatchCatalog::checkpoint` observation, keep dispatch paused, establish the
new actual owner epoch, persist that epoch and floor, and positively retire the
file session. Protected clock metadata must come from the same
`SupplyChainAuthority::covered_clock_source` owner; configuration or wall-clock labels
cannot prove continuity. Later recovery work requires a new separately admitted
existing-file session. It cannot renew the original session's deadline.

`EffectRuntime::start_protected` implements this bootstrap sequence on the
admitted store. Its checkpoint work reservation is 64 KiB from that store's
original global Recovery partition. It consumes the fresh witness before dispatcher
startup, inspects the external file on the original recovery workers, starts the
singleton paused, binds the same native owner, advances the checkpoint from the
actual durable dispatch observation and awaits a positive file-retirement
witness before returning a command source. It remains paused for the caller's
normal readiness sequence. This port grants no restore review or management
resume. Timeout or dropped startup observation quarantines the same store while
accepted native work keeps its original keeper through destruction.

Optional trusted `ProtectedStatePreparation` runs after the actual checkpoint
opens and is inspected, before dispatch starts. Fresh evidence therefore remains
valid while the engine contains only its initializer identity. This finite
callback installs or validates tenant/bootstrap rows on the same Recovery
writer. It declares at most 1 MiB of retained input and temporary work; the
original startup reservation prepays those bytes and keeps its buffer permit
through actual job/result retirement. Every tenant publication retains this
same original keeper and deadline in its actual owner fence. The callback
returns only bounded unit/status and grants no namespace or policy permission.

The returned `ProtectedEffectClock` combines the original process clock with
actual covered authority reads. Each accepted sample checks the original
wall/monotonic anchor, the last accepted pair, the nondecreasing authority epoch
and the current finite lease. Authority contention grants no positive sample;
actual rollback, lost coverage or uncertainty irreversibly rejects that clock.
Renewing the authority's lease cannot revive a clock that already lost coverage.
These observations perform no filesystem operation or lease renewal.
The covered-clock source reads coherent accepted metadata from the original
authority, including inside its actual admission fence. It never recursively
acquires the authority's admission/ledger mutex or publishes a cached grant.

Updates compare the exact original supported checkpoint before writing. They
synchronize the file and verify the bytes and original fences afterward. Any
partial write, synchronization failure or lost fence after a write is uncertain
and gates further work on the same storage owner. The failed file remains;
another initialization never replaces it. These boot floors do not detect every
possible rollback within one owner epoch. Older-history restore still needs the
explicit reconciliation and recovery approval required by #399.

The source registers four portable codec cases, ten native checkpoint/identity
cases and two protected-root ancestry cases. Native execution and strict Clippy
for this addition are held by the current local disk limit. The earlier
exclusive-create and generic resource ports retain their separate measured
proofs. This checkpoint source does not establish completed standalone startup,
backup/restore, power-loss durability or full CI qualification.
The protected effect bootstrap adds three portable clock-boundary cases and
three Linux cases using an actual protected authority for retirement, regression
and lease-loss/renewal. Their native execution and the actual standalone caller
composition are also pending.
