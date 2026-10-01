# Command completion coordinator

The node transaction admission uses the existing activation manager, protected
store, namespace/policy owners, atomic command ledger and bounded notification
registry. `CommandCoordinator` creates no executor, dispatcher, native worker,
database, timer or command execution map. `CommandAdmissionFactory` supplies the
actual selected publication and distinct original command/result-read owners
against the node's real admitted envelope and budget. Descriptive input cannot
grant access or assert durable completion.

Before publishing a claim, admission binds the original namespace cancellation
gate to the activation registration and reserves bounded native/result memory
from that same activation. The durable claim must retain the original sealed
namespace expectation. An opaque admitted claim is required to reobserve its
exact post-admission generation; raw decoded pending rows cannot do this.
Registration/capacity failure admits no second guest. Known never-started paths
still await actual native retirement before technical abort metadata is possible.

The existing backend teardown positively closes guest access. The manager does
that itself only for a guest that was never created. Completion validates the
complete application response before handing state to the writer. HTTP must
install its approved portable-response codec/validator here; the ordinary typed
codec does not approve HTTP credentials, cookies or session headers.

Success consumes the actual `StateTransactionHost.handoff` plan and captured
intents. Declared rejection discards all staged state/intents. Both publish one
complete atomic namespace/state/result/command/effect/inbox envelope through the
same protected worker. The final abortable acceptance callback repeats current
policy, namespace, publication and effect checks, and accepts the original gate
once. Cancellation before acceptance blocks business commit. Acceptance observed
after cancellation cannot be labelled abort or success without durable lookup.

Original publication/input/preconditions, source/time, business namespace version
and full opaque schema/recovery view token remain in the same envelope. Typed
initial receipts and replay return canonical padded base64 of that original
token. The new closed command/result format 3 explicitly refuses historic formats
1 and 2; no reader reconstructs omitted original history from current state.

`TransactionCompletion` keeps durable disposition separate from delivery failure.
Its private confirmed constructor verifies actual original command/result
linkage. `read_authorized()` must hold before any consumer releases result or
receipt data. Revocation after a physical commit cannot erase internal durability
or grant a public body. Original platform producer diagnostics survive failure
and cleanup; a codec failure is not relabelled as HTTP validation.

Technical abort requires the lower owner's positive private retirement proof and
fresh distinct read/control authorization, not a timeout, notification, dropped
waiter or decoded row. Missing continuity, permission, physical retirement or a
known durable result leaves the original attempt pending/recovery-required.
Physical guards remain in accepted work after observer detachment. Panics after
worker entry quarantine rather than refund occupied memory or infer noncommit.

Duplicates perform fresh authorized lookup before attaching to the existing
bounded registry. Every wake reloads durable state and current permission. A
waiter's own cancellation or deadline detaches delivery only. Missing owner,
interrupted native work, lost delivery and commit uncertainty never schedule a
replacement guest. Explicit protected retry/recovery policy remains a separate
owner operation.

The focused engine tests cover original token preservation across changed
history, later commit and reopen, and exact absent/present history CAS before
no-state rejection/abort acceptance. This source milestone does not certify the
HTTP/management wire adapter, actual component completion campaign, recovery
operator wiring or the full #387/#388/#718 acceptance gates. Those integrations
must consume these owners and are qualified separately.
