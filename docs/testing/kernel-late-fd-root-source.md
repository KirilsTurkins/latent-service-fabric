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

The existing immediate collector remains available for an already-retired
graph. Original permanent kthreadd also observes a cheap scalar pending check:
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

The eight focused controls interpret the actual C custody/pending predicates,
authenticate whole parent identities and retain exact inverse projections.
They do not execute Linux. The predecessor's terminal guards remain required;
fresh/no-BEGIN and unknown failed births do not gain a reclamation shortcut.

A separate future owning case must observe handoff **while children remain
pending**, followed by physical page/reference return through the outside
kthreadd collector. Those observations must come from fixed kernel markers at
the actual transitions. PID1's close return, a prior snapshot or failed reopen
is insufficient. No such new campaign is claimed by this source slice.
