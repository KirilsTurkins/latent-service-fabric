# Native close request and charged observation

The [actual close-request observation](../testing/evidence/kernel-native-close-request-2026-10-24.json)
for #738 passed at source `976e86c71a7dc57e9d9e3c47258e05370d599bf0`,
[run 40122724709](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40122724709).
Thirteen native owner controls, five charged-result controls, six Python controls,
twelve actual compiled C parser controls and one fresh isolated VM passed. The
earlier [native/kernel join](kernel-native-constructor-vm.md) actually reached
constructor-bootstrap READY using BEGIN and optional WAIT, then closed its file
and observed kernel physical return while retaining native capacity. It did not
send the explicit CLOSE request from Rust. The separate historical #1398 third
boot exercised open without BEGIN. None enables a production stream provider.

The native owner now preserves a private immutable expiry only after successful
actual bootstrap READY. Retirement submits the existing version-2 CLOSE operation
on the same protected file, with the same expiry, followed by one exact status
read. The original kernel actor checks bind mm, thread-group identity, current
credentials, file credentials and network namespace; they do not require the
same worker TID. No worker affinity, credential or namespace relaxation is added.
The new actual VM established that the selected worker received the authentic
CLOSED reply with the original expiry. Earlier final-file-close success alone
could not establish this.

CLOSED means close-request acceptance. It does not certify completed children,
Root physical return, native quota release or application transaction rollback.
Wrong expiry, reserved/error fields, unknown phase, short transfer or I/O failure
produces an uncertain observation with no retry or reconnect. Failed/uncertain
constructor attempts retain their original guards and do not receive a successful
READY stamp. Every outcome closes the facade only on the existing admitted
blocking table and retains the original connection/backing in quarantine.

The result has a fixed three-state observation and a non-cloneable receipt. The
same original cleanup work and metadata charge is reserved before its one
channel/task and one private shared billing carrier. Worker, receiver and receipt
hold at most three private guards to that one charge, so even a fast consumer
cannot refund it while the sender/worker tail is running. A closed but unpolled
receiver also remains paid after worker panic. The fixed waiter drops its
receiving channel half before exposing a receipt, and every billing guard uses
the existing Arc::into_inner pattern so carrier/header deallocation precedes
the last affine charge release. No Weak, raw Arc or cloneable receipt escapes.
Holding results consumes the original finite cleanup allowance; completed
workers cannot mint unlimited uncharged observations. There is no extra channel,
worker table, quota or ledger. The old general cleanup and ProviderJob APIs retain
their existing behavior.

Admission refusal returns/quarantines the original owner without closing inline.
Worker panic, a lost waiter or observation timeout cannot cancel admitted physical
work or refund the connection. Failed delivery drops the charged result only
after the original resource has entered quarantine. An explicit observation API
is limited to the existing qualification feature. Ordinary retire/drop starts
the same close, even when its observation is abandoned. Public normal installation
still returns Unsupported, and all accounting/production gates remain false.

The new bounded Resource fields are covered by the original client metadata
precharge, which uses its actual compiled size before opening the device. The
receipt uses the original JobCharge and adds actual fixed state sizes plus one
4-KiB shared-carrier padding allowance to its original metadata calculation before
allocation. This increases the admitted charge for the new allocation within the
same limits, not a pool ceiling. The original one-MiB backing and all pool ceilings
remain unchanged. These are resource-lifetime safeguards, not complete allocator/RSS,
kernel or whole-cost accounting qualification.

Source controls preserve the original ten native owner cases and add three
fixed-wire/real-file/result cases. Five original-pool controls cover buffered and
delivered receipt ownership, abandoned waiters, unpolled panic, admission saturation
and deterministic receiver/receipt drop while the actual worker is paused after
publication. Connection quarantine and sender destruction precede the worker's
last billing guard, including unwind; the whole worker is captured together.
All eighteen Rust controls compiled and passed using source-matched normal host
libtest products before the static VM programme; none was ignored. The
deterministic post-publication barrier proved that dropping the delivered receipt
cannot release the charge while the sender/worker tail is still live. No
native-init executable ran on the build host. The former thirty stream cases
remain outside that focused execution and keep their normal suite obligation.

The VM actually reported the accepted-close receipt with descriptor count zero,
connection/failed-cleanup counts one, cleanup jobs two and metadata 1,260,056 bytes.
After explicitly dropping that receipt and awaiting the worker tail, cleanup jobs
returned to one and metadata to 1,120,576 bytes; the connection and original backing
remained quarantined. Bootstrap READY had cleanup jobs one, metadata 1,251,648
bytes and one descriptor. The independent genuine kernel markers established
pending FD handoff, physical bank/actor return and outside collection. Kernel
marker order and PID1 row order are validated separately; reading a ring-buffer
event does not impose cross-stream UART delivery order.
Six Python source/reader controls, twelve actual C parser controls, the existing
PID1 2-MiB/new-child 3-MiB partitions, 4-MiB aggregate loaded spans and whole CPIO,
two CPUs, 512 MiB and 180-second watchdog remain mandatory. All 294 immutable
kernel-producing inputs remained unchanged; no new kernel was built. The actual
Rust child was 2,936,064 bytes, aggregate executable load spans 3,707,056 bytes and
CPIO 3,741,696 bytes. The VM completed in 3.643855 seconds. All 15 bounded commands
returned zero, and all 6,450 current source materials plus 294 immutable kernel
materials matched the tested Git blobs (6,673 unique paths).

The preceding run at `95171d5e95e56a2038c92fcc87870b38b6796bf5` failed core-test
compilation because the new test module lacked its `PlatformErrorCode` import.
Its thirteen native owner controls passed, but its five core controls, static
native build, C controls and VM did not run. Adding only that test import produced
the successful run above. The failed artifact and its exact source remain in the
public observation; earlier constructor-only failures remain in their original
receipt. This result does not claim that the full generic CI suite passed.

Two other jobs then exposed validation failures. The TLS selector still required
forty cases after the three additive native close cases made forty-three. Its
guard now requires all three exact new names plus every existing TLS/accounting/
kernel witness, the original 900-second timeout and no ignored cases. Its seven
source controls passed; this is not a new TLS Rust execution claim.

The runtime-contract source capture exceeded its 72-MiB file-byte allowance by
31,565 bytes: the exact Git archive contained 8,658 selected files and 75,529,037
file bytes, including 28 bytes of Git export substitution. The source allowance
is now 73 MiB; the separate archive transport remains 80 MiB. The actual archive
was 82,944,000 bytes. No selected input is omitted and no guest runtime limit
changes. Two existing focused controls passed; the process helper changed only
its explanatory comment, with identical AST and ownership/cleanup behavior.

These repairs compose six changed Python validation inputs and two owner
contracts after the qualified `976e86c` source. The remaining 6,444 native source
inputs and all 294 kernel-producing inputs are unchanged. The public receipt
records both original and composed identities. The Rust/kernel/C/VM result above
belongs to `976e86c`; it was not rerun or relabelled as the final composition.

An authenticated native post-free consumption/refund channel is still missing.
The current final VFS handoff clears file private data, and the collector
unpublishes the device/pages/actor fields before actual return. Existing reads,
CLOSED, static zero counters and UART therefore cannot become a native refund
certificate. That channel requires separate lifetime, authority and budget
design. Whole #738 acceptance, ordinary socket/TLS use, runtime/operator and
adversarial qualification, full allocation closure and production stay open.
