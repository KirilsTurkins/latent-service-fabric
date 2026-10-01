# Finite effect management plans

The dispatcher catalog stores an attributed original-operation plan and a separate
historical receipt for redrive, provider reconciliation, or administrative terminal
disposition. Both use the same selected atomic engine as commands, effects and
physical-attempt history. Their data never supplies a grant. The authenticated
gateway must retain its original current operator, publication, namespace and
data-read decisions and apply the prepared batch under the actual writer fence.

Recovery-scope selectors resolve through immutable, bounded installation
bindings before native admission. An absent selector selects the authenticated
original caller; an unknown selector or incompatible service principal fails
before lookup. A configured shared or delegated scope describes the target and
still requires current publication and data-read permission. It supplies no
grant, and the bindings cannot be replaced after the backend is shared.

Dispatcher pause/resume and manual effect writes share the acceptance order:
dispatcher role, original operator policy, state policy and namespace lifecycle
when applicable, original effect rules, then the original native request gate.
Protected-clock observations and bounded metadata cloning happen before the
role lock. No callback performs disk/network I/O, audit flush or an async wait
inside these fences. Native control tests also observe pending resume inside the
actual writer before durability, after the short acceptance locks have retired.

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

The retained policy configuration digest describes the exact consumer
publication, configured policy IDs/revisions/documents and provider binding.
Inspection and an approved action share this precondition despite different
operation labels or remaining budgets. The original retained decisions still
recheck their real owners and namespace lifecycle together. Hash equality never
supplies authority and a replacement configured grant cannot revive old stamps.

The redrive rule fence intersects current narrowing with the original effect
ceiling and expiry. It holds only through final acceptance, allocates no provider
work and is dropped before disk or network I/O. Typed audit actions distinguish
planning, reconciliation, redrive, terminal declaration and historical receipt
read without changing the numeric identities of existing audit actions.

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

The installed dispatcher now exposes `plan_effect_retained`,
`mutate_effect_retained` and `lookup_effect_receipt_retained` on its existing
management handle. Every database job borrows the same protected engine through
its actual `RecoveryRead`/`RecoveryWrite` partition. The final writer fence checks
the installed dispatcher role, retained policy/publication and namespace,
original effect rules for redrive, and original native request reservation, in
that order. Namespace row CAS and durable plan/receipt/effect/history links share
the actual atomic writer. Healthy domain refusal does not quarantine storage.

An explicit status lookup has four bounded physical lookup slots and an
independent management tenant/effect admission partition. Its provider job uses
one reserved fixed worker, two queued jobs, four accepted jobs and 8 MiB of the
same dispatcher worker owner. Ordinary jobs cannot consume these reserves.
Accepted provider cleanup, positive receipt persistence and unclaimed completion
buffers retain the original request owner after caller disconnect. Actual device
stalls or exhausted live provider sockets may still fail finitely; admission does
not steal live physical work or fabricate retirement.

Fresh current operator/read authority can look up the original provider attempt
after execution expiry or revocation. The immutable `ReconcileOnly` purpose
cannot authorize an ordinary send or redrive. A positive provider fact changes
the disposition only after real provider cleanup and an exact original effect
row/version fence. Missing, expired or conflicting status leaves the original
uncertain fact and preallocated plan intact. A plan expires within 30 seconds;
reconciliation expiry does not renew the old execution lifetime. Historical
receipt reads and known receipt replay remain available after plan expiry under
fresh current read authority. Restore review blocks new redrive and generic
resume, while permitting authorized lookup and administrative stop.

The native catalog and worker tests exercise actual engine snapshots, CAS,
reopen, history, high-water accounting, protected workers and original global
native admission. The 113-case Linux effects suite and strict all-target,
all-feature Clippy pass include current management revocation, detached lookup,
ordinary saturation, stale plans, affirmative nonexecution redrive, original
execution revocation, restore review and unsafe uncertain redrive refusal.
The controlled lookup adapter in these worker schedules is distinct from the
actual TLS/provider qualification. The public
authenticated adapter, CLI/node acceptance and full Phase 4 management scope
remain separate integration requirements of [issue 400](https://github.com/KirilsTurkins/latent-service-fabric/issues/400).
