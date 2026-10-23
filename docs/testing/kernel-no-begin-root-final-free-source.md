# Initial-only Root return source candidate

This source stage extends the qualified late-close implementation at
`7baad1341327ccd36c625e3e545faf0f1306a78e` for a successful factory open whose
final VFS release occurs without BEGIN. The owning programme now includes this
candidate; it has not been compiled or run. Actual no-BEGIN physical return remains
unqualified. Failed open without a successful file/VFS release is excluded.

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
and restore all five parent outputs by exact inverse projection. These checks
do not execute Linux or certify physical free. A future reviewed qualification
must use a fresh real open/no-BEGIN/final-close case, retain its actual opened
snapshot, and observe the existing post-physical kernel marker. Close return,
zero counters and a synthetic child-retired snapshot cannot supply that proof.

The owning campaign links one candidate kernel, builds three fixed PID1 images
and starts three fresh isolated VMs: child-retired fast close, pending-child
late close and initial-only no-BEGIN close. It retains all old60 Python source
controls and22 actual hosted C parser controls, adding10 NoBEGIN source controls
and7 observer/budget controls. No local kernel or VM replay accompanies this
source change. All three boots use the same kernel image,512MiB/twoCPU/no host
disk/no network profile. Each command remains capped at90seconds; one shared
monotonic180second deadline includes all three boots and their observation
work. The three90second maxima are not additive. The original earlier deadline
and command cap are preserved when smaller, and both are restored on exit.
Aggregate expiry refuses success even if the final process returned normally.
