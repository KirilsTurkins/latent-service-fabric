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

`create_reviewed_snapshot` uses that same custody, file and worker implementation
with a typed review result. Installed catalog, decoder or current-access refusal
stays a healthy domain failure; capacity and original deadline refusal stay
distinct. Actual source corruption or uncertain source I/O reaches the original
quarantine path. The original `create_snapshot` signature and classifier remain
supported. A rejected review still retains its private file and reservation
until the returned affine resource actually retires.

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

`latent_commit::recovery_review::review_snapshot` composes the original atomic,
dispatcher and state codecs on that same borrowed view. It checks each original
link before feeding exactly one producer contribution into the installed whole
unit `TenantCensus`. Trusted finite quota configuration must match every installed
tenant; namespace ceilings or the metadata tenant cannot substitute for it.
Physical encoded keys have the production 4096-byte bound, while business keys
retain their independent 1024-byte bound. Counter drift, missing payloads,
unsupported producer formats and partial tenant configuration refuse the unit.

The review captures original publication, release, component, contract and schema
artifacts, exact provider/adapter definitions and original inbox processing
associations. Installed immutable owners compare the complete original records;
current publications, recreated profiles or replacement consumers cannot supply
that evidence. Every observed supported decoder is required independently,
including actual LCM3/LCM4, result, rejection, inbox and effect history versions.
Protected pending rows and uncertain effects remain in the inventory after
expiry. Administrator termination does not turn an uncertain provider attempt
into proven nonexecution or drained retention.

The resulting review contains bounded descriptions only. Its source identity,
dispatcher epoch/floor and paused recovery guard cannot authorize restoring
control rows, changing clocks or resuming effects. The current whole-unit policy
and critical audit owners, original global Recovery reservation, exact absolute
deadline and positive native custody must survive independently through review,
export, readback and cleanup. Immutable catalog callbacks run on the fixed worker
outside currentness locks; currentness checks cannot perform I/O or renew grants.

The schema review substrate hashes exact application definitions independently
of engine, package, WIT and publication identities. An installed reviewer must
accept exact package/declaration/evidence association. Compatible canary and
rollback composition requires every selected reader to accept the actual
namespace and every selected writer schema. Retained success, rejection,
command, attempt, inbox, ordering, effect, payload, profile and migration
checkpoint decoders remain independently required. These descriptions never
grant publication, result-read, migration, restore or provider permission.

The fixed migration producer consumes the same affine `ProtectedSnapshot` and
uses the existing Recovery writer. Its two installed recipes are
[count](../../contracts/state/aggregate-v1-to-v2-protected-migration.json) and
[Java aggregate](../../contracts/state/java-aggregate-v1-to-v2-protected-migration.json).
They accept exactly one original 8-byte aggregate cell in a durably quiesced
namespace, add the fixed `AG` version prefix, and retain the original count in
a 12-byte v2 value. Entity-selected or additional cells, other media types,
metadata, scripts, keys or transformations refuse. The recipes bind snapshot
v2 explicitly; the historical v1 recipe artifacts remain unchanged.

`ProtectedStoreOwner::migrate_aggregate` stages a checksummed LMG2 progress row
and a paused namespace history before changing the value. That marker captures
the exact operation/operator, original 67-byte view association, full-unit
checkpoint and manifest digests, immutable schema/package/review/recipe hashes,
and original namespace/history/guard and tenant quota bytes. Normal namespace
transitions cannot bypass an incomplete marker. Completion changes the fixed
cell, namespace generation/schema, schema epoch, progress and exact tenant
categories in one actual fenced engine transaction. The namespace and history
remain paused for explicit reconciliation; completion cannot resume execution.

The original tenant owner computes every category delta from exact row
preimages. The fixed-size quota codec lets staging record the canonical final
quota without inferring counters or adding an alternative accounting owner.
Recovery verifies that staged quota through a temporary inverse delta using
the same arithmetic, then normalizes only the exact progress/history/quota
changes against the original full-unit checkpoint. Unrelated row or counter
drift refuses. The inverse plan is never submitted. Existing unsupported
migration formats never become absent work or receive inferred quotas.

