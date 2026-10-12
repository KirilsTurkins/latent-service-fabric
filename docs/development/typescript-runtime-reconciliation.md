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
`0cfe249e402e11af02b29abcc0631269e27a3188ef90c1590c845d9e83a669fa`;
its exact engine input envelope SHA-256 is
`2998903d9ca2541f76fb602c22c6d563f180c5c87ec4d4d4e188d18be00a7475`.

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

The focused Linux source suite passes 175 tests with zero skips. The packaging
library passes 80 tests. The signed ordinary campaign passes its complete original
matrix and fresh-after-failure control. CI adds the new regressions while retaining
all historical commands, cases, ignore guards, limits and qualification contracts.

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
separate requirements of #745. Default global fetch, body ownership and unchanged
default-fetch consumers remain #691. Complete private/local/offline/update/watch
native npm workflow acceptance remains #685. Historical source/Wizer/broker-only
controls retain their original qualification boundaries.
