# Activation-owned runtime support

The opt-in `activation-owned-v1` host support profile supplies
`latent:runtime/activation@0.1.0` beneath maintained language runtimes. It is
recognized by the V5 host ABI profile. Recognition does not install the bridge,
grant its operations, or qualify any language runtime. Existing direct guest
bindings and frozen V1–V4 sources remain available.

`WasmtimeConfig.activation_runtime` selects explicit finite limits for tasks,
executors, queued work, waits, timers, results and native owners. `None` preserves
the lazy legacy path. There is no product-wide task limit: language and deployment
qualification must select and measure the profile. Installation also needs the
original Phase 3 budget and cancellation tree, an exact capability broker binding
and grant, and an executor-neutral `PreparationReadWait` for timer suspension.
Permission to read either clock does not authorize runtime waits or timers.

## Ownership and closing

Every Store has a host-derived generation and every logical owner has an
unreused ID within that generation. Tokens describe owners and convey no external
authority. Registration checks the original cancellation/deadline, reserves
bounded records before allocation and charges admission work to original fuel.
The runtime's Arc/Mutex, fixed record arena, host owner slots and timer state use
affine native memory reservations on the same activation ledger as guest linear
memory and delegated children. Failed preparation rolls back. Completed work
settles its owner once; an abandoned waiter cannot release a physical provider
owner's reservation.

The four closed, resource-free runtime result shapes retain the accepted broker
call inside the actual Wasmtime return value until canonical lowering completes.
Completed scalar, token and observation results then release their original call,
result and output-window reservations before the next import. Callback return
alone cannot release that owner. The private lowering wrapper delegates the exact
pinned generated ABI, including both memory and flat lowering, and rejects an
upstream binding that requires guest allocation. Pending host futures and owned
stream/list/string resources retain their existing physical owners.

Parking records readiness without running guest code. A wake is valid only for
the original generation and a still-live owner. A weak wake does not keep the
Store or budget alive. The maintained language scheduler must choose a runnable
sibling and supply compiler/runtime checkpoints; this bridge alone does not
establish standard-language sibling progress.

Closing rejects independent new work. A bounded continuation can register only
while its original accepted owner remains live, with the same authority and
deadline. Draining never infers harmlessness from daemon status, sleeping, an
empty queue or managed-idle-worker classification. Ordinary export completion
with any accepted owner still outstanding produces `runtime-lifecycle-unproven`.
Native memory remains charged until its actual owner drops, including after a
frozen terminal report. Trap cleanup follows the existing Store destruction and
quarantine ownership boundary.

## Timers

Relative waits use monotonic nanoseconds. Absolute wall waits sample wall and
monotonic time once at admission and convert the wall value into one monotonic
deadline. Later wall changes do not restart the wait. The effective wait is
bounded by the original root deadline and the broker's narrower call deadline.
Cancellation/revocation or root-deadline expiry wins over requested elapsed
success at the same boundary.

Timers are invocation-local single-shot or fixed-rate recurring registrations.
Zero periods fail. At most one `timer-next` waiter is admitted per timer; that
wait owns a separate bounded wait registration. A recurring timer coalesces
missed periods into one readiness result in constant time and returns the number
coalesced. It creates no catch-up queue, host callback, sleeping worker or detached
task. Language ports serialize or otherwise bound callback execution using their
declared task/queue limits. `timer-stop` cancels readiness, while a physically
retained waiter keeps the timer and native memory charged until its actual drop.

Host Store access ends before the executor-neutral await. The host periodically
observes the original stop and provider-currentness state within a bounded 10 ms
wait interval; this interval neither extends a deadline nor retries an operation.

## Evidence and remaining qualification

Core conformance covers original-budget memory competition, failure rollback,
frozen report retention, bounded registration, close/continuation rules,
generation fencing, opaque-worker retirement rejection and recurring-timer storm
coalescing. The component/linker checks use authoritative WIT, reject missing
installation and wrong versions, and require canonical async types for waits.
Independent policy/schema/source/matrix checks preserve the frozen earlier
profiles and ensure runtime clock resources cannot grant network stream access.

The `local_service` signed component matrix also exercises the actual directory
catalog admission, policy and binding compiler, deployment controller, activation
manager, scheduler, broker and Wasmtime Store. Test signing keys bind the actual
component bytes and the checked-in component builder/runtime WIT source digest.
The other builder materials are fixture assertions; this is not an observed
production compiler build or a qualified language artifact.

Its runtime cases cover each owner ceiling, managed workers sharing the task
ceiling, closing and necessary continuations, stale owner tokens and fresh Store
generations, root-result retirement failure, trap cleanup, canonical timer
suspension with same-Store sibling work, timer stop, recurrence coalescing and
registration storms. Cancellation and policy revocation use a barrier that
observes a real pending timer, Store and broker call. A narrower policy wait
deadline remains a structured deadline result and allows the original root task
to settle. Root deadline and a tight CPU loop remain contained. Each case checks
physical Store/host/instance, broker and activation capacity reclamation before
fresh admission. Revoking a declared import also rejects a fresh activation even
when that path would not actually call the import.

The fixture compares the lazy path with a real registered owner, verifies that
native accounting raises the same original peak, and verifies failed native
reservation rollback. On the pinned Linux debug fixture the four-page lazy guest
reported 262144 bytes and runtime registration reported 263128 bytes. This 984
byte difference is fixture evidence, not a language memory or latency claim.
Growing linear memory to the entire original ceiling while native owners are
live produces resource exhaustion; cleanup preserves the original trap or
interruption instead of replacing it with cleanup cancellation.

Three additional normal-suite regressions exercise 40 completed cycles under
the original 16-call session ceiling, exact import counts, live pending-call
reservations, cancellation/drop, and malformed sync/async result destinations.
Their native execution on this repair remains pending. The prior signed Java
executor failure and its closed `resource-exhausted` receipt are retained; a
successful source repair alone does not qualify the expanded Java profile.

These checks are implementation evidence for #736. Remaining requirements
include the complete signed cross-tenant, late-wake and node-stop matrix,
measured cold/active/parked physical owner plateaus, tenant/node fairness,
standard-language scheduler ports and API-specific error aggregation. ADR-0060
remains Proposed. Language profiles and the larger #695/#677 qualification gates
remain open until those requirements are exercised under their exact source,
compiler, runtime, policy and artifact identities.

The initial [Java fiber integration](java-activation-fibers.md) exercises ordinary
threads in signed components through this bridge. Its broader standard-runtime
profile remains unqualified.
