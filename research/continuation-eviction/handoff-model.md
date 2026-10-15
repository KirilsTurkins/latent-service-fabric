# Proposed durable continuation handoff

This is a semantic model for research, not an installed protocol or API. The
[workflow traits](../../crates/latent-workflows/src/lib.rs) do not implement these
transitions. Use an explicit finite state-machine reference before adding a
compiler frontend; the reference alone would not complete compiler research.

## Identities and authority

Keep these identities separate and host-controlled:

| Identity | Proposed responsibility |
| --- | --- |
| Workflow instance and recovery domain | Tenant-scoped business lifetime, stable across separately admitted segments. A restored older history must not be mistaken for the current one. |
| Definition and continuation schema | Exact code/publication, compiler transform and resume-label/state format. Public function compatibility alone is insufficient. |
| Transition version and segment attempt | Compare-and-advance ownership fence; attempts are bounded and do not mint a new business operation. A numeric attempt in guest bytes is not proof of exclusivity. |
| Wait and signal/effect identity | Bind a durable result to its original workflow generation and wait. A correlation string alone is not authority or sufficient deduplication. |
| Physical execution owner | Cell/Store, accepted callbacks, buffers and provider/child reservations, plus evidence of actual retirement or enforceable fencing. |

The host binds these to a bounded continuation envelope independently of opaque
application state. A guest-supplied program counter, tenant, publication or ledger
must not select arbitrary host authority. Validate resume labels and state shapes
against the exact admitted compiler schema; never deserialize executable closures
or arbitrary native pointers as a shortcut.

Every new segment requires current publication eligibility, installed providers,
exact grants, required audit, real scheduler capacity and new host bindings.
Historical authority is not restored. Define who may signal, cancel, inspect,
migrate and resume a workflow, including any permitted principal delegation.
Checkpoint integrity or possession of an instance ID grants none of those rights.

## Durable position, readiness and cleanup are independent

Track at least these independent facts rather than relying on one `Suspended`
flag: durable transition disposition; wait/result readiness; old physical-owner
retirement; current resume claim; and cancellation/terminal disposition.
Readiness may arrive while cleanup is incomplete. Record it without allowing a
second execution or losing it when cleanup later finishes.

```text
finite running segment
  -> approved capture and quiescence
  -> conditional durable checkpoint + wait + state/effect-intent transition
  -> old Store/owners retired or safely fenced
  -> ready record + current authority + bounded fresh admission
  -> restore exact state and recorded wait result in a fresh Store
  -> next conditional durable transition or terminal outcome
```

This describes logical ordering; it does not claim all storage objects fit one
existing transaction. An implementation must identify the actual durable commit
point and recovery protocol. If multiple owners/stores participate, prove their
consistent decision rather than assuming cross-system atomicity.

## Capture and durable decision

Start with one task, bounded value state and an approved durable timer or event.
At capture, no unsupported handle, open transaction, borrowed guest buffer or
already-dispatched ordinary provider call may cross the boundary. All guest tasks
must be quiescent or excluded by the selected profile, not merely the root task.

Reserve overlap capacity before encoding: old guest memory, serialized state,
staging buffers, storage metadata and required recovery headroom may coexist.
Check the complete reachable state and byte/object/depth limits before accepting
the durable transition. Serialization failure has a defined original-segment
outcome; it must not leave a supposedly accepted orphan wait.

Bind the checkpoint, wait registration, accepted state changes and any approved
deferred effect intents to one conditional durable decision. Immutable large
payloads may be staged first, but references become committed only after their
bytes are durably available. Bound and collect abandoned staged objects safely.
An unknown commit result requires original-identity recovery, not a new attempt
that blindly repeats the business operation.

External dispatch may begin only from an accepted durable intent under its own
current authorization and ownership. Capture cannot retroactively turn an
ordinary HTTP call into a deferred exactly-once effect. Do not hold a database
snapshot, staged transaction handle or lock across the durable wait; close a
finite transactional segment instead. Existing
[state/outbox/outcome rules](../../docs/architecture/state-and-effects.md) supply
patterns, not an already available continuation commit port.

