# Java resources retained by ordinary timer callbacks

The new `examples/java-resource-runtime` fixture is a candidate for the existing
`teavm-activation-fibers-io-v1` profile. It adds no compiler or scheduler port.
An application calls an outside parent JAR, which depends on a second resource
JAR. The normal add-local, resolve, exact review and CAS path captures both JARs
and their UTF-8/NUL, binary and empty data before the originals are removed.

Ordinary `Timer`/`TimerTask` callbacks retain independent standard classpath
streams. One callback must wait on a monitor until its sibling enters; root and
callback `ThreadLocal` values remain distinct. The callbacks read standard
clocks, draw eight bytes through `SecureRandom`, and use `PrintStream` logging.
The secure API requires the existing `RANDOM.bytes` operation, not the unrelated
scalar `u64-value` operation. Each standard facility still requires an explicit
declaration and operator grant. This fixture supplies no SDK executor, logger,
entropy callback or manual task pump.

The [ordinary JDK reference observation](evidence/java-resource-runtime-reference-2026-10-20.json)
records three successful modes: two callbacks with retained streams, fresh
resource state, and timer cancellation followed by a valid read. A separate
normal local-JAR capture observed the actual nested TimerTask class files,
exact parent/child edge and resource bytes, then removed the original inputs.
The five focused source controls reject changed original source, foreign or
missing classes, unbounded generated class sets and implicit budget changes.
These are JDK/capture and source checks, not an emitted TeaVM component or
signed/admitted runtime qualification. That owning programme remains pending.

No native-thread support, complete Java scheduler acceptance, asynchronous
console-flush delivery, late-callback proof or complete #681/#741 qualification
is claimed. The ordinary Java SDK and existing signed programmes remain intact.
