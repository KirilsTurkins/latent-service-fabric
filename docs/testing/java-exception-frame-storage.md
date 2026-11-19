# Java exception-frame storage

The activation-enabled TeaVM C path uses function-local exception descriptors
according to lexical nesting, rather than allocating a fresh descriptor for
every sequential `TEAVM_TRY` site. This changes storage placement, not Java
exception behavior or the runtime's resource limits. FULL TeaVM optimization,
C `-O2`, the 65,536-byte linear C stack and the 64 MiB memory ceiling remain.
The non-activation compilation path is unchanged.

## Why the lifetime matters

The pinned emitter declares a `TeaVM_LongjmpDesc` inside each try macro. In the
selected Wasm SJLJ lowering, the corresponding storage persists until its
containing function returns. A function with many sequential handlers can
therefore exhaust its linear C stack despite having few simultaneously active
handlers. The diagnosed executor function has 159 try sites but only three
lexical nesting levels. These are observations of that generated programme,
not a permanent test-count or source-size requirement.

`tools/java_guest/enum_guard.py` now prepares the generated C before the existing
single preprocessing, validation and sealed-stdin compilation. Each function
gets a **separate automatic descriptor for each nesting level**. Sibling sites
reuse storage only after their lexical handler ends. Nested handlers never use
a live outer descriptor, and recursive calls have fresh automatic objects.
The descriptors are deliberately not members of one shared aggregate: writing
an inner descriptor must not change the outer automatic object across setjmp.

The original setjmp call sites, catch switches, handler IDs, parent links,
default rethrow and explicit jump-buffer restores on early exits remain.
Nothing is placed in global storage or a new heap/host owner. Suspension and
return still unwind the function's original frame; this is not persistent
continuation storage.

## Source and compiler boundary

The transformation requires the complete unchanged TeaVM 0.15 `exceptions.h`
resource, SHA-256
`024e4fafa0a2cd330911b5d84d1b929f928a88d74730cc265d08cbbb940eb368`.
The exact resource is retained as a test fixture from the pinned TeaVM
classlib C backend, under the existing TeaVM license attribution in `NOTICE`.
The original macros remain byte-for-byte intact; a distinct slot-taking try
macro supplies only the changed storage expression.

Only the selected emitter's closed function and handler grammar is accepted.
Strings and comments cannot affect the nesting map. Unscoped tokens, malformed
try/catch/end sequences, missing or duplicate shadow-stack roots, reserved-name
collisions, repeated adaptation, changed headers and over-bound inputs fail.
The full source inventory and every planned output are checked before writing.
All original enum/date checks and sealed compiler-input checks still run.

The build's `enumGuard.exceptionFrames` receipt records source manifests,
original/adapted header and file identities, and each transformed function's
handler-site and nesting-slot counts. The existing compiler recipe already
binds `enum_guard.py`, so a prepared product from the earlier implementation
cannot silently stand in for the changed compiler inputs.

## Regression controls

Run from the checkout with Python and a native C compiler:

```sh
python3 -m unittest tools.tests.test_java_exception_frames tools.tests.test_java_enum_guard
```

The controls compile the original and adapted pinned exception macros at `-O2`
and compare sequential handlers, nested catches, catch reentry, default
rethrow, recursion, explicit restore/exit edges and fresh function frames.
Collapsing a live inner descriptor onto the outer slot makes the native control
fail. Mutation controls check input shape, pre-write failure and source drift.
These are native C semantic controls, not a substitute for signed Java guests.

## Diagnostic evidence and qualification limits

A local reconstruction used the checksum-verified TeaVM JAR closure, the pinned
private WASI C compiler and unchanged activation fixture. Its baseline crossed
the 65,536-byte stack boundary at a runtime import with 69,104 bytes of observed
stack use. The final separate-descriptor candidate returned the required 42 in
mode 0 and three completed mode-1 diagnostic runs. Mode 1 observed 17,616 bytes
of stack use at runtime imports; its modeled owner table was empty at return.

This reconstruction used local JDK 21 rather than the hosted JDK 25 and a
simplified diagnostic host. Import observations are not a whole-execution peak
stack measurement, and an empty modeled owner table does not prove original
ledger settlement or physical retirement. The candidate core's SHA-256 is
`dbc9e1f8a824902c81998284e61299981ef23359ba30a94d433a8310db000543`;
it is diagnostic evidence, never a production compiler input.

Fresh source-owned compilation and the unchanged signed Java programme must
still pass on the branch. This repair does not waive PR #2161's separate Java
scheduled compiler-model merge hold or qualify all Java/runtime requirements.
