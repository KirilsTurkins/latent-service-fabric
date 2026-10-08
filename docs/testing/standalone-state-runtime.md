# Standalone transaction runtime composition

An explicit `state` object in the normal node configuration enables the shared
Phase 4 owners before listeners become ready. It requires the Phase 4 budget
profile, enforced supply-chain admission, and the existing capability policy
owner. The node opens one protected state database under its data root, validates
all linked command, result, namespace, history, migration, resume, and dispatch
records in one view, and shares that owner with state management, command
completion, fresh queries, and deferred dispatch.

The `state` configuration has `formatVersion: 1`, a positive
`configurationEpoch`, an external protected `clockCheckpoint` path,
`createIfMissing` (default false), and at most 128 `operations`. Each operation
pins its tenant, component digest, exact publication, contract/function,
deployment, binding, signed companion digest, namespace incarnation,
result policy, and bounded state-policy IDs. Optional entity and route values
are fixed installation constraints. No configuration field grants access.

The loader retains the actual admitted signed package and requires an Asset
named `transaction-binding.json` with media type
`application/vnd.latent.transaction-binding.v1+json`. Its declared digest must
match the exact original bytes. The companion's service, deployment, binding,
operation, namespace, schema, and formats supply the installed descriptor.
Package metadata is not reconstructed from operator input. The shared protected
engine currently requires its Linux/ext4 profile; portable checks do not certify
that physical profile on Windows.

The external checkpoint is a bounded protected document with `formatVersion: 1`,
the actual `nodeId`, a positive `ownerEpoch`, and `clockFloorUnixMillis`. The node
retains one original wall/monotonic anchor, rejects a wall value below the
checkpoint, and refuses cumulative drift, regression, overflow, or poisoned
observation. It never obtains renewed continuity by replacing its anchor.

`StandaloneNode::state_runtime` exposes the actual installed runtime to the
shared HTTP integration. `StateRuntime::installed` selects a retained operation
using the resolved target and publication. `admission` returns the existing
command or query admission owner; `result_admission` returns the Existing-only
lookup path. Commands preserve the original client ID, preconditions, reviewed
business HTTP metadata, and optional explicit retry fence. The node prepares and
canonicalizes actual component parameter types before a durable claim. A query
minimum is the original opaque NV2 view token. Result lookup creates no claim,
component preparation, cell, guest invocation, or automatic retry.

Compatible publication cutover keeps the original command key and fingerprint.
A bounded authorized metadata read selects a separately retained original
signed operation and current original-publication result-read authority. It
does not adopt the new publication as the original source. Missing original
proof, revoked publication, foreign caller/scope, changed schema/history, or a
changed command-row observation refuses disclosure. Ordinary business generation
advance can satisfy an original committed view; a different recovery or schema
epoch cannot. The original outcome, source, time, committed namespace version,
view token, and abort proof remain in their original envelope.

Every request owns ordinary native capacity and its original budget, deadline,
publication, policy, and cancellation control. Accepted storage workers retain
that original owner until physical retirement, including detached responses.
Application lookup uses the bounded recovery-read worker with ordinary global
capacity, preserving the administrative recovery reservation. The result delivery
fence survives budget finalization and checks current purpose during bounded
nonblocking transport polls without storage work or additional ledger charges.

State and transaction management use the normal authenticated management
transport. Shutdown closes ordinary state admission, preserves actual command
and effect owners during node drain, and reports native reservations, physical
storage owners, worker/thread retirement, and quarantine from the actual owners.
Startup failure also closes and drains started owners within one cleanup cutoff;
uncertain retirement quarantines the store rather than reporting it released.

The focused portable milestone registers seven configuration/request/clock
cases and one actual embedded-engine history case. It also preserves all prior
suite cases and ignore guards. This is source and bounded portable evidence.
Full installed signed-component command/query/replay, HTTP socket delivery,
cutover, restart, cancellation, overload, and one-intent dispatch qualification
remain required on the composed Linux node. Deferred adapters are empty unless
explicitly installed from actual native provider and authority owners; a guest
declaration does not establish an adapter, grant, or successful dispatch.

An operation may explicitly install `deferredHttp` with `requirementsDigest`,
`providerId`, `providerIncarnation`, `credentialReference`, `stagingBinding`,
`stagingPolicies`, `dispatchBinding`, and `dispatchPolicies`. This closed object
contains no credential, enabled flag, or authorization decision. Null, unknown
fields, ambiguous policy IDs, and noncanonical identities refuse installation.
The operation must be a strict command, and its admitted signed package must
contain the exact `deferred-http-requirements.json` Asset with media type
`application/json` and the pinned original SHA-256. Its capsule, deployment,
transaction binding, namespace, and companion digest must all match the retained
transaction descriptor. Payload bytes, logical binding/operation, contract,
adapter formats, and finite ceilings come from those original signed bytes.

Installation uses the already configured HTTP provider and protected credential
owner. It shares their transport pools, peer rules, resource counters, and secret
binding with the native `QualifiedHttpEffectAdapter`; it creates no second HTTP
client or listener. The installed configuration and signed requirements narrow
the selection but do not grant it. Before publishing a dispatch rule, the actual
policy store must authorize the retained source service's explicit native
`dispatch` purpose for that publication, namespace/incarnation, entity, result
policy, and derived service-integration recovery scope. The provider binding must
match the adapter's actual profile, combined configuration digest, and epoch.

The original caller separately needs `stage` permission. Its original sealed
staging decision remains intersected with fresh staging checks, and final commit
retains it when the envelope contains effects. Revocation blocks actual commit
before effect admission even when the service's dispatch rule remains valid.
Commands that retain no effects and queries keep their existing final fences.
Before each native adapter acceptance, dispatch rechecks current source policy
and publication under the policy/catalog fence, then the existing namespace,
effect-rule, and original deadline fences. Missing, unavailable, or changed
authority retains `PolicyBlocked`; it does not authorize an accepted-request
retry or infer an external outcome. Configured count limits are ceilings, so a
business rejection can retain zero intents.

The added portable checks cover strict installation pins and exact signed
requirements, including a NUL payload and unsigned overflow. Linux-only cases
add an actual policy/catalog dispatch decision, a real dispatcher with no
dispatch authority, and a retained staging-policy revoke at actual engine commit
acceptance. Their execution results must be recorded separately from compiler
and portable evidence. Full installed guest-to-HTTP dispatch is still a composed
node qualification requirement.
