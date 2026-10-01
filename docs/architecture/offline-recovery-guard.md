# Paused offline recovery

`latent_state::recovery` owns a bounded durable guard in the selected common
transaction engine. It binds the original recovery operation, snapshot digest
and declared recovery/data-loss window. Its 133-byte closed codec distinguishes
incomplete staging, completed recovery awaiting reconciliation and an explicitly
accepted review. Unknown phases, missing proof, zero identities, truncation and
foreign row keys fail closed. These records are historical descriptions, not
permissions or renewable grants.

Command and query acquisition call `require_ready` on their actual protected
worker-owned view. `StateSession` also captures and charges the bounded guard,
and its final plan compares that exact row, including initial absence.
`CapturedView::recovery_expectation` supplies the same fence for a no-state
disposition. An old logical plan cannot commit after staging begins. Live token
capture also refuses paused namespace or history metadata.

Real dispatch selection calls `require_namespace_ready` with the original effect
tenant, namespace and incarnation. It checks the global guard, active namespace
and ready history. A review of the global recovery window cannot reopen a paused
history, move an effect to a different namespace or bypass an ordered predecessor.
The installed dispatcher still checks original authority, current grant/provider
credentials and its actual owner/attempt fences.

`RecoveryGuard::prepare_reviewed` accepts only a configured host review of the
actual restored view and prepares an exact CAS replacement. That reviewer must
check current publication/grants, retained work, external-effect reconciliation
and conservative time continuity. The normal control owner supplies current
policy authorization at the final physical commit fence. Review acceptance does
not activate namespace histories or itself authorize redrive.

This is the shared guard foundation for #399/#718. Protected logical snapshot
export, staged fresh-root restore and the essential remote-applied/backup-pending
fixture remain separate pending work; decoding or testing a guard is not backup
qualification. Broader operator and migration workflows are not yet delivered.
