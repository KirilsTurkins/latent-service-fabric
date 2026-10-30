# Initial-only Root physical return

The [owning campaign](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40036590425/job/120697476339)
passed at `0f1e453448bc10a7d2c60453ab69140283834182`: a successful factory open
whose final VFS release occurs without BEGIN physically returns its original
Root bank and four actor references. The [public receipt](evidence/kernel-no-begin-root-physical-return-2026-10-24.json)
binds the actual source, images, commands and raw observations. Failed open
without a successful file/VFS release remains excluded.

The final file handoff captures a strictly initial-only candidate before
changing opened1 to opened2 and clearing private_data. Stack-local route3 may
enter the FD fast collector; pending child route2 cannot. The existing
kthreadd pending predicate and drain remain byte-exact and still require actual
Request return. No Task, workqueue, callback, ledger or release API is added.

The new guard authenticates the initial owner63/gen1, Root slot1/gen2 and next
generation3. The owner has one LIVE Root and no continuations; its cursor and
the Root extent equal the rounded actual sizeof Root. All other63 owners have
zero historical generation/cursor/scope/occupancy, with only the original
close bits set. Backing record0 and Root record1 retain their exact original
identities; the other254 records must be canonical EMPTY, including embedded
route-cache metadata and security-cache fields. RETURNED history is refused.

Every named member in the actual transformed Root is checked: only its key,
Root ticket and CLOSED bootstrap state may be nonzero. Its expiry remains0,
so BEGIN and partial/failed births are excluded. The actual constructor first
memsets the complete object, including padding. The guard never reads padding
as proof; extent calculations use real sizeof, and source controls compare
every typed member against the guard. Whole actual Root/prepaid/route-header
identities are mandatory, so an unknown future member/layout fails closed.

The permanent IRQ hint must be EMPTY with uncertainty0 and every identity,
Task/Request pointer and bank-base field0. Only after original Root queue and
finish does EMPTY transition once to RELEASED. No descriptor was initialized
or queued, so none is synchronized or followed. Both cached EMPTY and current
RELEASED last-stack callers take the unchanged ordinary0 early return before
any hint range/pointer read. Original prepare requires a LIVE Request, Task and
kthread metadata; exact initial history excludes a previously validated
prepare. Terminal state never resets and future prepare cannot win its CAS.

All existing common qualification, admission, uncertainty, observer/tap,
application-history, exact128-page and opening-actor-reference guards remain.
The child-retired branch, page preflight, physical helper and pending/drain
are preserved byte-for-byte. A post-Root-finish IRQ failure only poisons and
retains the original bank, with no subsequent Root payload access. Success
unpublishes all original global handles under pool_lock, then performs the
existing physical return and four actor puts outside locks. Static seals,
opened/initialized flags and generations remain sticky; no static bootstrap
charge or native quota is refunded and production selection remains closed.

Focused source controls interpret the actual C predicates, reject every
noninitial Root/record/embedded-route member, bind the owned derivation recipes
and restore all five parent outputs by exact inverse projection. Source checks
alone do not execute Linux or certify physical free. The actual fresh no-BEGIN
boot retained this opened snapshot and required the post-physical kernel marker:

```text
LSFVM1 snapshot=opened state=0 error=0 field0=0 field1=0 field2=0 field3=0 field4=0 field5=0 field6=2 field7=0 field8=0 field9=0
[    2.339616] LSFVM1 physical-return=constructor-root-bank-and-actor-refs
LSFVM1 result=PASS stage=actual-no-begin-descriptor-close-returned
```

The snapshot has only backing and Root LIVE. PID1's terminal reports close
returning; the separate kernel marker follows actual page return and all four
original actor puts. The host requires that marker exactly once and preserves
the raw serial identity. Kernel and PID1 UART delivery order are checked
independently. No BEGIN, READY or child-retirement snapshot is manufactured.
Close return and zero counters provide no substitute for the physical marker.

The campaign linked one kernel in 705.307 seconds, built three fixed PID1 images
and passed three fresh isolated boots: child-retired fast close in 3.199 seconds,
pending-child late close in 3.256 seconds and no-BEGIN close in 3.170 seconds. All 77
mandatory Python controls and 22 actual compiled C parser controls passed; all 16
commands returned zero with descendant cleanup. Independent cached verification
authenticated 55 archive members, 294 committed Git materials, six reviewed
derived changes, 320 unchanged outputs, all three init/CPIO pairs and raw boots.
Security also passed. No campaign was replayed for this receipt update.

All three boots use the same kernel image with 512 MiB, two CPUs, no host disks
and no network. Each command remains capped at 90 seconds; one shared monotonic
deadline of 180 seconds includes all three boots and their observation work. Actual aggregate
time was 9.632 seconds. The three command maxima are not additive. Smaller original
deadline/command limits remain binding, and both limits are restored on exit.
Aggregate expiry refuses success even if the final process returned normally.

This completes the initial-only constructor prerequisite, advancing #738
criteria 4/6. Unknown failed/uncertain births, application/device-used banks,
general cancellation reclamation, native quota release, complete allocation and
bootstrap closure, installed stream qualification and production enablement
remain open. No whole acceptance criterion or ticket is closed by this receipt.
