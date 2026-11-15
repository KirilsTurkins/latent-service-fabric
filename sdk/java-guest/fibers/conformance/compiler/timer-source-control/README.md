# Timer and owner lifecycle source controls

These fixtures compile the actual `Activation` and `Monitors` source against a
private, fault-injecting `Bindings` ledger. They are not generated guest bindings
and must not be included in a component recipe.

`timer_sleep_admission_source_control` in `tools/qualify_java_fibers.py` compiles
the fixtures with Java 25 and the verified, locked TeaVM model classpath. It runs
`TimerSleepAdmissionSourceControl`, then a fresh JVM for each
`OwnerAdmissionSourceControl` mode: `normal`, `refused`, `lost`, `null`, `reentry`,
and `capacity`. It also runs each `OwnerSettlementSourceControl` case in a
fresh JVM. An incomplete or unexpected result, failed process, or changed
source input prevents a successful source-control receipt.

The owner controls check both sides of admission. Normal admission and definite
typed refusal followed by retry remain usable. Lost acknowledgement, a missing
token, in-flight finalization, and counter overflow fence subsequent admission
and successful completion. A prepared managed worker, pool registration, and a
cached default executor must not bypass that fence merely because they can
avoid another call to host `register`. Rejected starts leave the prepared bit
and original token intact; exceptional teardown retains the worker, root,
pools, and cached executor rather than discarding uncertain custody.

The fixture constructs prepared-worker state with reflection and invokes the
maintained start hook directly. It does not start a JVM worker and does not
claim to execute a TeaVM continuation. The normal/refusal modes also verify that
healthy prepared starts consume preparation without registering a second owner,
settle their existing owners, and permit clean teardown.

Generic `Lease.close()` keeps its original token in an intrusive in-flight
registry until both host acknowledgement and local cleanup have completed.
`OwnerSettlementSourceControl` exercises Wait, Result, QueuedWork, and Executor
owners, typed refusal/retry, failures before and after host removal (including
an `Error`), missing replies, duplicate closes, and teardown on either side of
the host mutation. It also covers nested and out-of-order acknowledgements,
capacity refusal before dispatch, and try-with-resources preserving the primary
exception while retaining an uncertain wait lease. JVM latches arrange the
out-of-order host returns; they do not represent native parallel guest fibers.

A definite acknowledgement may finish cleanup after teardown has fenced the
Store, but cannot make that Store healthy again. A healthy typed refusal leaves
the token retryable; a lost acknowledgement never permits another host attempt.
Failure retention is idempotent even when both `Lease.close()` and its caller
report the same owner: the preallocated retention guard prevents cycles or
lost list entries without allocating on the failure path. No host limit or
application memory grant is expanded.

`tools/tests/test_java_owner_admission.py` separately tests the Python command
orchestration and receipt validation using mocked compiler results. Those tests
provide no Java execution credit. Neither these fixtures nor a host-JDK source
run establish signed component execution, real Wasm trap catchability, host
physical retirement, or completion of the Java standard concurrency profile.

## Work retirement

`WorkFinishSourceControl` exercises the actual worker/root settlement helper
against the same private ledger. Each task, managed worker and root mode runs in
a fresh JVM. Teardown during a host call, after host mutation, or during local
pool cleanup must refuse completion and retain the original Work records.
Lost acknowledgements, missing replies, duplicate/reentrant completion and
cleanup exceptions cannot enable another host settlement attempt. Definite
refusals retain the token and permit retry while the invocation remains healthy.
Nested and ordered out-of-order returns check independent intrusive-list entries;
capacity and teardown admission controls prove rejection before host dispatch.

The managed fixture consumes the real preparation hook without scheduling a JVM
worker. Root controls call the production settlement helper with reflected entry
state; they do not execute the native dispatch/Fiber pump. The out-of-order
control uses bounded JVM latches solely to arrange sequential host-return
interleavings, not to claim simultaneous guest execution. All new list links and
counters live in Work custody allocated before owner registration; the production
IR control checks claim/release helpers for calls, monitor operations and loops
before and after checkpoint insertion.

The legacy readiness fixture also checks that poisoned leases and workers
cannot be cleaned through production APIs after teardown. Its between-case
reset removes only private ledger entries; it is not a guest cleanup path.

These controls do not establish guest component execution, real trap
catchability, physical retirement, or closure of #741. They do not change runtime
grants, capacity budgets, or the production Java 25 toolchain requirement.
