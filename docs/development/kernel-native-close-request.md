# Native close request and charged observation

This is source preparation for #738, not an executed close qualification. The
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
The next actual VM must establish that the selected worker receives an authentic
CLOSED reply. Earlier final-file-close success cannot establish this.

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
These Rust controls have not yet compiled or run. The owning controller will
build source-matched normal host libtest products and require all thirteen native
plus five result-lifetime cases before the static VM programme. No native-init
executable runs on the build host. The former thirty stream cases remain outside
that focused execution and keep their normal suite obligation.

The new VM protocol must report the actual accepted-close receipt while the
additional cleanup reservation is still held. Only after explicitly dropping
that receipt may it compare quarantine against the previous single maintenance
reservation. Descriptor absence, native connection/backing retention, and the
genuine kernel physical-return observation remain independent requirements.
Six Python source/reader controls, twelve actual C parser controls, the existing
PID1 2-MiB/new-child 3-MiB partitions, 4-MiB aggregate loaded spans and whole CPIO,
two CPUs, 512 MiB and 180-second watchdog remain mandatory. All 294 immutable
kernel-producing inputs remain unchanged; no new kernel build is planned.

An authenticated native post-free consumption/refund channel is still missing.
The current final VFS handoff clears file private data, and the collector
unpublishes the device/pages/actor fields before actual return. Existing reads,
CLOSED, static zero counters and UART therefore cannot become a native refund
certificate. That channel requires separate lifetime, authority and budget
design. Whole #738 acceptance, ordinary socket/TLS use, runtime/operator and
adversarial qualification, full allocation closure and production stay open.
