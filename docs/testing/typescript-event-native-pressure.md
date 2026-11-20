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

## Reproduction and evidence limits

```sh
python3 -m unittest \
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

The normal source-owned engine build and strict signed Fetch programme must
qualify the combined source. No diagnostic binary is a production input and no
historical or modeled pass substitutes for that gate.

## Declaration boundary

The signed Fetch attempt on PR #2156 head `3d88e6d`, run `44616090286`,
job `135963175967`, stopped at strict typechecking before guest execution.
Artifact `14585192162` (SHA-256
`6e8c8838c845ae05e30ecb1fe628a24416f91ae6e3f501ce2bbbd710f59e0103`)
retains TS2345 for adding and removing the non-abort `fanout-fill` listener.
The runtime declarations had incorrectly restricted both methods to `abort`.

The declarations now accept string event names, matching the selected native
EventTarget methods inherited by AbortSignal. Callback and option types are
unchanged; no browser globals, new runtime API, casts or typecheck suppressions
are added. The source signal, positive held-listener requirement and every
signed refusal/recovery assertion remain unchanged.

The existing networking compiler-boundary job now also runs the strict
declaration controls using its already installed, lock-checked frontend. The
controls compile the actual fan-out helper source, reject the old abort-only
declarations, and reject invalid event/callback arguments and undeclared browser globals. Missing tools,
skipped controls and compiler errors fail this explicit gate. The full ordinary
component build and signed programme remain separate mandatory steps.

```sh
LSF_TYPESCRIPT_FRONTEND=/path/to/installed-tools \
  python3 -m tools.tests.test_typescript_abort_declarations
```
