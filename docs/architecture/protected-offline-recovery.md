# Protected recovery and explicit resume

The current protected v2 workflow uses the existing `ProtectedStoreOwner`,
reserved Recovery capacity and fixed native workers. It exposes bounded
snapshot, inspection, staged restore, adoption and migration operations. It
creates no guest or provider execution owner. The qualified physical storage
profile remains Linux x86-64 with an explicit private local ext4 root.

The [installed recovery gateway](../testing/installed-transaction-recovery.md)
composes authenticated operator actions with current signed publication,
companion/schema, policy, audit, checkpoint and clock owners. That page owns the
closed request fields, configured capacity and remaining native campaigns.
The ordinary [result-recovery CLI](../operations/transaction-recovery.md) has a
separate read/control contract; it does not perform a backup or restore.

## Protected v2 ownership

| Transition | Concrete owner and required boundary |
| --- | --- |
| Snapshot | [ProtectedSnapshot](../../crates/latent-state/src/protected_store/snapshot.rs) retains the same native reservation, private file and exclusive custody. Installed row, artifact and linked-closure reviewers validate one actual engine view. |
| Restore inspection | [review_restore_window](../../crates/latent-state/src/protected_store/restore_input.rs) rereads the original snapshot and current source view, then exposes the exact loss-window acknowledgement. Its read fence supplies no write permission. |
| Fresh staging | [stage_restore](../../crates/latent-state/src/protected_store/restore_stage.rs) requires separate fresh private store/checkpoint roots, creates destination files exclusively, persists `Staging` before import, preserves business rows and replaces archived controls only through installed current owners. Every write consumes its original fence. |
| Paused adoption | [RestoreAdoptionPlan](../../crates/latent-state/src/protected_store/restore_adoption.rs) requires actual source and staged-resource retirement, original file identities and fresh current reviews. Its startup publishes the same restored root paused; matching receipt bytes are insufficient. |
| Migration and resume | [migrate_aggregate](../../crates/latent-state/src/protected_store/migration.rs), [resume](../../crates/latent-state/src/protected_store/resume.rs) and [restored resume](../../crates/latent-state/src/protected_store/restored_resume.rs) retain the original checkpoint and current schema/policy/clock fences. Completion alone cannot activate business work. |

Before exclusive custody, close affected command, query, consumer, dispatch and
maintenance admissions, quiesce the selected namespace roster, and drain actual
commit, view, native-request and dispatcher owners. A paused flag, dropped
waiter or elapsed drain deadline cannot replace physical retirement. Accepted
work retains its reservation, buffers and native resource through cancellation;
uncertain ownership remains charged and closed to business work.

Snapshot and staged destinations use explicit private roots and safe leaf names.
Creation is exclusive. Existing partial exports or failed staging roots remain
operator evidence and cannot be overwritten by a retry. The snapshot records the
complete source-store identity. Restore also selects and verifies the actual
new destination identity; neither a path nor a configured identity proves that
its physical files are fresh. State v2 uses `dataDirectory/state`; adoption needs
the reviewed installation layout and a separate fresh checkpoint root.

The [logical format bounds](logical-recovery-snapshot.md) are ceilings, not a
reservation sufficient for every installation. The General protected profile
uses an 8 MiB callback footprint; SingleNamespace uses 7 MiB, one namespace and
at most a 2 MiB row. Native custody separately charges paths, descriptors, staged
engine cache and response owners. The installed gateway applies narrower
manifest and aggregate capacity limits and refuses excess before destination
creation. Its original absolute deadline is not renewed by inspection, replay,
shutdown or a lost response.

## Reconciliation and activation

Completed import validates the full staged linked view, advances each live
recovery epoch and leaves the guard `ReconciliationRequired` with histories
paused. Business incarnation, command, attempt, effect and inbox identities
remain unchanged. The [recovery guard](offline-recovery-guard.md) and
[older-history restore](reviewed-older-history-restore.md) define those fences.

An authorized review must reconcile present publication/result/provider/consumer
permission, original deduplication and grant horizons, conservative time, newer
commands and any external work that may have happened after the snapshot.
A Pending row is no evidence of remote nonexecution. Global review does not
activate namespace histories or instruct effect redrive. Namespace activation is
a separate exact-token operation; a retained migration instead requires its
specific checkpoint-bound resume path. Unfinished migration cannot use generic
resume. Historical grants and receipt replays never supply current authority.

## Lost staged-restore responses

While the original `ProtectedSnapshot` custody remains owned, drop the lost
response object, inspect the same input with `review_restore_window`, and call
`recover_restore_receipt` with the same operation, operator, runtime and window
acknowledgement. The response uses its original reservation and absolute deadline.
It cannot replace snapshot custody or extend the operation.

Receipt recovery performs no import or durable write. Installed owners reread
the snapshot, source window, destination rows and checkpoint, validate the
completed linked view and current role/audit/controls/clock, and consume the
final read fence. The destination remains paused. Different inputs, partial
staging, changed checkpoint, revocation or expiry refuse. Adoption preparation
also closes this read path. After custody retirement or process restart, use
explicit restored-root review and adoption; an in-memory description provides
no new-boot authority.

## Retained v1 facade and evidence

`latent_state::recovery::offline::OfflineRecoverySource` explicitly re-exports
[the v1 offline facade](../../crates/latent-state/src/recovery/v1/offline.rs).
Its `RecoveryCodecs`, `start_review`, `resume_namespace` and 32 MiB scratch
profile describe that facade. They are not the protected v2 API above. V1
snapshot/migration/resume bytes retain their own identities, 16 KiB migration
progress and installed review requirements. Its writers reject installed v2
tenant accounting/progress; there is no format fallback or automatic upgrade.

Finite engine fixtures and historical receipts retain their recorded source,
reviewer and retained-work scope. An empty inventory cannot certify real
state/outbox/inbox closure or the case where a remote effect succeeded after a
pending snapshot. The current native gateway supplies composed actions, while
its full terminal/pending, application and packaged acceptance remains separate.
Backups contain sensitive application data and are never public test artifacts.
