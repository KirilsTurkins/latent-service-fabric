# Timer and owner admission source controls

These fixtures compile the actual `Activation` and `Monitors` source against a
private, fault-injecting `Bindings` ledger. They are not generated guest bindings
and must not be included in a component recipe.

`timer_sleep_admission_source_control` in `tools/qualify_java_fibers.py` compiles
the fixtures with Java 25 and the verified, locked TeaVM model classpath. It runs
`TimerSleepAdmissionSourceControl`, then a fresh JVM for each
`OwnerAdmissionSourceControl` mode: `normal`, `refused`, `lost`, `null`, `reentry`,
and `capacity`. An incomplete or unexpected result, failed process, or changed
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

`tools/tests/test_java_owner_admission.py` separately tests the Python command
orchestration and receipt validation using mocked compiler results. Those tests
provide no Java execution credit. Neither these fixtures nor a host-JDK source
run establish signed component execution, real Wasm trap catchability, host
physical retirement, or completion of the Java standard concurrency profile.
