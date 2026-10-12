# Reviewed older-history restore

`RestoreWindow::capture` compares the inspected snapshot with the actual
quiesced source view. The first profile requires the same tenant, namespace
roster and incarnation, and refuses a snapshot generation ahead of the source.
Its canonical digest includes both exact namespace records and histories and
the bounded digest/counts of every current logical row. Attempt, inbox or clock
changes invalidate an old acknowledgement even without a namespace increment.
`RestorePlan::prepare` requires an explicit operator acknowledgement of that
window and an installed host review. A changed source generation makes the
old acknowledgement stale. Runtime identity must match the installed decoder
profile exactly; application reader compatibility cannot authorize a runtime
upgrade or downgrade.
The physical profile uses `capture_until` and `prepare_until` to retain the
original operator deadline across inspection, review and staging.

The plan checks conservative logical quotas before a destination is created.
Execution requires an empty selected engine, commits its fresh `Staging` guard
before importing, and streams the same inspected input a second time through
the same finite codec. All original business, command, result, rejection,
attempt, inbox, outbox, ordering and payload bytes are preserved. Historical
guard bytes are descriptive and cannot replace the new root's live guard.

After the complete stream digest, original namespace bytes and installed
cross-row/payload inventory validate, each live history's recovery epoch becomes
`max(snapshot,current)+1`. Schema identity, original namespace generation and
incarnation remain unchanged. The final guard becomes
`ReconciliationRequired`; every history stays paused. A prior query minimum
token or state edit precondition cannot become current again in the restored
history, even if its business generation matches.

Truncation, decoder failure, quota exhaustion or an inconsistent linked view
leaves the destination in `Staging`. The current source is untouched. A failed
staging root is never silently reset or overwritten by a retry.
`execute_checked` checks the installed physical owner's named-file fence before
and after every durable staging, import, history and completion write. Fence
loss after a write reports `CommitUncertain` and leaves the root closed.

Current publication, result-read and provider permissions, original effect
identity and deduplication horizon, conservative clock continuity, uncertain
attempts and inbox replay all require explicit reconciliation. Restored Pending
rows are insufficient evidence that a remote action has not already happened.
No command ingress, consumer delivery, effect dispatch or maintenance expiry is
automatically resumed. The core tests exercise actual selected-engine
interruption and token invalidation. The protected physical facade and its
finite native test campaign are described in the
[offline recovery runbook](protected-offline-recovery.md). The complete
state/outbox/inbox and remote-effect reconciliation scenario remains a separate
integration qualification; an empty retained-work fixture cannot establish it.
