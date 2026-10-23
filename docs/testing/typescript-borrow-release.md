# TypeScript import borrow release: source foundation

This #745 foundation adds a compiler-private, opt-in acknowledgement for one
original asynchronous canonical import. Its native implementation and signed
Component Model behavior are **not yet qualified**. The compiler-owned
selection is empty, so ordinary generated bindings remain byte-identical and
applications cannot enable the mechanism through project configuration.

## Three separate events

1. The original JavaScript result Promise rejects immediately when the existing
   cancellation path requests cancellation. This timing is unchanged.
2. The optional `borrowReleased` Promise resolves only after the original
   canonical subtask becomes terminal and drops, original work accounting
   completes, the import record/captures/buffers are destroyed, and the original
   and observer retirement acknowledgements succeed. A blocked cancellation
   keeps this second Promise pending. A failed acknowledgement quarantines the
   remaining paid ownership and cannot provide a release proof.
3. Underlying provider `IoCall`, `IoTransfer`, connection and physical socket
   retirement remain independent. Borrow release never certifies these events.
   A future stream adapter must wait for borrow release before consuming close
   and must still observe the provider's actual retirement rules.

The private wrapper receives an opaque native handle for the exact reserved
record, owner token, root generation, manager and context. It exposes separate
logical-result, cancellation and release operations to a selected compiler-owned
module. No numeric record id or new authority is exposed to application code.
Repeated calls reuse the original observer; foreign, stale and malformed
identities refuse. Released handles still check the current admitted root epoch.

## Admission and source boundaries

The original import `Record` layout and `cancel(id)` implementation are unchanged.
An optional intrusive lookup node receives a Native owner under the original
budget before its allocation, persistent root registration or observer Promise
creation. Existing intrinsic Promise hooks separately preadmit the managed
Promise; the managed handle remains under the original JavaScript heap cap.
Lookup traversal is bounded by the admitted-node count. There is no new quota.

Original completion failures retain the paid node in quarantine. On successful
completion, the node and persistent root are destroyed before refunding their
Native owner. A refusal of that final refund retains the owner in the existing
scalar failure holder and cannot resolve the observer. The manager adds a fixed
pointer, size counter and failure flag even when unused; the actual ABI size
delta and total runtime cost have not been measured. This is not whole-cost
acceptance evidence.

The AST transform accepts only selected generated async declarations with the
reviewed reservation, carrier and finally graph. Arming occurs first inside the
original try block, so observer admission refusal still executes the original
finally. The bridge must be the actual unique top-level const declaration.
Changed or ambiguous shapes fail closed. The native header is part of the
engine source identity; the JS helper is part of compiler staging and the build
recipe. Existing engine products cannot stand in for a fresh source-bound engine.

## Current controls and remaining owning evidence

Run the six host-only controls with:

```powershell
python -m unittest tools.tests.test_typescript_import_cancellation -v
```

These controls cover default bytes, captured generated structure, cancellation
versus delayed release, denied observer admission, nested handoffs, malformed
shapes and recipe membership. They may use Node's bundled Acorn solely as a
host-side test mechanism when the owned compiler parser is unavailable. The
production compiler has no such fallback. Pinned-parser execution remains
required for owning qualification.

Three real-SpiderMonkey native controls are staged in
`sdk/typescript-guest/activation/tests/native_imports.cpp`: blocked cancellation
through actual fixture subtask drop, foreign/unregistered/released foreign-epoch
handles, and Native admission denial before the optional node and Promise.
They have not been compiled or executed for this foundation. Their canonical
intrinsics are explicit diagnostic doubles, rather than signed host evidence.

Before qualification, the owning hosted recipe must compile the selected native
engine, run the native controls plus owner-acknowledgement refusal/drop-order
controls, measure actual ABI sizes, and run the pinned-parser controls. A
separately reviewed signed TypeScript campaign must hold a real canonical borrow
at a controlled cancellation barrier, prove release remains pending while the
logical result rejects and a sibling progresses, then observe actual drop before
consuming close. Root trap/deadline cases must retain or quarantine outstanding
physical owners; fresh success follows measured cleanup. LogicalReference
development evidence must remain distinct from production provider qualification.

No Node socket module, production enablement, complete #745 acceptance criterion,
or full ticket completion is claimed by this source foundation.
