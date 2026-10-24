# TypeScript import borrow release: source foundation

This #745 foundation adds a compiler-private, opt-in acknowledgement for one
original asynchronous canonical import. Its native implementation and signed
Component Model behavior are **not yet qualified**. The compiler-owned
selection is empty, so ordinary generated bindings remain byte-identical and
applications cannot enable the mechanism through project configuration.

## Three separate events

1. The original JavaScript result Promise rejects immediately when the existing
   cancellation path requests cancellation. This timing is unchanged.
2. The optional `borrowReleased` Promise resolves only after any created
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
module. The selected wrapper/public API exposes no numeric record id or new
authority to application code. The existing internal bridge still receives
compiler-lexical numeric ids.
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

Eleven real-SpiderMonkey native controls are staged in
`sdk/typescript-guest/activation/tests/native_imports.cpp`: blocked cancellation
through actual fixture subtask drop, foreign/unregistered/released foreign-epoch
handles, Native admission denial, observer Promise admission failure, bounded-list
refusal, five exact owner-acknowledgement refusals, and the existing cancellation
baseline. They have not been compiled or executed for this foundation. Their canonical
intrinsics are explicit diagnostic doubles, rather than signed host evidence.

The original owning campaign at commit
`e2dfcf6d1b48b650fee585e83cd15720bf7f745c`, run `40042939576`, built the
normal Promise library and import engine successfully. Its diagnostic C++
compile/link command exceeded its 120-second deadline. **The campaign failed;
no native case ran.** Its original failed receipt and completed compiler-input
receipts remain unchanged. A completed source input has unknown runtime
qualification.

The replacement owning recipe in `tools/qualify_typescript_borrow_release.py`
requires the fixed authenticated producer artifact, all 41 byte-identical engine
inputs, and the unchanged normal engine/splicer/source validators. It refuses
source mismatch rather than rebuilding or rewriting old receipts. Only the
normal pinned WASI SDK 30 toolchain is acquired for the diagnostic retry. The
normal library and engine are never rebuilt by this recipe.

The first bounded retry, run `40047503071`, compiled the diagnostic in1.8s
but failed its link because the standalone recipe omitted the maintained Rust
encoding/hook and WASI support closure. It ran no native case. The support-link
repair adds only the pinned Starling four-crate staticlib template with its
original Cargo.lock (`--locked`, Rust1.97.1, wasm32-wasip1), unchanged panic/oom
wrapper source, and normal WASI signal/process-clock/getpid archives. Its
separate support-build deadline is300s; the producer's normal staticlib build
took15.56s. Source, lock, compiler, libraries and wrapper identities are retained
and rechecked. No substitute symbols or engine/libJS rebuild is permitted.

Run `40049437805` built that support successfully and compiled, linked and
validated the diagnostic. It then failed the64-MiB carrier bound:139,270,923 of
148,560,386 bytes were DWARF debug sections. Artifact `12542384282` retains the
failed raw carrier. The next diagnostic link adds `--strip-debug`; executable
sections, the64-MiB/120-second bounds and all eleven cases remain unchanged.
No native case has run in that failed campaign.

Diagnostic compilation uses `-O0`; the diagnostic link explicitly disables
ThinLTO optimization. Their separate phase receipts share **one aggregate
120-second deadline**, preserving the same finite bound and all eleven cases,
ABI, admission, ownership and drop assertions. Pinned Node's `node:wasi`
executes the diagnostic with no preopened directories. These fixture intrinsics
are not signed canonical behavior. All six pinned-parser controls must pass
without skips before diagnostic compilation. Actual wasm32 manager, record and
observer sizes remain unknown until that retry succeeds; no whole-cost claim
follows from those measurements.

A separately reviewed signed TypeScript campaign must hold a real canonical borrow
at a controlled cancellation barrier, prove release remains pending while the
logical result rejects and a sibling progresses, then observe actual drop before
consuming close. Root trap/deadline cases must retain or quarantine outstanding
physical owners; fresh success follows measured cleanup. At borrow acknowledgement
the same real connection/socket owner must remain live until consuming close;
actual read `IoCall`/`IoTransfer` counts are recorded, including genuine earlier
retirement, rather than assuming an extra held transfer. LogicalReference
development evidence must remain distinct from production provider qualification.

No Node socket module, production enablement, complete #745 acceptance criterion,
or full ticket completion is claimed by this source foundation.
