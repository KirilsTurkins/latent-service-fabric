# Retained cleanup constructor waits

This unselected source layer follows the measured [cleanup lifecycle source](kernel-cleanup-lifecycle-source.md).
It adds a paid birth completion and one expiry to the existing Control record.
The full begin API accepts the caller's finite remaining jiffies budget, fixes
that expiry before reservation and birth, and returns `-EINPROGRESS` while the
original ordered queue is still parking. The separate readiness wait can only
narrow that expiry. A zero or expired budget cannot turn an already completed
completion into permission to proceed.

The provider Task creator keeps the original pending-slot and `create.done`
exchange. Its completion is inside paid Control storage. If timeout or a signal
wins the completion pointer, the existing actual Task/child drain remains
responsible for retirement. If the real creator or child already claimed the
pointer, the constructor retains the complete graph in quarantine before the
opener borrow is dropped. A late completion or sleeping Task never refers to a
dead stack completion, and the timeout provides no refund proof.

Queue preparation releases the actual ACPI lifetime mutex before returning
pending. Its real registration borrow retains Control and queue lifetime.
The park callback acquires that same mutex across the original two RCU stages.
Termination checks the authenticated phase under that mutex, then waits on a
provider static waitqueue with the mutex released. Its condition reacquires the
same mutex before reading registration; no candidate pointer survives the
unlocked wait. A failed unlinked PWQ keeps registration until its actual release
callback and the separately paid same-worker barrier complete. Unknown topology
retains the lifetime rather than certifying readiness. All ordinary producers
and all three original queue-destruction calls remain.

The original factory open publishes `opened` and its real mm/tgid/credential/net
borrows before releasing `factory_lock` around its existing constructor call.
A second open observes `opened` and cannot enter or recycle the pending bank.
Failure keeps that owner state until actual retirement.

These APIs are source helpers. The existing factory still calls the earlier
deliberately refusing constructor. No file descriptor selects the full begin or
readiness helper. Returning pending through the existing open error branch would
close construction and is not a supported integration. Actual public IoCall and
provider readiness wiring remains required.

The focused programme compiles only the changed factory, kthreadd, workqueue and
ACPI OSL defining objects, measures the actual enlarged Control and new provider
waitqueue, and retains their source/configuration identities. Its eight source
controls do not execute Linux constructor races or physical retirement. The
earlier 24-object/native atomic programme is unchanged and is not rerun.

Synchronous mutex acquisition, allocation/constructor execution and the complete
wall-clock birth bound remain unqualified. Initial completion storage ownership
does not establish that bound. Actual positive, timeout/signal/late-completer,
second-open, termination and physical final-free programmes remain necessary
before selection. Full consumer, accounting, whole allocation closure and
production installation gates remain false. Original caps are unchanged.
