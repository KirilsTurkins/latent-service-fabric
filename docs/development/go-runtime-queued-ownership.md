# Ordinary Go queued-root ownership

This finite programme extends the signed Go admission evidence for #736 and
#742 to the original node admission-eight and queue-eight policy. It uses the
unchanged maintained Go v5 managed-idle fixture, scoped signed publications for
two tenants, one manager/backend and one physical cell. No production runtime,
scheduler, compiler, grants, Task16/Wait4 limits or aggregate CPU/memory ceiling
changes are selected.

Each tenant takes a turn holding the original real Store at an observed pending
runtime wait. Seven peer roots are polled into the actual scheduler queue; all
eight original CPU and memory grants remain charged while only one Store is
created. A ninth root must receive exact node/concurrency ResourceExhausted
advice, with no queue extension or automatic retry. A foreign cancellation must
remain NotFound and leave every original reservation intact.

Cancelling one owned queued root must return only its reservation without
creating a Store. One explicit replacement restores saturation. A different
queued root carries a narrower absolute ingress deadline, which must expire
while the original Store remains held; queue waiting cannot restart that
deadline. A second explicit replacement again restores the same original
ceiling. These are new requests, not retries hidden by the manager.

After cancellation or the ordinary Go panic actually retires the original
Store, all seven accepted peer roots must remain charged and then execute with
fresh initialized Go state. The target observes physical Store, host-state,
component-instance and invocation retirement between successors. Final calls
from both tenants must succeed after all ownership returns to idle.

The strict qualifier requires exactly 34 ordered observations: 20 actual guest
executions, four queued cancellation/deadline outcomes before Store creation,
two admission refusals, two foreign-cancellation controls and six pending queue
barriers. It authenticates exact managed source/compiler/component identities,
the real ignored libtest target and before/after source snapshots. Wrapper
success, incomplete or reordered rows, wrong tenants, private fields, ignored
execution or a different target cannot qualify this programme.

Hosted execution is pending. This programme does not establish full scheduler
fairness, every late-wake/race/cost scenario or low-level network/DNS/TLS
accounting. The synthetic auxiliary callee remains separately attributed to its
handwritten constructor and is never invoked or described as compiled Go.
