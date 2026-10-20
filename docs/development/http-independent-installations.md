# Independent tenant HTTP installations

`providers.httpStreaming` remains the original optional installation. The additive
`additionalHttpStreaming` array contains the same strict installation document:
identity, configuration, stream limits, explicit `phaseTiming`, and optional
protected credential directory/references. Null entries and unknown fields refuse.
Each identity has its own provider ID, tenant, service and epoch. Provider IDs are
unique, and an additional HTTP installation cannot reuse another installation's
tenant/service scope or a scalar alias identity.

All real installations and scalar aliases together still occupy at most the
original 14 descriptor slots. The decoded array also has a sixteen-entry
capacity check. Existing
node-wide I/O, pool, metadata, configuration, worker and request ceilings are
unchanged; installing more providers never multiplies those ceilings. Each
provider's original client/connection key, configuration digest and epoch remain
separate beneath the same charged global pool.

Bindings select the exact tenant, provider service and selected HTTP contract.
The existing original 0.3 and explicit phase-timing 0.4 profiles remain distinct.
A profile with one installation uses its original concrete invoker. A profile
with several installations dispatches only after original session liveness and
exactly one same-tenant sealed provider-reference match. Zero or ambiguous matches
return the existing permission-denied HTTP outcome before admission. Liveness and
capacity errors propagate; the dispatcher never retries or falls back to another
provider. The selected concrete provider repeats all original credential, policy,
audit, epoch and budget checks.

Each credential store is opened and bound using that installation's exact tenant,
provider ID and destination. Reusing a reference name does not share material.
HTTP registrations are not scalar aliases. Every store is retained before later
startup work can fail, closed on rollback/retirement, and included in the original
shutdown proof. No installation or descriptor supplies an invocation grant.

This is a source milestone for the same-node tenant-isolation requirement in
#688/#691. The additive controls cover exact binding/profile selection, unchanged
14-slot ceiling, malformed credentials, unique dispatch and original liveness
errors, plus two real secret stores/registrations on one pool and refusal of a
foreign sealed session before any outbound charge. Native compilation/execution
and the signed same-node cross-tenant Java/TypeScript programmes are pending.
Historical single-provider or native-product receipts do not qualify this change.
