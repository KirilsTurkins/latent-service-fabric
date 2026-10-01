# Durable dispatch storage

The atomic command envelope stores the committed `EffectRecord`, its exact
`PayloadRecord` and initial due index in one engine batch. These records retain
command, commit, caller, namespace incarnation and payload linkage without a
guest instance. Publication state-schema changes do not reinterpret payloads.

The selected profile is unordered. Sequence identifies an intent within its
command; it grants no ordering or predecessor-skipping behavior. Ordered mode
requires a separately supported profile and is rejected by the dispatcher.

## Closed initial formats

| Family | Key | Value |
| --- | --- | --- |
| Outbox | `effect-v1\0` + raw 32-byte effect identity | Existing checked `LER\0\x01` effect record |
| PayloadReference | `effect-payload-v1\0` + raw effect identity | `LEP\0\x01` + raw effect identity + LE u32 canonical Value length + canonical Value |
| Maintenance | `dispatch-due-v1\0` + BE u64 due milliseconds + raw effect identity | `LDI\0\x01` + BE u64 namespace incarnation + BE u64 claim generation |
| Maintenance | `dispatch-owner-v1\0` | `LDO\0\x01` + BE u64 process epoch + BE u64 trusted clock floor |
| Attempt | `dispatch-history-v1\0` + raw effect identity + BE u64 history sequence | `LDH\0\x01` + bounded receipt/attempt JSON, at most 4 KiB |
| Attempt | Same future history key while an attempt is active | `LHP\0\x01` + BE u64 owner epoch + BE u64 claim generation + BE u32 attempt |
| Maintenance | `logical-reservation-v1\0dispatch-attempt-v1\0` + raw effect identity | Checked engine `LSR\x01` reservation, 70 KiB, bound to claim generation |

The initial due time is the immutable authority's committed time, and initial
claim generation is zero. Big-endian time and binary identity make finite prefix
pages sort by due time, then effect identity. Guest strings never select an
engine family or construct an index; scope comes from the captured authority.

Canonical Value bytes are `LEV\0\x01`, LE u32 payload length and binary payload,
LE u16 media-type length and UTF-8 media type, LE u16 metadata count, then sorted
metadata entries. Each entry uses LE u16 key length/key and LE u16 value
length/value. Metadata names sort by UTF-8 bytes; duplicate or noncanonical
encoded names fail decoding. Digest is SHA-256 of
`lsf-effect-payload-v1\0` followed by these exact canonical Value bytes.

Payloads retain the contract's 1 MiB body, 128-byte media type, 32 metadata pairs
and 8 KiB combined metadata bounds. Decoder limits/counts/types/trailing bytes
are checked before application buffers are allocated. The row key binds the
decoded effect identity, and retrieval also calls `PayloadRecord::verify` against
the immutable authority's payload length/digest. A decoded record grants no
current dispatch authority. Unsupported record versions fail visibly.

`dispatch_store::validate_row` validates only its closed outbox, payload and due
prefixes; other namespace/command/maintenance codecs remain responsible for
their own rows. Full dispatcher startup must also verify cross-row linkage and
recover interrupted claims under exclusive process ownership before readiness.

`DispatchCatalog::validate_view` validates this dispatcher's closed prefixes and
cross-row links against one coherent borrowed startup snapshot. It checks exact
due generations, unresolved payload digests, owner epochs, complete bounded
history, active history placeholders and matching logical reservations, including
orphaned rows. It walks finite 16-row/4 MiB pages and bounded point reads instead
of collecting the backlog. The command registry validates its own foreign
prefixes and command/commit linkage. `has_owner_history` exposes whether startup
must obtain an admitted external epoch/clock checkpoint before claims.

## Integration ports

`payload_digest(&Value)` lets the command coordinator capture immutable payload
identity. `PayloadRecord::new` verifies that authority and returns the retained
binary row. `effect_row_key`, `effect_payload_key` and `initial_due_mutation`
produce the shared store's exact keys/mutation. The coordinator includes every
row in its atomic state/result/outbox/payload boundary; an independently appended
outbox is not a transactional guest path.

The borrowed `DispatchCatalog` runs inside fixed storage jobs. Claim CAS consumes
the exact due row, advances the record's attempt/generation and fences the node
epoch. A durable send marker precedes physical dispatch. Completion replaces the
outbox and appends one history row atomically; stale or duplicate completions
cannot overwrite an active or terminal disposition. Qualified retries alone add
another due row under the same stable effect/payload/provider identity. Unsafe
retry proofs preserve the actual uncertain receipt.

The fixed provider worker retains its affine `DispatchContext` through actual
provider cleanup. `accept_with` rechecks the current rule under its short no-I/O
fence and passes a sealed owned `DispatchGrant` to synchronous reviewed adapter
admission. It refreshes the credential reference/epoch, narrows ceilings and
preserves the original deadline. The adapter returns an owned accepted operation
that starts I/O only when driven after its durable send marker; policy locks are
released before storage/network I/O. Revocation before admission prevents the
adapter callback and does not refund the existing physical owner.

