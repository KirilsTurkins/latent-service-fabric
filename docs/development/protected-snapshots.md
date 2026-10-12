# Protected snapshot custody

The snapshot producer for issues [#398](https://github.com/KirilsTurkins/latent-service-fabric/issues/398)
and [#399](https://github.com/KirilsTurkins/latent-service-fabric/issues/399) uses
the existing protected database and its fixed Recovery workers. It does not
open another source engine, copy a live database file or accept client paths.
The management service resolves a bounded configured destination identity to a
private operator root and supplies the original authenticated read/audit owner.

`ProtectedStoreOwner::create_snapshot` first reserves exclusive custody under
the original worker owner's admission lock. Every accepted callback and
unclaimed response, active reader/writer, affine view, dispatcher operation pin
and native retirement backlog must actually retire. An idle view count, paused
dispatcher or clean flag cannot establish this custody. Persistent checkpoint
and dispatcher native pins must retire through their original owners before
this operation can begin. Namespace records must also be durably quiesced.

Custody closes both ordinary and generic Recovery submissions. Only its same
affine resource can use the existing Recovery workers. Dropping an export
waiter leaves the queued/physical callback and its resource charged. Native
file/root destruction precedes original global work-buffer/permit destruction
and physical slot refund. Admission reopens only after that retirement and all
job/response bookkeeping have completed. A callback panic quarantines the
original owner; neither timeout nor detached observation implies abort.
A panicking native custody destructor leaves its bounded original keeper and
physical reservation charged, closes admission and supplies no retirement
proof. Only process loss can retire that unresolved owner.

The original Recovery `NativeReservation` must belong to the store's installed
global owner. It declares at least 8 MiB of work plus the resource's 64 KiB and
the independently bounded response. The producer reserves these bytes before
opening the file. It retains the original absolute deadline throughout export,
inspection and native cleanup. The existing store partition/queue/job ceilings
remain authoritative; a live device stall can prevent physical progress after
the observer's deadline and leaves custody and ownership charged.

The private file is exclusively created with mode `0600` below a protected
operator root separate from the business root. Existing files, symlinks,
traversal, wrong types, altered ancestry and unsupported filesystems refuse.
The producer checks the original native deadline and original current
read/audit decision around each file operation. Those currentness callbacks
are short metadata checks outside storage bookkeeping locks; they cannot run
guest code, providers, audit flushes, disk I/O or renew a decision. Review and
operator-output failures are distinct from actual source-engine corruption.
A partial export remains private and cannot produce a complete receipt or be
silently overwritten by another attempt.

The v2 stream contains all ten row families from one native view and an exact
canonical manifest. Bounds are 65,536 rows, 128 MiB of logical rows, 160 MiB of
file bytes, a 1 MiB manifest, 128 namespaces and 128 immutable artifact
associations, with 4 MiB pages and a maximum 60-second operation deadline.
Nested vectors and identity strings are bounded during decoding, before
allocation. Unknown fields, duplicate fields, row-order changes, trailing data,
unsupported versions, incomplete streams and checksum mismatches refuse.

The manifest captures every namespace across every tenant in the full unit,
including distinct tenants using the same namespace name and incarnation.
Every namespace must be durably quiesced. The metadata tenant describes the
original operator/audit context; it supplies neither filtering nor permission
to read another tenant. The authenticated operator must hold the actual
whole-unit read/recovery decision before the service admits this operation.

The manifest records the source `StoreIdentity` bytes observed in that same
view, namespace/schema/history epochs, actual row counts and digests, exact
retained-format inventory, runtime identity and immutable required artifacts.
Installed linked-row and artifact validators are mandatory. The complete
stream is fsynced and independently decoded/read back before returning its
receipt. A second bounded pass on the same file matches manifest histories to
the archived rows and refuses changed stream bytes. An absent history permits
only the codec's explicit epoch1 initial value. `inspect_created_snapshot`
consumes the same affine file; it cannot
open a substituted path or extend the deadline. Retire `ProtectedSnapshot`
before resuming business admission. Its retirement witness proves physical
cleanup, not restore or execution approval.

The schema review substrate hashes exact application definitions independently
of engine, package, WIT and publication identities. An installed reviewer must
accept exact package/declaration/evidence association. Compatible canary and
rollback composition requires every selected reader to accept the actual
namespace and every selected writer schema. Retained success, rejection,
command, attempt, inbox, ordering, effect, payload, profile and migration
checkpoint decoders remain independently required. These descriptions never
grant publication, result-read, migration, restore or provider permission.

This source milestone adds executable schedules for native custody, physical
retirement, actual redb/archive integrity, bounded input and protected operator
files. Native compilation, tests and strict Clippy are pending the current
resource hold. It does not establish the authenticated management/CLI surface,
the two-version guest campaign, full production retained-row closure, schema
migration, restore staging, approved reconciliation/resume or complete CI.

Restore must preserve producer ownership of the fresh destination identity,
sticky owner marker, external checkpoint, protected clock floors, audit and
high waters. Archived control rows are observations, never permission to
overwrite those owners or renew historical execution. The older peer v1
snapshot lacked this Root identity association and is explicitly unsupported
by this v2 producer/reader; no missing-format inference is permitted.
