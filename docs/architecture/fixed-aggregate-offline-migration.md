# Fixed aggregate migration

The protected v2 migration selects one closed host recipe:

| Recipe | Fixed business key | Immutable definition |
| --- | --- | --- |
| `lsf.aggregate-migration.v2` | `count` | [Protected aggregate recipe](../../contracts/state/aggregate-v1-to-v2-protected-migration.json) |
| `lsf.java-aggregate-migration.v2` | `aggregate/count` | [Protected Java aggregate recipe](../../contracts/state/java-aggregate-v1-to-v2-protected-migration.json) |

Both preserve the unsigned 64-bit count while changing the exact
[aggregate-v1](../../contracts/state/application-aggregate-v1.schema.json)
eight-byte value to the tagged twelve-byte
[aggregate-v2](../../contracts/state/application-aggregate-v2.schema.json) value.
Tenant, namespace, incarnation, physical/logical key, original command/effect/
inbox identity and retained payload/source associations stay intact. These are
fixed single-cell transforms, not a shell, guest, plugin, request-selected key or
arbitrary application migration. Extra state cells/entities, wrong media/bytes,
missing values, unsupported retained formats and insufficient quota refuse.

## Original checkpoint and current owners

Close relevant admissions and drain actual command/query/commit/consumer/
dispatch/maintenance owners before exclusive custody. A flag, timeout or dropped
waiter is not retirement proof. The current
[ProtectedStoreOwner::migrate_aggregate](../../crates/latent-state/src/protected_store/migration.rs)
uses the same protected snapshot custody, native reservation, fixed Recovery
workers and original absolute deadline; it does not reopen an arbitrary engine.

[VerifiedMigrationCheckpoint](../../crates/latent-state/src/recovery/migration/checkpoint.rs)
comes from inspecting actual bounded snapshot-v2 bytes and their installed row,
linked inventory and immutable artifact owners. The source row digest covers
namespace, state, results, attempts, inbox, outbox and maintenance changes,
including those without a business-generation increment. A manifest description
or application schema declaration cannot construct that checkpoint authority.

The request retains operator/operation, exact old opaque view token, checkpoint
and manifest digests, target package digest and immutable review evidence.
`ReviewedSchema` must cover the actual old/new readers and new writer. Installed
`AggregateMigrationOwners` validate artifacts, original linked work, current
publication/policy/audit and conservative clock continuity. Their short `accept`
fence must consume the same native gate under those authority fences. No
callback may run guest/provider work or renew the operation's deadline.

## Stage, complete and resume

1. Stage validates the exact source, recipe, quota and checkpoint, then atomically
   publishes paused history and durable progress. Business bytes and schema stay
   unchanged. Repeating Stage returns original progress and cannot complete it.
2. Complete explicitly continues that reviewed operation. It reinspects the same
   checkpoint and linked rows, normalizing only its attributable stage marker.
   One atomic envelope changes the fixed cell, namespace schema/schema epoch,
   business generation, progress and exact tenant-accounting category deltas.
   Recovery epoch is preserved. History and namespace remain paused.
3. [Migration resume](../../crates/latent-state/src/protected_store/resume.rs)
   separately rechecks the original checkpoint, completed progress, current
   schema/publication, retained work, clock, policy and audit. Its review/accept
   hooks default to refusal. A restored migrated history uses the distinct
   [restored migration resume](../../crates/latent-state/src/protected_store/restored_resume.rs)
   with the acknowledged restore window. Generic namespace resume cannot replace
   either original checkpoint-bound owner.

The current progress has a closed version-2 codec bounded to **8 KiB** and the
retained format identity `latent.aggregate-migration.v2`. Recipe identity and
progress-format identity are separate. Replay preserves original operation,
namespace/history and receipt associations after current authorization; changed
input, checkpoint or review conflicts. Accepted physical work and response bytes
stay charged through actual retirement, even after waiter loss. Interrupted
progress never automatically completes or activates on restart. Possible
commitment uses original durable recovery rather than a new operation key.

Old-reader rollback refuses after the actual tagged schema change. Code rollout
cannot downgrade business data or reverse external effects. Explicit
[older-history restore](reviewed-older-history-restore.md) preserves original
business identities, advances recovery epoch and stays paused for reconciliation.

## Retained v1 profile and qualification

The original [v1 recipe](../../contracts/state/aggregate-v1-to-v2-migration.json),
`OfflineRecoverySource::stage_aggregate_migration`/`complete_aggregate_migration`,
`lsf.aggregate-migration.v1` retained identity and 16 KiB progress remain under
[recovery::v1](../../crates/latent-state/src/recovery/v1/migration.rs).
They are not the protected v2 producer. V1 writers reject installed v2 accounting
or progress; there is no automatic fallback or format upgrade.

The [earlier native receipt](../testing/recovery398-migration-native-evidence.json)
records 153 State cases at its immutable source
`0c9a700eb809158e73633a35b29ba6bcc3f3512a` with a synthetic host reviewer. It
cannot qualify later v2 custody, signed Java execution or deployment/canary/
rollback integration. The [installed gateway](../testing/installed-transaction-recovery.md)
now composes explicit migration/resume actions with reviewed signed Java sources;
full retained-effect/inbox, terminal/pending native and packaged campaigns retain
their separate acceptance gates.