Claim also reserves 70 KiB of logical capacity and installs the future history
row. Every engine writer counts that reserved capacity. Completion replaces the
actual history placeholder and releases the reservation in the same transaction;
the released reservation row can hold a qualified retry index. This preserves
receipt capacity even when another writer fills the remaining byte and row
quota. Pending history slots remain visible as a bounded diagnostic count, never
as completed receipts. These reservations do not promise disk-free space or
eliminate an uncertain physical flush failure.

Startup checks cross-row linkage under exclusive store ownership, then advances
the process epoch and recovers finite outbox pages. A persisted send marker means
uncertain provider acceptance. Recovery before that marker is known nonexecution
only after affirmative old-process physical retirement. An admitted protected
external checkpoint rejects epoch/clock rollback on restore; wall time alone
cannot synthesize continuity. Process epochs never change business namespace
incarnation or command identity.

The focused tests prove canonical identity/tamper rejection, bounded malformed
decoding, due ordering, actual atomic snapshot/reopen, stale receipt fencing,
send/claim restart boundaries, qualified retry, bounded history, policy/expiry,
clock regression and older-checkpoint rejection.

Measured on 2026-10-01: all 40 effect tests passed on Windows and the pinned
Linux Rust 1.97.1 image, with strict all-target/all-feature Clippy on both hosts.
All 73 state tests and strict Clippy also passed on Linux. This includes the
native full-store receipt pressure schedule and the shared engine reservation
port from `fbe2c8e2`. Exact Linux discovery is registered in the workspace suite.

## Fixed dispatcher and node lifecycle

`DispatcherOwner` uses the transaction runtime's same `Arc<ProtectedStoreOwner>`.
It acquires the store's exclusive dispatcher registration before validation,
epoch advancement or recovery. An alias cannot overlap a dispatcher with live
provider work. Persisted owner history requires an admitted external minimum
epoch/clock checkpoint; a monotonic-looking wall clock does not approve restore.
The node handles a missing checkpoint as paused recovery readiness before claims.

The default profile has two fixed provider workers with 1 MiB stacks, four queue
slots, 16 accepted jobs, one accepted job per active tenant, 80 MiB retained work
and a 4 MiB reservation per accepted attempt. Due pages contain at most 16 rows
or 1 MiB; at most four pages are scanned per scheduling tick. Configuration has
finite ceilings for every field. The selected unordered contract rejects ordered
mode rather than fabricating predecessor or global-order promises. Empty/cold
tenants have no worker, timer, connection or retained admission metadata.

One shared scheduling task rotates the durable due cursor, skips saturated active
tenants and prioritizes the finite receipt queue. No task or timer is allocated
per durable intent. Provider jobs are reserved before claims. The native claim,
current fenced adapter admission and persisted send marker run inside one accepted
storage job; the owned provider future remains unpolled until the marker commits.
It then runs on a fixed provider worker through actual physical cleanup. Immutable
profile matching prevents redirecting old work through a new decoder/provider.
Missing decoders are recorded as blocked, while paged profile inventory retains
the original command, commit, namespace incarnation and unresolved status.

The provider's authority owner retires after actual I/O/buffer cleanup. Its
storage operation pin and accepted job reservation remain live until the durable
receipt CAS finishes. Store queue pressure keeps one pending receipt plus the
bounded receipt channel, without resending network work or allocating a second
worker pool. Claim reserves both terminal logical bytes and the actual future
history row. Disk/flush failure remains recovery uncertainty.

Pause stops new claims. Resume requires current safe clock state and no sticky
failure. Close is nonblocking. Shutdown applies one absolute cutoff to provider
workers and the scheduling owner, observes actual fixed thread joins, and preserves
root pins when physical work remains. A later observation can prove retirement
while still reporting unclean after the original deadline. Drop closes admission;
the scheduling task retains the role until all actual accepted work retires.

The standalone `EffectRuntime` owns these ports. `StandaloneNode::install_effects`
accepts the trusted state composition before readiness; `effects_snapshot` returns
bounded observations and `ShutdownReport.effects` participates in clean teardown.
Standalone shutdown closes effect admission first and uses its original drain
cutoff before state-store retirement. The state composition supplies existing
provider adapters, authority and protected clock/checkpoint evidence. Stateless
compositions retain an absent optional effect runtime.

Measured on the pinned Linux image: all 48 effect cases passed with strict
all-target/all-feature Clippy; all 75 state cases and combined strict Clippy also
passed. Actual schedules cover a live provider through expired drain, dropped
dispatcher owner, forbidden alias recovery, native queue saturation, current
revocation, paused/unsafe clock, hot-tenant fairness, old/new decoder compatibility,
bounded required-profile pages and external-checkpoint recovery after real store
close/reopen. Provider doubles witness physical payload destruction through
shared rendezvous; these cases are native dispatcher tests, not broker, HTTP
endpoint or packaged guest qualification. Concrete transports and their controlled
real endpoint evidence belong to #392/#393; ordinary state-runtime composition,
management authorization and terminal payload retirement also consume their
respective Phase 4 ports before aggregate delivery is complete.

