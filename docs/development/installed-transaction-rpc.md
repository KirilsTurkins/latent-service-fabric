# Installed transaction RPCs

The standalone Phase 4 node composes configured targets with the existing
`NativeTransactionAdmission`, activation manager, Wasmtime backend, cleanup
owner and protected store. `InvokeCommand` and `Query` use the normal activation
lifecycle. `LookupCommand` and `LookupCommit` read original durable records on
the reserved recovery lane without starting an activation or guest.

Use the version-2 `state` member described by
[the configuration schema](../../schemas/node-state.schema.json). Phase 4
accounting, enforced supply-chain, audit and capability-policy owners are
required together. Each operation must select an admitted component and exact
publication, contract/function, deployment, companion digest, state binding,
namespace incarnation and result-read policy. The companion's formats are
`lsf-wit-values-v1`. This slice accepts one explicit state grant/policy per
selected deployment and preserves its operation narrowing. Additional grant
constraints refuse until their adapter is implemented.

The state provider binding must describe the actual protected engine profile,
configuration digest and configured epoch. `ProtectedStoreConfig::inspection_profile`
computes that descriptive identity from the selected engine limits; the
namespace inspection response reports the same identity. It grants no access.
Every request still needs the actual current publication and policy decision.

Configured recovery storage must admit the signed metadata capture: 32 MiB per
job and at least 32 MiB retained capacity cover its current bounded envelope.
The default native profile provides eight recovery slots and 96 MiB. Larger
operation sets must explicitly provide enough room for startup, resident
metadata and a full serving recovery request. Eight targets share each resident
reservation; configuration derivation refuses insufficient capacity.

An absent namespace exposes authenticated namespace management for its signed
binding. Create it through the existing `MutateNamespace` RPC, stop the node
cleanly and restart with the same installed configuration. Restart captures the
real namespace lifecycle and deployment owners before transaction readiness.
Changing an installed deployment invalidates its execution selection; a new
startup captures the changed source. Configuration does not create namespaces
or install a replacement executor.

Original-result lookup derives the default caller scope from the authenticated
principal. A user requires current `read-result` permission; namespace and
dispatcher administration require their existing operator permissions. Lookup
preserves the original fingerprint, publication/schema, attempt, result and
receipt. Explicit historical attempts read their real linked rows. A pending
command is recovery-required and supplies no inferred abort proof. Policy
revocation, original deadlines and retention cutoffs remain enforced through
the final response frame. Receipt-only lookup follows identity retention after
payload expiry.

`GetEffect` requires current `inspect-effect` permission for the original caller
scope and installed authorization publication. It uses the same protected
recovery lane and retained namespace, policy and response owners. The getter
validates the original command/attempt/commit/effect association and complete
durable effect closure. It returns bounded metadata without a payload or any
dispatch permission. Response or delivery-horizon expiry cannot change the
persisted effect disposition, and an uncertain attempt supplies no inferred
provider acknowledgement. Final response frames retain the original read
authority and command identity cutoff.

State-only commands and fresh queries use this installation boundary. The merged
[deferred HTTP installation](deferred-http-installation.md) and
[transaction HTTP routes](transaction-http-v1.md) compose the same runtime with
shared ingress and separately authorized dispatch. The
[stateful reference application](../../examples/stateful-reference/README.md)
derives declarations from its exact signed companion; installing those
declarations does not grant namespace or effect access. Issues #409 and #718
retain wider runtime/application qualification requirements.

For the operational lookup sequence, use [transaction recovery](../operations/transaction-recovery.md).
PR #970's current recovery source is the base of this documentation audit; its
complete terminal/pending native and packaged qualification remains outstanding.
Preserved Java compiler captures and failed receipts qualify only their recorded
sources. The private
`transaction_recovery --diagnose-startup` helper runs ordinary startup and
shutdown and may advance the durable node epoch. Its obsolete offline modes
return `offline-recovery-adapter-unavailable` before opening the store.