The concrete host must retain its original authenticated whole-unit recovery,
critical audit, exact package/schema evidence and namespace/effect owners.
Its final `AggregateMigrationOwners::accept` executes inside the real writer's
short no-I/O fence and consumes that invocation's affine `MigrationCommitFence`.
Ignoring the original native gate refuses the transaction. Lock order remains
Policy, Namespace, Effects where needed, then original Native currentness and
cancellation. The host must invalidate affected live namespace/effect metadata
at accepted mutation; descriptive progress, hashes and plans supply no grant.
Audit reservation precedes preparation, and audit completion remains outside
these locks. No guest, provider, audit flush, disk I/O or decision renewal may
run inside a currentness fence.

Exact completed operation replay preserves its original receipt and token;
it cannot refresh preconditions, downgrade the schema or renew publication
authority. `inspect_progress` reads bounded original status on a borrowed
native view and supplies no read permission or resume approval. After positive
resource retirement, `open_snapshot` can reopen an explicitly configured
existing private checkpoint for a fresh authorized Recovery request. It never
creates or overwrites a missing/partial file. Fresh input access does not
renew historical command/effect/migration execution. The old migration owner
cannot be replaced while its same file resource remains physically live.

Twenty-one registered source schedules cover the actual Count/Java codecs,
tenant census, original checkpoint drift, forged staged quotas, schema/recipe
and decoder refusal, incomplete-operation reopen, exact completed status,
fenced writer refusal, native/file custody, final current refusal after held
review, original deadline expiry and detached physical cleanup. The rooted
schedules use real protected files/engine workers with controlled reviewers;
they do not establish authenticated Wire/deployment or external checkpoint
restore approval. None has been compiled or executed under the native hold.

This source milestone adds executable schedules for native custody, physical
retirement, actual redb/archive integrity, bounded input and protected operator
files. Native compilation, tests and strict Clippy are pending the current
resource hold. It does not establish the authenticated management/CLI surface,
the two-version guest campaign, the concrete authenticated migration adapter,
restore staging, approved reconciliation/resume or complete CI.

Fourteen additional registered source schedules cover durable rejection/inbox
and uncertain effect history after reopen, substituted evidence, decoder removal,
corrupt links and tenant counters, paused controls, maximum entity/business keys,
original deadline/current-access refusal, actual namespace corruption and
detached source-I/O uncertainty with retained native capacity. Those schedules
have not yet been compiled or executed under the native resource hold. The
installed production artifact-review adapter and migration/restore producer
composition remain separate requirements.

Restore must preserve producer ownership of the fresh destination identity,
sticky owner marker, external checkpoint, protected clock floors, audit and
high waters. Archived control rows are observations, never permission to
overwrite those owners or renew historical execution. The older peer v1
snapshot lacked this Root identity association and is explicitly unsupported
by this v2 producer/reader; no missing-format inference is permitted.

`recovery_review::review_restore_input` composes the same original command,
dispatcher and tenant review on one borrowed current view. It checks the
archived runtime, each declared retained decoder and each exact required
artifact through installed owners. `RestoreWindow` binds the verified v2
receipt to the complete current row digest and every original namespace/history
association; the snapshot metadata tenant never filters the physical unit.
The first profile refuses changed namespace rosters, incarnations, retirement
states, future generations and a foreign source identity. Proposed histories
remain paused and advance recovery epochs beyond both old and current history.

`ProtectedStoreOwner::review_restore_window` rereads the actual same private
file on a fixed Recovery reader, reviews the same borrowed current view and
retains the original input/audit owner once on that file. Its final short
policy/namespace/native acceptance must consume the actual affine read fence;
ignoring it refuses. Input corruption and stale digests leave the source healthy.
Detached readers retain file/view/request custody and original global capacity
through actual native cleanup. It opens no destination or additional engine.

