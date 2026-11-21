# TypeScript EventTarget native allocation pressure

## Observed failure

On PR #2161 head `644711813efc3bc34cfdd3dcdb54ae5c88132c05`, signed
Fetch run `44583246210` fails `abort-fanout` after 17 preceding cases. Its
retained component has SHA-256
`cc340a315c269301324fd139cca5d2b263f8f85a4b1b0cfce9cedf6cbe6bb865`.
The failure is not evidence that cleanup physically completed.

An isolated replay of that exact SpiderMonkey core with diagnostic runtime
imports reproduces the native-register refusal at the unchanged 64-owner
ceiling during listener registration. Its rejected export subsequently reaches
a closed formatted-output path, producing the visible `unreachable` trap.
The diagnostic imports are not the signed node or original activation ledger.

Reusing the same core's existing Promise pressure-collection prefix before
listener registration makes ordinary nine-way fan-out return its expected value
without increasing the diagnostic owner limit. This identifies avoidable dead
ownership before registration; it is not fresh signed qualification of the
source change below.

## Rooted preflight, non-collecting admission

`prepare_native_object_allocation` uses the existing Promise pressure checkpoint.
It rejects a pending exception, unavailable activation, or stopped native
retirement state. Collection still requires physical finalization, the original
collection-end notification, and successful acknowledgement of each original
owner. Reachable objects and failed acknowledgements never create capacity.

`EventTarget::add_listener` calls this preflight only after conversions and the
duplicate/aborted-signal checks. Its inputs remain Handles or RootedValues. The
rooted target retains its non-moving native listener list; the lookup cursor
has been discarded, and only a removed record's integer index survives collection.
The new listener, its captures, and any abort terminator do not exist yet.
Duplicate registrations still bypass preparation and admission.

`admit_native_object` intentionally does **not** collect. Abort graph, Fetch,
and listener publication paths may hold staged native captures or weak-set
cursors that are not safe across a newly introduced collection. In particular,
the second admission for an abort terminator cannot collect over a staged
listener. Both admissions and every fallible allocation must succeed before
publishing the new listener identity.

## Refusal control

The refusal probe fills the existing source signal with listeners for the
separate `fanout-fill` event type instead of first allocating an unrelated
EventTarget container. No fill callback can run during abort dispatch. The
probe still requires at least one held listener, both the filler-registration
and fan-out refusals, unchanged root/dependent state, removal of every held
listener, the ordinary awaited Promise checkpoint, and successful explicit
retry of the same nine-dependent graph. All reason, order, fresh-state,
no-network, budget, deadline, and cleanup assertions remain in force.

## Strict declaration boundary

Signed Fetch run `44620650191` at `0d7c4fa3` compiled the source-owned engine,
but stopped before guest execution: the shipped AbortSignal declarations
restricted both listener methods to `"abort"`, rejecting the existing
`"fanout-fill"` control with TS2345. The declarations now accept string event
names, as the inherited native EventTarget methods already do. Callback and
options types are unchanged. This neither adds an API implementation nor
casts away the refusal probe's type errors.

The existing signed Fetch job runs the following check after installing its
locked compiler. It uses the unchanged full probe, real Jco-generated WIT
bindings and selected runtime declarations, without DOM or Node ambient types:

```sh
python3 tools/check_typescript_abort_event_types.py --tools /path/to/pinned/frontend
```

The check requires the repository-pinned Node and TypeScript versions. It
rejects numeric event names, invalid listeners and invalid `once` values.
Independently restoring either old abort-only signature must reject the
unchanged signed source; restoring the current declarations must compile again.
These are compiler observations, not signed execution or retirement evidence.

## Recovery across an awaited Promise

Signed run `44701843668` at `afad3f21` passed compilation and ordinary fan-out,
then returned `diagnostic:abort-fanout:checkpoint:native-admission`. Artifact
`14618760997` retains that failed signed attempt. Its cleanup observation does
not prove physical retirement.

A replay of the retained engine with finite diagnostic broker imports narrows
the failure beyond the returned diagnostic. The filler listener is actually
removed and its original owner acknowledged at the next collection. The graph
and generated task still retain 63 native owners. The recovery Promise takes
the final slot, so its reaction cannot be admitted. Raising the ceiling or
refunding still-live Promises would conceal this boundary.

The selected source-splicer path now derives a lazy **private task completion
capability**. Construction retains the original exit capability, task queues,
metadata, and settlement handler. The completion Promise and its resolving
functions are created on the first `completionPromise()` observation, or at
`onResolve` entry before detaching any original handler. The same real Promise
is retained thereafter. Settlement creates it even without observers, preserving
thenable assimilation and unhandled-rejection reporting rather than buffering
results or substituting a custom Promise implementation. The factory must
succeed before publishing either field. The original completion handler drops
its resolver captures only after they are no longer needed; their native owners
still require actual physical retirement and acknowledgement.

The derivation checks the exact rewritten AST shapes and use counts, rejects
extra private uses, reserved-name collisions and repeated adaptation, and leaves
unrelated task methods unchanged. The ordinary compiler path is not adapted.
Both derivation files were already included in the captured compiler recipe.

Deferring completion alone admits the awaited checkpoint but still reaches the
limit on the resumed job's explicit abort retry. `AbortSignal::abort` therefore
uses the existing pressure preflight after its pending-exception and
already-aborted checks, **before** the default exception factory, weak-set
cursors or fan-out staging. Its signal and reason are rooted handles. This
collects only dead earlier-job owners; the live nine-dependent graph remains
charged. Low-level admission remains non-collecting, and failed preparation
cannot publish reasons, allocate the fan-out vector, or dispatch callbacks.

The diagnostic rebuilds the real generated bindings with the retained engine.
Its abort preflight is a private insertion of that engine's existing compiled
collection/checkpoint code, not a fresh C++ engine build. The diagnostic fails
with only the completion change, and returns the original success value with
both changes at the same 64-owner ceiling.
The latter still observes both required refusals before recovery. Replays of the
other non-network event, abort and combinator cases also retain their original
results. These are diagnostic broker observations, not signed-node or original
activation-ledger qualification. The guest probe, same-root retry, positive
filler, budgets, deadlines and strict signed-result assertions are unchanged.

## Reproduction and evidence limits

```sh
python3 -m unittest \
  tools.tests.test_typescript_native_task_meta \
  tools.tests.test_typescript_native_object_pressure \
  tools.tests.test_typescript_event_ownership \
  tools.tests.test_typescript_abort_any_ownership \
  tools.tests.test_typescript_fetch_runtime
```

The pressure tests compile the actual production collection, preparation,
admission, and retirement bodies with finite GC/broker doubles. They cover
reachable-owner refusal, acknowledgement failure, missing collection-end,
pending exceptions, snapshot refusal, exact dead-owner reclamation, and the
non-collecting admission boundary. Emitted listener tests cover preparation
failure before publication, retained removed identity, and duplicate handling.
Node controls additionally exercise the refusal probe with only one filler slot
available. These controls do not establish SpiderMonkey compaction, signed-host
custody, or whole-runtime byte accounting.

Task controls run the original and adapted generated class with real intrinsic
Promises, including early observers, settlement without observers, thenables,
throwing getters, unhandled rejection, reentrant observation, queue contention
and factory refusal before publication. Emitted abort controls additionally
require pending-exception preservation, already-aborted no-op and refusal before
reason construction or graph mutation.

The normal source-owned engine build and strict signed Fetch programme must
qualify the combined source. No diagnostic binary is a production input and no
historical or modeled pass substitutes for that gate.
