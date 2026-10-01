# Fixed aggregate offline migration

The first bounded recipe changes the single `count` value from the exact
[aggregate-v1 definition](../../contracts/state/application-aggregate-v1.schema.json)
to the exact [aggregate-v2 definition](../../contracts/state/application-aggregate-v2.schema.json).
It preserves the unsigned 64-bit count, logical/physical business key, tenant,
namespace, incarnation, quota, pins and original command/effect/inbox identities.
The closed [recipe](../../contracts/state/aggregate-v1-to-v2-migration.json) is
immutable source evidence. It does not run a shell, guest, plugin or provider.
Additional keys/entities, missing/tombstoned values, unexpected media/metadata,
inconsistent usage, insufficient quota and arbitrary opaque formats refuse.

The configured host must first stop relevant admissions and dispatch, retire
actual command/query/commit/consumer/maintenance owners and close the normal
engine owner. `OfflineRecoverySource` then acquires the existing protected root
exclusively on the existing fixed storage workers. A long retained view or live
physical owner cannot be replaced by an idle flag. This operation exposes no
ordinary business ports.

The pre-migration checkpoint is an actual protected logical snapshot captured
through the selected engine's consistent view. Its closed manifest contains the
full retained-work and payload/decoder closure, runtime/store identities, old/new
schema definitions, exact selected package and recipe artifacts. Public manifest
descriptions do not construct `VerifiedMigrationCheckpoint`; that private type
comes from inspecting actual bounded checkpoint bytes with installed row,
linked-inventory and artifact validation. The source canonical row digest also
matches every namespace/state/result/attempt/inbox/outbox/maintenance family,
including changes that do not increment namespace generation.

`OfflineAggregateMigrationRequest` carries the protected checkpoint reference,
authenticated operator/operation, exact old opaque namespace token, checkpoint
and manifest digests, exact target package digest and immutable review evidence.
The installed `RecoveryCodecs::migration_schema` supplies tested `ReviewedSchema`
evidence for that actual package: both old/new readers and the new writer. A
request's schema declaration or an authoring fixture's descriptive flags cannot
provide this evidence. Installed `review_migration` also reviews present grants,
conservative clock continuity and retained work; every original required decoder
association must remain available. Current authority is rechecked through the
short no-I/O `accept_migration` callback at the actual physical writer fence.
These new installed callbacks default to refusal.

Two attributable commands form the path:

1. `stage_aggregate_migration` verifies the checkpoint, exact source generation,
   recipe support, current evidence and quota, then atomically publishes a
   paused history and bounded durable progress. Business bytes/schema remain
   unchanged. Repeating this stage returns the same progress; it does not finish
   the migration. Incomplete progress blocks namespace resume.
2. `complete_aggregate_migration` explicitly continues the same reviewed
   operation. It reinspects the checkpoint and all original linked rows,
   normalizing only its own attributable staged marker. One bounded atomic
   envelope updates the existing state cell and usage codec, namespace schema,
   schema epoch and completion receipt. It preserves the recovery epoch and
   increments the actual namespace generation. The namespace remains quiesced
   and its history remains paused for separately reviewed resume.

Each accepted command retains its original deadline, worker, protected root,
checkpoint lock and charged buffers until physical retirement. A detached waiter
does not refund them. Each command uses one physical commit with named-root/file
checks before and after the commit. Interruption, disk/quota failure or final
revocation leaves either unchanged source or durable paused progress; restart
never automatically completes or activates it. Source input/authorization refusal
does not poison a valid current engine. Uncertain irreversible completion remains
recovery-required and uses the same operation key.

Progress has an independent canonical closed codec and retained checkpoint
identity `lsf.aggregate-migration.v1`, with at most 16 KiB per operation and a
finite 128-entry per-namespace resume inventory. No trimming occurs. A completed
operation retry preserves its original namespace/history/view token after current
authorization; it neither repeats the transformation nor substitutes a later
business generation. Changed input, evidence, checkpoint or operation meaning
conflicts. Pending effect IDs, rejection results, inbox identity, ordering and
payload associations are copied unchanged, never interpreted by the new business
schema or moved to the new publication.

Old-reader rollback rejects after the actual tagged data/schema change. Automatic
business-data downgrade and reversal of remote effects are unsupported. A
separate explicit older-history restore retains original business IDs, changes
the recovery epoch and stays paused for external reconciliation.

The maintained portable fixtures exercise the fixed recipe, interruption/reopen,
actual byte/media change, stale checkpoint/linked-row refusal, immutable replay,
input/quota limits and final-fence revocation. Protected-engine execution is
recorded separately against its exact immutable source. Their host package
reviewer is a concrete synthetic test owner. Actual compiled signed Java v1/v2 capsule
execution, deployment/apply/canary/rollback integration, public management/CLI
and complete retained-effect/inbox campaigns remain required acceptance work;
the authoring and finite engine fixtures do not claim those outcomes.
