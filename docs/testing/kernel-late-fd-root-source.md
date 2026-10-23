# Original final-FD custody and late Root collection

This source extends the constructor-only Root collector to an actual final FD
release while its original children are still retiring. It supplies no new
Linux execution result, native quota refund or production selection.

After the existing FD close and cache scans finish, the actual file and its
immutable credential authenticate a one-way `factory.opened` transition from
1 to 2. The file's private pointer is cleared there. The same bank and actor
references remain in the original factory; no file pointer survives VFS release.
Both states still reject a second open. No historical READY bit is invented:
CLOSE_REQUEST followed by immediate FD close can transfer custody too.

The handoff returns a stack-local routing result: refused, already returned or
still pending. Only already returned may use the existing FD fast collector;
pending defers to original kthreadd even if children finish before FD return.
Original permanent kthreadd observes a cheap scalar pending check:
released FD custody, a present bank/Root, actual Request returned and no poison.
Its new branch follows actual Request drain and drops the original creation
lock before taking the same factory mutex as the FD collector. Existing
Task/Control/Request wakes cover retirement; final FD handoff wakes kthreadd
outside the factory and pool locks for the already-returned case.

One full take preserves every original typed-record, lineage, Control seal,
IRQ closure, 128-page preflight and actor-reference requirement. A disappeared
owner is a no-op. A terminal but unqualified retained graph enters the original
sticky quarantine, making pending false instead of spinning. Request still
in progress stays owned without an attempt. The original pages and copied
actor references return outside creation, factory and pool locks. There is no
new Task, workqueue, owner ledger, reset, timeout-derived free or native refund.

The ten focused source controls interpret the actual C custody/pending predicates,
authenticate whole parent identities and retain exact inverse projections.
They do not execute Linux. The predecessor's terminal guards remain required;
fresh/no-BEGIN and unknown failed births do not gain a reclamation shortcut.

The prepared owning programme links one image and boots it twice, each with a
90-second limit inside the original 180-second aggregate VM envelope. The old
fast mode and parser remain required. Late mode must observe a typed live
Request at actual handoff, then the shared physical return and distinct outside
kthreadd return markers. PID1 waits through bounded nonblocking `/dev/kmsg`
reads and `poll` for at most 20 seconds; the host independently checks UART.
PID1's four observation rows and the three kernel markers each retain their
own order. Ring commitment does not fence UART delivery, so a delayed kernel
marker may arrive after PID1's terminal; every kernel marker remains mandatory.
Kernel-origin facility and whole-record flags are required. No synthetic child
snapshot or close/reopen inference substitutes for the actual markers.

The second static init image also runs 22 finite controls through the exact
same pure C parser leaf on the hosted builder before any guest setup. That
explicit control entry has no device, mount, reboot or guest failure path.
Seven new UART/source controller tests preserve raw identities and refusal
cases. No local compiler/kernel/VM was run and no new actual campaign result
is claimed here. The compiled tree's original printk implementation is pinned
and rechecked after the build.
