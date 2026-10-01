# Finite effect management plans

The dispatcher catalog stores an attributed original-operation plan and a separate
historical receipt for redrive, provider reconciliation, or administrative terminal
disposition. Both use the same selected atomic engine as commands, effects and
physical-attempt history. Their data never supplies a grant. The authenticated
gateway must retain its original current operator, publication, namespace and
data-read decisions and apply the prepared batch under the actual writer fence.

A plan binds the exact supported effect-row bytes, immutable command/caller and
namespace incarnation, original operation ID, action, policy precondition, reason
and full original request digest. It retains the last completed physical attempt
from the coherent history row. A recovered dispatcher row may have a newer owner
epoch and claim generation; those replacement stamps cannot describe the original
provider attempt.

Planning preallocates a 40 KiB logical disposition reservation in the engine. The
future write consumes that reservation atomically with the receipt, new effect
row and any due-index change. A supported admitted plan can therefore complete
at the configured logical byte high-water mark. This does not reserve device
bandwidth or make unreadable/stuck storage available. New planning can fail with
capacity pressure. Each effect has at most 128 plan slots, including abandoned
plans, and each plan lives for at most 30 seconds. Expiry does not discard its
protective reservation or historical identity. Authorized retention owns cleanup.

Redrive of a known failure before the durable send boundary uses the affirmative
nonexecution fact and requires actual physical retirement at acceptance. Unknown
send outcome needs the installed provider's qualified same-payload/profile
deduplication horizon. Delay is finite and cannot cross that horizon, the original
intent expiry, or the attempt ceiling. The runtime must recheck the original
effect rules at the final acceptance fence; a newer publication cannot renew them.

Provider reconciliation accepts a typed positive receipt from a status lookup
through the existing sealed provider grant. Absent, expired, conflicting or
ambiguous remote status remains uncertain and cannot authorize another send.
Confirmation records the provider observation time separately from local receipt
completion. An administrator may stop future local dispatch, but that declared
disposition creates no provider acknowledgement, nonexecution proof or automatic
payload purge. Both paths preserve immutable physical-attempt history.

The unmanaged effect row retains exact `LER` format 1 encoding. A committed
management stamp uses independently decoded `LER` format 2; old format 1 rows are
not silently rewritten. Plan, receipt and bounded slot/counter/reservation rows
have their own closed formats. Coherent startup validation rejects orphaned
records, missing reserved disposition capacity and unsupported formats instead
of treating them as absent work.

The native catalog tests exercise actual engine snapshots, CAS, reopen, history
and high-water accounting. These tests qualify the catalog substrate. The public
authenticated adapter, CLI/node acceptance and full Phase 4 management scope
remain separate integration requirements of [issue 400](https://github.com/KirilsTurkins/latent-service-fabric/issues/400).
