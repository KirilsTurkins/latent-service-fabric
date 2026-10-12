# TypeScript runtime snapshot reconciliation

PR #923 retains the useful runtime, source derivation, async import and compiler
material changes from snapshots #916 and #919 while reconciling current
development. The associated requirements are #745, #691 and #685. This milestone
does not close any of those tickets.

## Verified runtime milestone

The unchanged `ordinary15` application now executes through real package signing,
ordinary node admission and the installed activation, clock and physical cleanup
owners. Its original 15 cases cover pending exported Promises, macro/microtask
ordering, thenables and rejection identity, timeout cancellation, recurring timers,
AbortSignal timeout/any/reason behavior, accepted work after root settlement,
rejected exports, callback failures, unhandled rejection, opaque pending user work,
fresh state and captured callback arguments. A further fresh activation succeeds
after the failure cases. Every case checks actual node/Store/broker cleanup.

The qualification application bodies, tenant/service identities, runtime owner
ceilings and declared invocation limits remain unchanged. The source-built engine
used one CPU, 2 GiB memory and the original finite compiler deadline. The current
engine SHA-256 is
`6655200c457ac1b75763ba6fa661271379cbb7a4e6bcb49e0cebc7bc425f9692`;
its exact engine input envelope SHA-256 is
`bf4d9d65cebbc1375f18f50537687475b15ad8bf96e2e0ec9c4a09e02fe6e783`.

The ordinary, clock and service caller/callee components have genuine maintained
CLI builds, exact selected WIT sources, packages and build observations. Their
public application contracts remain in the original tenant namespace. Foreign
world includes retain their declared names and separate captured package sources.
Nonblocking async subtask cancellation is admitted narrowly; the other previously
unsupported additional async builtins remain rejected by package preflight.

## Lifecycle corrections

The pinned generator eagerly retained an unused pending sync-import waiter and
completed task/exit Promise graphs. The selected runtime adapter creates a waiter
only for an actual import wait and removes completed task references on genuine
exit. Behavioral regressions preserve shared waiting and queued execution order.
The ordinary synchronous compiler path keeps its generated bindings unchanged.

Canonical post-return cannot import broker settlement. The embedding instead
releases its actual temporary JS roots after result lowering and repeats the
strict drain while the ordinary call can still acknowledge physical retirement.
Post-return observes GC without host imports. Native reservations remain charged
until their actual retirement. The host's finalization and native owner checks
remain unchanged; neither root settlement nor Store destruction proves completion
of accepted work.

The pinned AbortSignal implementation now returns a native failure when throwing
the original abort reason and converts the single `any` iterable before allocating
the dependent signal. These follow the
[DOM abort algorithms](https://dom.spec.whatwg.org/#interface-abortsignal).

## Evidence and remaining acceptance

The focused Linux source suite passes 177 tests with zero skips. The packaging
library passes 80 tests. The signed ordinary campaign passes its complete original
matrix and fresh-after-failure control. CI adds the new regressions while retaining
all historical commands, cases, ignore guards, limits and qualification contracts.

The unchanged four-case clock application also passes signed node execution:
actual wall/monotonic progress, stable activation time origin, default/explicit
Date constructor behavior and AbortSignal timeout. The two-case actual service
import fixture is retained as a separate explicit prepared-component test; its
first run exposed a guest failure before child admission and is not qualified.

The native-lock npm application also has a fresh maintained resolve/review,
offline dependency verification and compiler/package build. Its original direct
pins are `p-queue@9.0.0`, `p-timeout@7.0.1`, `delay@6.0.0` and
`eventemitter3@5.0.1`; neither the application bodies nor the original limits were
changed. A separate explicit signed fixture retains its five cases. The first
production attempt failed at the original native owner ceiling before the heap
collector ran.

The collection milestone collects actual unreachable objects before bounded
native admission reaches the heap collector's later trigger. Its local live-owner
count changes only after successful native registration or settlement and controls
collection timing, never permission or admission. Broker settlement follows the
real weak sweep and collection end, outside GC. Twelve intrinsic engine controls
pass, including all historical cases, 64 retained reachable Promises refusing the
next allocation, and churn retaining its charges until physical collection and
acknowledgement. Their fixture broker is explicitly not signed qualification.
The unchanged five-case npm application now passes signed production execution.
The original ordinary matrix, fresh-after-failure and four clock cases also pass
again on this exact production engine. Production host test binaries and packaging
tools are copied to owned immutable paths before use. Earlier diagnostic runs keep
their separate qualification boundary.

The service diagnostics exposed the original Promise realm mismatch and a native
binding selection failure. The selected import compiler captures the application
Promise intrinsic and normalizes actual async functions and resource methods at
module registration. A two-realm regression preserves pending ordering, rejection
identity, receivers, constructors, name/arity and ordinary function references.
Missing native import records now report explicit errors while preserving an
already pending exception; 27 actual import/timer/snapshot controls pass.

The original splicer guessed native pointers within 1000..5000. This engine's
sample pointer is 532, so that guess selected instruction zero and modified stack
arithmetic while retaining the sample binding. The source-owned splicer now
locates the actual sample function in its table and selects the corresponding
getter operand. Missing and ambiguous shapes are rejected. Eight native compiler
tests pass, including existing ABI layouts and pointers below and above the old
range. The updated compiler tool rebuild and signed service acceptance remain in
progress; source controls do not qualify that import implementation.

Local evidence is retained under the isolated worktree's `target/pr923`, including
all earlier failed builds, the pending-Promise diagnostic, forbidden post-return
import, strict host lifecycle failure and the original Abort failure. Diagnostic
components are separate from the production evidence. The successful production
campaign is `signed-production-r13.log`; source-bound engine build and exact reused
link inputs are in `abort-engine-build.json`. Source-built link inputs are preserved
independently from these tests.

The input classification remains `qualification: unknown`,
`apiSupport: not-evaluated`, `inputTrust: operator-asserted`. These bounded signed
controls do not establish the entire standard runtime or clean installed toolkit
qualification. Clock/service/npm runtime controls, exhaustion/cancellation/late
wake acceptance, automatic runtime selection and packaged distribution remain
separate requirements of #745. The clock controls above cover their bounded
original fixture only. Default global fetch, body ownership and unchanged
default-fetch consumers remain #691. Complete private/local/offline/update/watch
native npm workflow acceptance remains #685. Historical source/Wizer/broker-only
controls retain their original qualification boundaries.
