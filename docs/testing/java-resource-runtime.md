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
records four successful modes: two callbacks with retained streams, fresh
resource state, timer cancellation followed by a valid read, and an exact caught
callback error followed by a fresh resource read. A separate
normal local-JAR capture observed the actual nested TimerTask class files,
exact parent/child edge and resource bytes, then removed the original inputs.
The five focused source controls reject changed original source, foreign or
missing classes, unbounded generated class sets and implicit budget changes.
The new 30-minute owning job authenticates the separately compiled f919 native
observer products, installs the existing pinned Java compiler tooling and
compiles one fresh offline `teavm-activation-fibers-io-v1` component. It performs
normal neutral-resource signing/admission for two tenants with explicit
CLOCK/WALL/RANDOM/LOG/ACTIVATION authority. It does not rebuild the native host,
engine or five-template SDK baseline. The maintained compiler-cache acquisition
may also emit one unsigned default greeting control; its count and cache mode
are recorded separately from the one joined component.

The pending programme has eleven joined calls and two missing-runtime denials.
It includes overlapping callbacks, clear, a root trap, caught callback error,
accepted-root timer cancellation/deadline and fresh same/foreign-tenant reads.
An uncaught ordinary TimerTask exception is not asserted to trap the root;
the caught case checks the exact exception class and resource recovery.
Before cancellation/deadline, a fresh fixed native record must prove either
accepted timer-to-`begin_wait`, or the original `wait-for` future returning
`Poll::Pending`. All five physical guest owners and current provider charges
remain mandatory. Audit loss/refusal is never positive barrier evidence.
Original 8-task/2-executor/8-queue/16-wait/8-timer/8-result/8-native-owner limits,
64 MiB memory, one-billion fuel and 256 log-byte budget remain unchanged.

The JDK/capture/source checks are not emitted-component or signed/admitted
qualification. The owning programme is newly queued only after publication;
no successful Java joined-runtime receipt is currently claimed.

No native-thread support, complete Java scheduler acceptance, asynchronous
console-flush delivery, late-callback proof or complete #681/#741 qualification
is claimed. The ordinary Java SDK and existing signed programmes remain intact.


The first owning c277 job genuinely completed the fresh normal FIO component
(`1569a4ce8a15e61601b458f11dd1c332085f28db1f85954b9a000a6044946d8f`,
1,898,554 bytes; 42.2451 seconds), then failed before node execution because the
reader requested a private coroutine workspace file. The maintained builder
publishes `coroutine-compiler-preparation.json`; the corrected reader verifies
that public receipt and never invents the absent private file.

The opt-in retained-component replay authenticates the exact failed job/artifact
and all 105 immutable public member preimages. It restores only eight original
raw WIT/resource files from their authenticated package layers, leaving every
original marker/observation byte unchanged. All 98 original Git materials are
checked; only the current receipt reader and workflow can differ. Current
helper/fixture/native identities are rechecked after fresh normal signing and
the unchanged 13-outcome node programme. No Java compiler, JDK, NativeAOT, host
or engine build runs in this 20-minute replay. The earlier owning failure stays
failed; no successful joined runtime outcome is claimed until that replay passes.
