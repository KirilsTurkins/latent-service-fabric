# Reviewed older-history restore

The current [RestoreWindow::capture](../../crates/latent-state/src/recovery/restore.rs)
compares an inspected snapshot-v2 with the actual quiesced source view under
the original deadline and current review callback. The complete source-store
identity, tenant/namespace roster and business incarnation must match. A snapshot
generation ahead of the source refuses. Its canonical digest includes exact
namespace/history records and every current logical row; attempt, inbox, clock
or effect changes invalidate an old acknowledgement even without a business
generation increment.

The snapshot runtime must match the installed retained decoder profile exactly.
Application reader compatibility cannot authorize a runtime upgrade/downgrade,
missing decoder or new provider permission. Snapshot and window descriptions
supply neither physical quiescence nor destination-import authority.

## Protected v2 import

[review_restore_window](../../crates/latent-state/src/protected_store/restore_input.rs)
retains the actual protected snapshot and source view.
[stage_restore](../../crates/latent-state/src/protected_store/restore_stage.rs)
consumes that reviewed input, exact operation/operator/runtime and loss-window
acknowledgement under mandatory installed write owners. It uses separate fresh
private store and checkpoint roots and the explicit destination store identity.
Existing roots, logical emptiness or matching filenames are not Fresh evidence.
Capacity, current source and authorization checks precede destination creation.

The destination persists `Staging` before importing. Original business, command,
result, rejection, attempt, inbox, outbox, ordering and payload identities remain
unchanged. Archived authority/control rows are not installed as permission;
only the installed current-control owner may replace their closed row classes.
Complete staged row/payload/decoder closure and protected file identities must
validate before the guard leaves `Staging`. Stream integrity alone is insufficient.

Each history advances its recovery epoch to `max(snapshot,current)+1` and stays
paused. Business incarnation, original snapshot generation and schema identity
are preserved. Old query minimum tokens and edit preconditions fail across the
new epoch even when recovered business bytes and generation match. A receipt
cannot authorize silently refreshing those original preconditions.

Truncation, linked corruption, quota/deadline exhaustion or failed review leaves
the source untouched and any partial destination closed in `Staging`. Lost
ownership after a possible write remains uncertain, requiring original-identity
recovery. A retry cannot reset or overwrite that root. The
[protected recovery guide](protected-offline-recovery.md) explains bounded lost
stage-receipt recovery while original custody is still live.

## Adoption and reconciliation

[Paused adoption](../../crates/latent-state/src/protected_store/restore_adoption.rs)
requires actual native retirement, retained original root/file/checkpoint
identities and fresh current role, audit, publication, clock and linked-view
reviews. It opens the same destination as a still-paused owner. Source identity
and requested destination identity are distinct; the configured restored node
must select the identity actually returned by restoration.

Before business resume, explicitly reconcile current result/provider/consumer
permission, grant and deduplication horizons, conservative clock continuity,
uncertain attempts and post-snapshot commands/inbox history. Restored Pending
rows do not prove an external action never happened. Review acceptance neither
renews historical authority nor automatically resumes command ingress, consumer
delivery, dispatch or expiry. Migration-bound histories require their specific
resume owner rather than generic namespace activation.

The original `RestorePlan::prepare`, `prepare_until` and `execute_checked` APIs
remain under [recovery::v1::restore](../../crates/latent-state/src/recovery/v1/restore.rs).
They describe the retained v1 facade, not the current v2 stage/adoption API.
The [installed qualification](../testing/installed-transaction-recovery.md) keeps
finite engine proof separate from the full native/application terminal and
pending campaigns; an empty retained-work fixture establishes neither campaign.
