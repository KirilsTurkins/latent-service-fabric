# Java resources retained by ordinary timer callbacks

The `examples/java-resource-runtime` fixture qualifies a finite joined path in the existing
`teavm-activation-fibers-io-v1` profile. It uses the existing scheduler port;
the compiler-owned immutable resource stream corrects the locked bulk reads.
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

The programme has eleven joined calls and two missing-runtime denials.
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

The [signed observation](evidence/java-resource-runtime-signed-2026-10-20.json)
records the [successful owning job](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39494267034/job/118875086584)
on feature `2475c56cc6e21c5f407d88a2661473de133ad033`, tested at PR checkout
`34993882cc2741180cc79b8fc8bde404a70f03e2`. All thirteen outcomes are known
and reaped, including the two denials and eleven joined calls. Sixteen physical
samples, thirteen idle samples with all eighteen active provider counters at
zero, both positive native timer pairs and clean node/zero-contact peer shutdown
were verified against all 329 authenticated artifact members and 98 Git-bound
materials. Exactly one fresh joined component and one unsigned compiler-cache
control were compiled; the f919 native products were reused unchanged. The JDK
reference and source controls retain their separate scope.

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
failed; it supplied no successful joined-runtime qualification at that stage.


The retained-component replay at 7b3 reached the first signed parallel call and
failed with a real known/reaped guest trap, 235 charged log bytes and no completed
joined cases. That failed execution is preserved. The host charges the complete
correlated JSON envelope: the original two callback messages need 234+235 bytes,
which cannot both succeed under the unchanged 256-byte activation limit. Several
later long activation IDs also made a single verbose record exceed that limit.

The corrected fixture keeps every original activation ID, grant and limit. Each
ordinary PrintStream write uses one ASCII marker; the longest existing record
is 255 bytes. Only the two callback log checks serialize: the first must succeed,
the second must expose PrintStream's sticky bounded error. Resource readers,
clock/RNG calls, ThreadLocal values and the callback rendezvous stay concurrent.
The parallel result includes `logs=accepted:sticky-error`; later fresh Stores
must again accept their ordinary write. This is an error-policy assertion, not a
log-delivery or asynchronous-flush claim.

The [bounded JDK reference](evidence/java-resource-runtime-budget-reference-2026-10-20.json)
uses an explicitly controlled host-only correlated-byte sink: original source
is RED, corrected parallel/fresh/clear/caught-callback modes are GREEN. It records
Windows CRLF separately from the Linux guest LF envelope. That reference sink
is never compiled into the component and does not qualify guest execution.
The source change requires one fresh joined guest compilation through the
original maintained 30-minute lane; its result was pending at that stage.


The fresh corrected guest compiled successfully on PR checkout 7c50 (feature 4980),
then still trapped on the first parallel call with 219 charged bytes. This is a
second real failure; the host reference is not promoted to component evidence.
The retained 209-member artifact binds that new guest and its original compiler
receipts. The explicit manual diagnostic reuses it without compilation and
observes only fresh, clear and parallel under the same grants and caps. Exact
success values and real traps remain separate raw observations; every call must
still be known/reaped and physically retired. Its `diagnostic.json` explicitly
sets `originalProgrammePassed:false` and cannot qualify the normal 13 programme.

The [retained diagnostic observation and direct stream controls](evidence/java-resource-stream-bulk-read-reference-2026-10-20.json)
record three real traps: fresh and clear before any log bytes, and parallel after
219 bytes. The diagnostic job succeeded in retaining those observations; it did
not pass the joined programme. The exact TeaVM 0.15.0 class-library JAR exposes
the cause: `readAllBytes()` and `readNBytes(int)` copy bytes without advancing
the stream position. The unchanged outside library correctly requires EOF after
reading the remainder.

Generated resources now return a compiler-owned `ByteArrayInputStream` subclass.
Only its two bulk-read methods change: copy before advancing, reject negative
lengths without mutation, and bound the count before addition. `readAllBytes`
retains the standard JDK method's synchronization. The locked class-library JAR,
all inherited methods, fresh per-open arrays, application source, EOF assertion,
authority and budgets remain unchanged. The ordinary SDK snapshot and resource
profile bind the exact helper source. Direct controls execute against the real
pinned TeaVM superclass: five old cases are RED, all eight corrected cases are
GREEN. They include subsequent reads, bounded/maximum/zero/negative lengths,
empty streams, mark/reset, close and independent readers. These host controls
were reference-only until the later signed guest result below.

The corrected e977 guest passed parallel and foreign-fresh on the original f919
host, then failed clear before logging in both the fresh063 run and the public
69d retained-component replay. A bounded private observation host returned exact
fresh/clear/parallel values without observing any trap; its trap-required outer
job remains failed. The three private successes do not qualify the public host
or prove the short clear sleep actually suspended.

The joined fixture now declares its ordinary greeting export as `async func`,
matching the maintained fiber conformance world's entry contract. It preserves
the service name, Java/C ABI, original library code, all13 cases/order, grants
and budgets. The successful public-host component is 1,954,666 bytes, digest
`sha256:5b80c6679f9f9ebeeede6f6ef28c3d4acd685005a79b9041e87ffcb1720862de`.
Compared with the reproducibly failing e977 component, its entire byte sequence
changes only three function-type bytes, from `0x40` to `0x43` at offsets
`0x1dc510`, `0x1dc594` and `0x1dc5be`. Java/C/header binding outputs, backend
receipts and both original JAR identities are identical. The unchanged public
13-case programme now passes, establishing the bounded contract counterfactual.
No particular old trap variant was observed. Cancellation/deadline have positive
pending evidence; the short clear sleep itself is not claimed to have suspended.

The separate [accepted late-facility programme](java-dotnet-late-facilities.md)
keeps the original joined programme intact and tests callback completion after
an ordinary cancellation/disposal request. Its new signed execution is pending.