## Attributed node controls

The dispatcher is node-wide, across tenants and namespaces. Its management
gateway requires current trusted node-operator authorization; a tenant
administrator or a known effect ID supplies no permission to pause it or release
its node-wide aggregates. These are existing private management transport ports.

`prepare_control` captures the original authenticated actor tenant/subject,
operation ID, `Pause`/`Resume` action and exact control generation. That generation
combines the actual persisted exclusive dispatcher epoch with a checked monotonic
revision. Preparation does no I/O and changes no admission. A prepared value is
affine to this actual dispatcher; another engine/owner rejects it before queuing.
Local safety pause and restore-review changes invalidate stale preparations.

`submit_control` transfers that immutable request to the same protected store's
fixed writer. It reserves 64 KiB for the bounded request, intermediate rows and
receipt. The actual engine transaction checks the owner row, latest control and
absent original receipt. Its final short callback holds current node policy
through one acceptance, advances the revision and pauses admission. Receipt
durability then atomically stores the owner clock floor, latest control and
attributed original-operation receipt. The policy lock never spans disk I/O.
Only successful durable completion publishes a resume. Dropped waiters keep the
actual writer and its reservation; no unobserved writer is refunded.

Both `dispatch-control-v1\0` and `dispatch-control-receipt-v1\0` live in the
Maintenance family. Values are closed `LDC\0\x01` records, bounded to 4 KiB.
The receipt key contains SHA-256 of `latent.dispatcher-control-operation.v1\0`
and the length-framed authenticated tenant, subject and original operation ID.
IDs are at most 256 UTF-8 bytes; a reused ID with a changed action/precondition
fails exact association. Startup validates receipt/latest-control/owner links
in finite pages and keeps an earlier durable pause across exclusive epochs.

Historical receipt lookup preserves the original action and precondition; it
never republishes a historical resume. Unknown completion keeps admission paused
and the pending original identity. Only actual receipt recovery or the admitted
exclusive-owner recovery path can establish its outcome. No timeout, pause,
cancel, cursor, decoded receipt or numeric generation proves provider retirement.
Already accepted claim/send/cleanup can finish after pause; shutdown reports
physical retirement and fixed thread joins separately.

Pause remains available with an unproven or backwards clock. Resume requires
protected continuity, no sticky failure and no restore-review fence. Restore
composition installs `start_in_restore_review` before readiness, or the trusted
`require_restore_review` safety port before exposure. Generic resume cannot clear
that fence; #399's separately reviewed restore protocol must provide any future
clear/resume authority. A known durable resume whose later safety fence prevents
publication remains a known receipt and reports `published: false`.

The common authenticated RPC/CLI composition and #397 reserved recovery lane
consume these ports. This domain implementation does not by itself qualify the
public management workflow, ordinary-queue saturation or backup/restore review.

## Original command role and clock

The same protected node role also supplies commands when no effect adapters are
configured. `command_admission_source()` returns a cloneable sealed metadata
source, with no worker or scheduling handle. `capture()` reserves a non-clone
`CommandAdmission` from a finite node slot table (128 by default, hard ceiling
1024). Captured guards expose their actual protected owner epoch and positively
qualified time; descriptions and client counters cannot reconstruct them.

`with_current` is the short outer native-writer acceptance fence. It checks the
same epoch/control generation, pending control, restore review, current store
failure/close/quarantine and nonrewinding original clock before invoking the
host's namespace, policy/effect and cancellation acceptance. It performs no I/O
and releases before flush. Initial startup time still needs the admitted
external checkpoint and retained command registry's maximum clock floor; this
port does not synthesize continuity from wall time.

The actual physical command owner must retain its guard through guest/native
cleanup and invoke `retire(self)` only after positive retirement. Lost waiters,
logical cancellation, expired leases and a finalized activation ledger are not
retirement proof. Unexpected guard Drop quarantines the shared store and keeps
the bounded guard/root role. Driver shutdown cannot retire that role or allow a
new epoch while any original command guard remains. A plain effect pause allows
fresh commands to accumulate paused intents; stale control generations and
restore review fail writer acceptance. Diagnostic epoch/time getters reserve no
command slot and grant no writer permission. The sealed source exposes the exact
installed effect registry and checks registry owner identity; it does not create
a second authority. Its clock getter fails closed after physical role close.

Pinned Rust1.97.1 Linux: all70 effect cases and strict all-target/all-feature
Clippy passed, including four real protected-store command schedules: zero
adapters with bounded sources and clock rollback, control/restore fences, sticky
deadline with exclusive role retention, and detached native writer/buffer
retirement before rejecting an old command fence. The earlier adapter factory
passed all-feature standalone compilation. Checking the newly added command
wrapper was interrupted by Docker becoming read-only (SIGBUS and filesystem
error 30), so that full application check remains pending. Full guest admission
and response/recovery capacity remain their integration owners.
