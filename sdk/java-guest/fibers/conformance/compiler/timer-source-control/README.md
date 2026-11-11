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
