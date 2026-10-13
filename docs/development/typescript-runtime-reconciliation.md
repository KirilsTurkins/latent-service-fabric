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
`ec7f1a8f6f599ec5283357ebd79e90d833d88291570e10c1a3a353557c6d33d0`;
its exact engine input envelope SHA-256 is
`4b581e005948db7dc99f2cedc0e3cb08307c446c93f1f4aac0f882e31cbb81ad`.

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
import fixture also passes both original cases, with actual child admission and
invocation, original sibling progress assertions and complete physical cleanup.

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
range. The exact source-owned compiler rebuild and upstream component-new/transpile
recipe complete within the original bounds. Its WASI core SHA-256 is
`ea1e45684324106a3df4ef813ba5c70cfba73ee09e756c129ba4e5fd89e6f275`;
the source-splicer input envelope SHA-256 is
`c4cb8e9e425f365dfd596ff6bb6d537389514adee1140ab56041451f6e453467`.

The complete original 26-case signed matrix now passes on the current production
engine, rebuilt splicer and merged delivery chain: ordinary 15, clock four,
service two and unchanged npm five, plus the extra fresh-after-failure control.
All four required ordinary failure cases still fail with the expected guest trap.
Both service cases execute one actual child. No diagnostic exception reporter,
host instrumentation or application-body modification participates in these runs.
An [identity packet](typescript-runtime-reconciliation/2026-10-12-production.json)
records exact inputs, evidence digests and remaining acceptance boundaries.

Local evidence is retained under the isolated worktree's `target/pr923`, including
all earlier failed builds, the pending-Promise diagnostic, forbidden post-return
import, strict host lifecycle failure and the original Abort failure. Diagnostic
components are separate from the production evidence. The successful production
campaign is `signed-production-r18.log`, with separate clock/service/npm logs;
source-bound engine build and exact reused link inputs are in
`import-production-engine-build.json`. Source-built link inputs are preserved
independently from these tests.

The input classification remains `qualification: unknown`,
`apiSupport: not-evaluated`, `inputTrust: operator-asserted`. These bounded signed
controls do not establish the entire standard runtime or clean installed toolkit
qualification. Broader exhaustion/cancellation/late-wake acceptance, automatic
runtime selection and packaged distribution remain separate requirements of #745.
The controls above cover their bounded original fixtures. Default global fetch,
body ownership and unchanged
default-fetch consumers remain #691. Complete private/local/offline/update/watch
native npm workflow acceptance remains #685. Historical source/Wizer/broker-only
controls retain their original qualification boundaries.
