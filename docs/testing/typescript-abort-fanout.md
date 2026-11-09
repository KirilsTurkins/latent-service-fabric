# TypeScript AbortSignal fan-out ownership

This is a partial implementation of #745, not whole-runtime qualification. It
changes the source-owned AbortSignal implementation selected by
`spidermonkey-activation-promises-clocks-imports-v1`; it does not add a JavaScript
polyfill, a developer-selected transport, or a new public runtime profile.

## Qualification status

The [integration ledger](typescript-runtime-745-qualification.md) separates
source controls, historical signed observations and remaining #745 obligations.
Run 42516280360 passed nine-dependent fan-out but failed at
`abort-fanout-refusal` with an actual `guest-trap` / `unreachable-code`. The
following default-factory reentry and fresh fan-out cases were not reached,
and the artifact has no post-refusal cleanup sample. The signed programme
remains failed. Host C++ or sanitizer success does not replace that evidence.

## Admission and publication

The pinned engine previously set the root and dependent abort reasons before
appending dependents to a fallible, unowned temporary vector. Allocation failure
could therefore leave signals aborted without running their accepted abort steps.

The derived implementation normalizes and roots the reason, then stages all
currently un-aborted dependents before publishing any reason. A vector that
exceeds its inline capacity first admits one native owner through the existing
original-activation ledger and then reserves its entire backing allocation.
Admission or reserve refusal leaves the root and dependents unchanged. Already
aborted roots return immediately; empty, all-aborted and inline fan-outs do not
admit a separate vector owner.

This is a native **count/model reservation**, not byte-accurate accounting of
vector capacity, allocator metadata, captured objects, engine heap or stack.
The owner is declared before the rooted vector, remains live through nested
callbacks, and is retired only after the backing allocation is destroyed.
Retirement performs no host call. The existing safe checkpoint acknowledges the
original token; a refused acknowledgement retains custody and fences admission.
No GC completion is fabricated for an ordinary GC-owned graph.

## Reentrancy and failures

The pinned StarlingMonkey default DOMException factory looks up the constructor
on its prototype and invokes it. That operation can run application code. The
abort operation therefore constructs the default reason before enumerating weak
links and rechecks the root afterwards. An abort completed by that reentrant
code wins: the outer call neither overwrites its reason nor dispatches again.
All dependents receive the same rooted reason before root callbacks run.

A catchable failure in the root or a dependent's abort steps no longer produces
success with an exception still pending. The first exception, stack and status
are saved with the pinned JSAPI `AutoSaveExceptionState`; eligible independent
dependent steps run without a pending exception, and the first failure is then
restored and returned. A later catchable failure cannot replace it. A native
failure without a pending exception fences subsequent callbacks and is not
masked by an earlier saved catchable exception. Failed algorithm lists are not
cleared or reported as successfully completed.

The finite C++ controls model the last case as a false/no-pending return. They do
not establish C++ unwinding or physical custody after an actual Wasm trap or
Store destruction. Those remain separate qualification obligations.

## Tests and signed programme

Run the maintained source/host controls from the repository root:

```sh
python3 -m unittest tools.tests.test_typescript_event_ownership -v
```

`AbortFailureControls` compiles the actual emitted abort and abort-steps bodies
against bounded JS/vector/broker doubles and the production native-retirement
header. It exercises inline and heap paths, refusal before mutation, allocation
failure, retry, nested fan-out, callback checkpoints, acknowledgement refusal,
repeated reuse, reason identity, first-error/stack preservation, uncatchable
failure fencing and default-constructor reentrancy. These are not SpiderMonkey
or signed-component tests. Historical controls are failure witnesses, not a
substitute for the current emitted implementation.

The existing TypeScript guest qualification workflow builds the source-owned
engine and runs `tools/qualify_typescript_fetch_runtime.py` with these additional
scenarios in the signed Fetch component:

| Scenario | Required observation |
| --- | --- |
| `abort-fanout` | Nine distinct dependents, root-first event order, shared reason and thrown identity. |
| `abort-fanout-refusal` | Exhaust native admission, refuse fan-out without mutation, remove fillers, use an ordinary Promise checkpoint and retry the same root successfully. |
| `abort-fanout-default-reentry` | The selected native factory really reenters, the nested reason wins, and the original constructor is restored. |
| `abort-fanout-fresh` | Repeat ordinary fan-out in a fresh activation. |

The programme keeps the original 64-native-owner ceiling, other budgets,
capability grants, provider restrictions and deadlines. These cases require zero
outbound requests and retain the existing post-invocation cleanup checks. A
missing native-factory reentry is a failure, not a passing skip or a fallback.
The post-invocation broker/pool/I/O counters do not independently measure each
native allocation.

Node is a reference for ordinary fan-out order and reason identity, not the
selected native factory: Node's primordial default-error construction does not
reenter through the overridden `DOMException.prototype.constructor`. Its expected
result for the native-only probe is therefore
`abort-fanout-default-factory-not-reentered`. Simulating finite refusal in Node
checks the probe's assertions, not activation accounting.

## Remaining scope

A successful signed run of these scenarios would qualify only this bounded
slice. Aggregate engine/GC/native/capture accounting, original-owner custody
through Store retirement and quarantine, the remaining unchanged-library
qualification, and approved stream/DNS/socket/TLS mappings are not established
here. The source derivation remains explicitly unqualified; #745's remaining
acceptance criteria must not be checked off on the strength of these controls.