The operation requires the operator's exact window acknowledgement, immutable
IDs and target runtime. Failed current access, stale acknowledgement, missing
evidence, deadline expiry and capacity refusal remain healthy review failures;
actual malformed source history retains its corruption disposition. Eleven
registered source schedules cover these boundaries with selected-engine rows,
full tenant accounting and original rejection/inbox/uncertain work. They have
not been compiled or executed under the native hold. Three use the actual
rooted engine/file/fixed-worker keeper with controlled reviewers. The upper receipt builder
is controlled metadata; it does not certify protected archive readback.

This review emits bounded descriptions, not an import batch, fresh witness,
checkpoint, current policy grant or resume approval. The production caller must
reread the original protected snapshot under the same Recovery custody and
retain original authorization, audit, memory and deadline through its reply.
Fresh destination admission and external checkpoint/clock/role installation
remain Root-owned. Staged imported rows still require complete original linked
validation. A restored Pending/no-attempt effect may have succeeded after the
backup, so neither this review nor an old due index authorizes automatic send,
redrive, garbage collection or restoration of source control authority.

A retained technical-abort fence proves only its original schema/recovery
history. An explicit retry may have completed after the backup and disappeared
from older restored rows. New `PreparedAdmission::retry` therefore compares
the original terminal NV2 epochs with the same current namespace history,
and retains exact history and global recovery-guard CAS observations through
the actual writer. A changed history requires recovery; neither an old abort
nor a reviewed global guard renews that proof. Namespace generation changes
alone preserve the original fingerprint and user preconditions. Fresh work
positively aborted in the current history retains the explicit retry path.

Recovering an already accepted retry receipt stays a historical read under
present access checks, without a new attempt or rewritten result. Six source
schedules cover those paths, including exact absent/present history and guard
races before acceptance and retained original results after reopen. They are
registered but have not been compiled or executed under the native hold.

`RestoreReconciliationPlan::capture` reviews the actual staged unit on the same
borrowed view. It binds the original restore operation, snapshot and acknowledged
window to the exact paused recovery guard and every proposed namespace history.
It reuses complete command, effect, payload and tenant validation with the
installed original runtime/artifact/decoder owners. Root must still establish
the fresh destination, validate the archived bytes during import and install its
own identity, mode marker, checkpoint, clock, role and audit controls. This plan
does not supply those approvals or a restore writer.

All nonterminal effects remain unknown since the snapshot, including Pending
without an attempt and an old KnownFailed receipt. Neither row authorizes another
send. Counts also preserve pending commands, inbox identities, historical aborts,
expired command floors and unfinished migration/management operations. An expired
management plan still requires its real receipt; expiry proves no retirement.
Its original plan, receipt, counter, slot and reservation codecs now contribute
their own format descriptors to the required recovery inventory. Missing support
refuses the review without dropping the protective rows.

Effect pages retain the actual original effect association, supported record
version and completed attempt where history exists. They disclose no payload
body or credential and distinguish original provider acknowledgement, positive
provider confirmation and administrator termination. A Pending effect receives
no invented attempt. Finite pages preserve native continuation even when short;
the affine cursor belongs to that exact retained native view and cannot move to
another request/view. The original current read/audit/capacity owner and deadline
remain required through the physically encoded reply.

`require_terminal_review` is a conservative prerequisite on that same view and
current request. Pending commands, any nonterminal effect or unfinished original
operation refuse. A successful prerequisite does not modify the recovery guard,
activate namespace history, grant a provider operation or resume a dispatcher.
Fresh current policy, physical retirement, external continuity and explicit
operator resume remain independently required. A stale plan is never refreshed.

Seven registered selected-engine source schedules cover Pending/KnownFailed/
uncertain facts, exact original attempts, bounded native continuation and foreign
cursors, changed guard/window/history/runtime, expired protective plans, pending
commands, declared versus provider facts, current-access/deadline refusal and
missing/corrupt linked rows. The staged fixture charges every history update
through the original tenant owner. Its archive receipt and access callbacks are
controlled metadata fixtures; it does not prove Fresh restore, authenticated
management or the essential real remote-success/older-Pending campaign. Native
compilation, execution and strict Clippy remain pending the resource hold.
