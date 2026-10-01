# Current result delivery

The activation receipt retains an optional `ResultDeliveryFence` from the actual
transaction owner. Ordinary activations have no state result authority. A durable
command outcome and an earlier `read_authorized` observation describe history;
consumers use the retained fence immediately around delivery of result data.

`with_current(output_bytes, action)` retains the original caller, publication,
policy acquisition, namespace lifecycle, deadline and cancellation gate. It
checks current purpose-specific policy and the approved output bound before the
short delivery action. It performs no native I/O, guest execution, ledger
consumption, refreshed admission or new deadline. Socket owners retain this fence
through actual write polls; a denied poll releases no newly exposed data.

Command completion and replay reobserve the namespace in the existing protected
worker before producing the fence. Refusal changes delivery availability while
preserving the original command identity, source, durable outcome and version.
Result lookup never invokes the mutating operation or prepares a guest.

Fresh queries obtain their fence after actual guest/native teardown. One bounded
read of the same store checks the current namespace, schema/history epochs and
recovery guard against the query's original NV2 view identity. A concurrent
business generation advance is allowed; it never replaces the observed snapshot
token. Reincarnation, schema or recovery changes, quiescence and unavailable
recovery refuse delivery. The final no-I/O fence retains the original acquisition
and rechecks current policy/publication and lifecycle through the real owners.

The common authority qualification covers actual redb generation advancement,
original cancellation and deadline preservation, command/query mode separation,
schema replacement and policy revocation. Socket and component qualification
must additionally demonstrate that the retained fence reaches the real delivery
owner; compilation alone does not establish that behavior.