## Old-owner retirement and exclusive resume

Committing bytes does not destroy the Store. Retire guest execution, instance,
heap, stack, activation-local handles and every callback/provider/child reference.
An explicitly transferred remaining operation needs an affine bounded owner with
all Store/cell references severed and its real charges retained, following
[ADR-0028](../../adr/0028-retain-activation-ownership-across-asynchronous-waits.md).
Failed or uncertain cleanup withholds capacity and uses the declared quarantine
policy. Do not infer retirement from a cancelled future or expired grace period.

A ready claim must not allow the old physical owner to act concurrently. Lease
expiry alone cannot establish that a stalled worker stopped. Fence state/effect
dispatch against stale attempts and require observed retirement or an enforceable
isolation/recovery boundary for the old guest. Process-local cancellation is not
a cross-process fence. A fresh process identity must not reuse an old owner token.

Exclusive durable transition commitment does not mean guest instructions execute
once. A crash before commit can repeat a segment. External effects have their own
accepted/uncertain/completed disposition; a database fence cannot retract a remote
request. Preserve those distinctions in results, audit and recovery tools.

## Wait delivery, cancellation and clocks

An event can arrive before checkpoint publication, during cleanup, before a
worker claim or after terminal cancellation. Define a bounded durable inbox with
atomic match/consume semantics, or an explicit acknowledged rejection/redelivery
contract. A check-then-subscribe gap is insufficient. Define ordered selection
for multiple eligible events, replay retention and overflow behavior; never
acknowledge an event and then silently discard its only recoverable copy.

Duplicate/late events resolve against the original wait and transition version.
One readiness result cannot create two committed resumptions. Persistent
cancellation competes with readiness and claim under the same durable fence;
late delivery cannot resurrect cancelled or superseded work. Cancellation of the
workflow does not undo accepted remote work or automatically retire its owner.
Keep terminal/deduplication records for the declared late-message window.
Claim, decode or restore failure must not consume the only durable wait result;
retain it until a subsequent transition commits its disposition.

Persist timer meaning, not a process-local monotonic instant. Specify wall-clock
authority, restart/rollback uncertainty and conversion into a bounded local wait;
clock failure must not silently extend business or segment deadlines. Ordinary
same-invocation eviction preserves its original absolute deadline. Durable
segments instead need explicit workflow lifetime, total-work, retry and per-segment
limits; resumption must not manufacture fuel, calls or storage allowance.
Reserve a segment attempt's finite allowance against durable workflow accounting
before admitting it. A crash must not refund consumption merely because the worker
could not report it; define conservative settlement for unknown work and retain
physical charges until actual retirement. A lease renewal cannot reset attempts.

## Restore, upgrades and recovery-data retention

Admit restoration against bounded capacity and fair tenant queues. Durable rows
must not each retain a Rust task, sleeping timer, response future or dormant guest
heap. Bound ready batches, claims, payload fetch/decode, restore concurrency and
per-workflow wake storms. Missing capacity leaves durable readiness intact under
the declared expiry policy; it does not justify hidden cells or workers.

Decode only checked application state. Recreate approved host resources with
fresh current authorization; copied Store tokens, transaction handles, credentials
and pointer values cannot regain authority. Bind sensitive state to its tenant,
integrity/access/at-rest policy and retention limits. A checksum detects corruption
but does not authorize resume or stop replay of an old valid checkpoint.

Pin exact definitions and continuation formats for long-lived instances.
Migrations need explicit authorization, bounded transforms, rollback/recovery
rules and tests of saved control positions as well as data. Retained code does
not authorize a revoked release. State the operational outcome if required old
code/schema becomes unavailable; do not restart the business operation silently.

Advance the durable transition before reclaiming superseded checkpoint payloads.
Retain recovery references, wait results, required effects and cancellation/
deduplication records for their actual lifetimes. A continuation may be the only
remaining computation state, so ordinary cache LRU cannot delete it. Backup and
older-history restore need their own recovery-domain and external-effect policy;
do not assume current Phase 4 restore evidence qualifies workflow recovery.
