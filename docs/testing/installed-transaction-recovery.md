# Installed transaction recovery qualification

The native gateway composes authenticated snapshot, restore, migration and
effect-close actions through the current protected store. See the [2026-10-15
progress packet](evidence/recovery970-current-progress-2026-10-15.json) for later
source-scoped results and remaining qualification limits. The [2026-10-14
clean-source progress packet](evidence/recovery970-current-progress-2026-10-14.json)
retains earlier native and early HTTP controls; complete terminal and pending
restore/close programmes remain unqualified. Every receipt keeps its actual
tested source; the earlier 573-case receipt binds its earlier checkpoint.

The gateway authenticates the protected-file administrator credential, exact
tenant and configured publication. It retains current publication/package
eligibility, signed companion and schema/source associations, purpose-specific
policy generations, the installed store profile, actual checkpoint floors and
the protected effect clock. Each physical writer consumes its original native
fence. It requires existing state identity, installed tenant accounting and the
state-mode file; offline requests cannot create a missing source store.

## Closed native input and output

Invoke `transaction_recovery --config CONFIG --credential-file FILE --tenant
TENANT --request-file REQUEST`. The protected request is at most 16 KiB and has
`publication`, `request`, and optional `decoderSources`. Neither digests nor
paths convey authority. Decoder selectors are closed objects containing only
`componentDigest` and `publication`; at most three extra publications are
accepted, and neither duplicates nor the requested current publication may
appear in that list.
Current action fields are:

| Action | Fields in `request`, in addition to `action` |
| --- | --- |
| `snapshot` | `operationId`, `file: {root,name}` |
| `inspect-namespace` | none |
| `inspect-restore` | `file`, `destinationRoot`, `destinationCheckpointRoot`, `operationId`, `snapshotDigest`, `manifestDigest`, optional `destinationStoreIdentity` |
| `restore` | the inspect fields plus exact `windowAcknowledgement` |
| `inspect-close-effects` | `operationId`, `effectIds`, `reason` |
| `close-effects` | `operationId`, exact inspected `plan`, `acknowledgement` |
| `review` | none |
| `resume` | `operationId`, exact `expectedView` byte array |
| `stage-migration`, `complete-migration` | `operationId`, `file`, `expectedView`, `checkpointDigest`, `checkpointManifestDigest` |
| `resume-migration` | `operationId`, `migrationOperationId`, `file`, `expectedView`, `migrationExpectedView`, `checkpointDigest`, `checkpointManifestDigest` |
| `resume-restored-migration` | `operationId`, `migrationOperationId`, `file`, `expectedView`, `snapshotDigest`, `manifestDigest`, `windowAcknowledgement` |

Digests use `sha256:` and 64 lowercase hexadecimal digits. Restore inspection
returns `windowDigest`; restore requires that exact acknowledgement. Namespace
inspection returns encoded `namespace`, `history`, current `view`, optional
`guard`, and `reviewDigest`. Migration resume returns action `resume-migration`,
encoded current `receipt`, current `view`, and `resourcePhysicallyRetired`.
Generic resume refuses a retained current migration and cannot replace its
protected checkpoint and activation owner. Old v1 recipes and bytes retain
their own approval boundary.

For protected staging, use the same explicit `destinationStoreIdentity` in both
inspection and restore. The identity accepts one through 128 ASCII letters,
digits, dots, underscores or hyphens. Source validation remains bound to the
original source; target validation uses the immutable requested destination.
Omitting the field preserves the legacy inspection/refusal path. Require the
actual restore receipt's `destinationIdentity` to match, then select that actual
identity as the restored node's `state.storeIdentity`. Successful inspection
does not approve restoration or replace the reviewed window acknowledgement.

The requested publication must match a configured current operation and its
actual current deployment. Each extra source independently captures eligible
signed package bytes and the reviewed component, companion, contract, schema,
Java source and current HTTP marker. It must match the current tenant, capsule,
logical deployment, binding, namespace and incarnation. These sources install
no operation, grant or dispatch rule. Only the requested current source supplies
purpose-specific policy decisions. Every selected publication remains subject
to the final currentness fences; unknown or incomplete retained sources refuse.
The review digest includes all selected signed source identities and proofs.
Retained command source schemas must equal their exact signed companion schema;
a compatible reader cannot relabel its original execution source, and the
distinct generic aggregate schema remains unsupported by this reviewed closure.

Ordinary runtime configuration selects one publication's three operations.
Historical decoder sources cannot bypass the runtime's current deployment and
publication checks, and a descriptive source cannot become an authority source.

The output schema is `latent.native-transaction-recovery.v2`. Its six fields
are `schemaVersion`, `operationSucceeded`, `failure`, `result`, `retirement`,
and `catalogsRetired`. Success has null `failure` and an object result. Failure
has null result and exactly `{code,message,retryable}`: the stable platform wire
code, original owner diagnostic bounded to 1024 Unicode characters, and the
original Boolean retryability. Store retirement independently records `clean`,
`physicallyRetired`, `liveWorkers`, `acceptedJobs`, and optional `threadsJoined`.
Retirement never converts an uncertain write into a known abort. Early
configuration/authentication/admission failure may refuse the process before a
store report exists. The collector must retain that failed attempt.

## Finite current ownership

The existing Java declaration remains 96 MiB native recovery capacity with a
32 MiB maximum reservation, 16 MiB retained store recovery capacity, an
8 MiB + 8 KiB recovery job, and an 8 MiB cache. Compact signed captures use the
same package/evidence/current-publication verification with stricter document
and decoded-metadata ceilings. Broad capture behavior remains available.

Signed HTTP response authorization remains 2048 encoded reply bytes. The adapter
separately prepays the unchanged 22,528-byte reply/header/codec envelope against
the existing physical provider ledger. An actual TLS held-response control
passes with the 2048-byte declaration, rejects 2047, observes the retained
physical charge, and retires after one acknowledged mutation. All 62 HTTP
library controls pass; this does not substitute for signed gateway execution.

The original gateway reservation is 32 KiB request, 9.5 MiB plus the configured
cache for Work, and 14 MiB response. The response separately charges 2 MiB result
metadata and its 2 MiB eventual stdout frame before shutdown. A frame retains
its affine owner until its actual bytes are destroyed. It does not reserve
again after closing native admission.

Exclusive custody charges the actual staged cache and descriptors against the
same retained partition; every active callback independently retains the job
limit. The single-namespace snapshot profile admits a 7 MiB callback, at most
2 MiB per row, one namespace and a 64 KiB manifest. Excess encoded lengths
refuse before allocation. The broad 8 MiB callback plus the configured staged
cache still refuses aggregate admission before destination creation.

Fresh restore creates the destination database, lock and `STATE_OWNER_MODE`
through the actual private Fresh producer. It retains all three original
physical identities and rejects byte-identical replacement files. State v2
adoption uses a fresh installation `dataDirectory` whose `state` directory is
that staged destination and a separate fresh `checkpointRoot`; it adds no
`stateRoot` override. Signed catalogs and explicit fresh policy CAS updates are
separate conductor responsibilities. No grant follows from copying catalogs.

## Read-only proposal inspection

`latentd inspect-transaction-hosts --config CONFIG` reads actual signed
companions and current configured adapter/profile proposals. It installs no
StrictCommand, dispatcher or business-store owner and does not advance the
state epoch. The exact store configuration digest is invariant to operation
selection; `operations=[]` preserves it when the state declaration is identical.
Catalog startup and shutdown still use the real protected control owners.
Their supply-chain epoch and restart floor are real control writes. A collector
waits the original admission lease interval after either catalog-owning
inspection before starting another owner; an inspection result cannot waive
that floor or renew its deadline.

`latentd inspect-configured-http-effects --config CONFIG` exposes actual
constructor-derived adapter profiles before publications exist. The schema is
`latent.configured-http-effect-inspection.v1`, with `adapters` containing
`endpointIncarnation` and `profile` fields `provider`, `destination`, `adapter`,
`intent_format`, `payload_format`, and `idempotency_profile`. This is a proposal,
never an approval. The current provider guard accepts Phase 4 with all existing
protected-file/audit/policy/binding requirements; the exact counter field is
`maximumEffectCount`.

## Dispatch and restored migration

`deferredHttp.dispatchAuthority` can explicitly select
`{"formatVersion":1,"mode":"signed-service-integration"}`. This native effect
owner requires the exact signed nonoptional INTENT import and deferred
requirements, and refuses an immediate HTTP import or guest deployment grant.
Every dispatch still requires current publication, provider, configuration,
credential reference and HTTP policy/binding fences for the derived service
principal. The selected scope and grant restriction remain sealed in the
dispatch registry. An absent declaration keeps the original guest-grant route;
the new selection grants no guest HTTP capability.

The separate `resume-restored-migration` action accepts `operationId`,
`migrationOperationId`, `file` (`root`, `name`), the current 67-byte `expectedView`,
`snapshotDigest`, `manifestDigest` and `windowAcknowledgement`. It rereads the
same protected single-namespace archive and exact completed Java migration.
The current ready restore guard, original restore-operation/window/review,
current package/schema/purpose and original writer/native fence remain required.
The first activation advances namespace generation once and makes the existing
namespace/history active/ready; incarnation and schema/recovery epochs stay
unchanged. Generic resume and the original migration resume retain their
completed-migration and restored-history refusals.

The result contains `action`, a byte-array `receipt`, `view`, `replay`,
`snapshotDigest`, `manifestDigest`, `windowAcknowledgement`, `reviewDigest` and
`resourcePhysicallyRetired`. The new receipt starts with `RMA\x01`, is bounded
by 8192 bytes, and has a distinct retained prefix. Exact replay returns the
original receipt/view without activating later state. Its attribution includes
the exact restore operation and protected archive progress digest. Migration
and original migration resume now consume the same scoped decoder/custody work,
retaining the existing broad-profile refusal and every qualification ceiling.

## Pending recovery conductor

`tools/run_java_pending_recovery_qualification.py` is a separate finite current
conductor. It selects six named ordinary node sessions and one empty-operation
restore-authority session. The default terminal program remains fourteen
sessions; current HTTP terminal qualification explicitly selects eighteen before
its first start. The pending program remains six sessions. Its twelve native
actions export an actual
unattempted pending effect, resume the original installation for real remote
acceptance and reply loss, restore the older pending bytes, inspect and close
the exact stable effect ID, replay that close, review and resume. The dispatcher
control uses the existing authenticated node operator, original owner epoch and
revision, durable audit and immutable receipt lookup. Logical pause alone cannot
satisfy the physical drain required before backup.

## Collector observations and uncertainty

Dispatcher mutation and receipt lookup retain the original operation, action,
tenant, scope, owner generation and `automaticRetry=false`. A receipt lookup
must match the original receipt and durable audit acknowledgement. It creates
no new mutation or inferred external outcome.

Explicit read-only observers may consume at most eight attempts for the closed
`resource-exhausted` transport response. Every refusal remains recorded as a
dispatched, unknown outcome. The original absolute cutoff, ten-second drain
bound and 256-call campaign limit remain in force. Mutation, receipt replay and
cancellation retain their single-call behavior.

A stored pending command may report `RECOVERY_REQUIRED`, `outcomeKnown=false`
and `metadataDurable=false`. The collector preserves those fields and checks
the original key, scope, source and distinct retention identities. A stored
record cannot replace the current original host's running staging witness or
authorize cancellation, commit or abort.

Accepted-operation bytes and resident engine/worker allocations have separate
retained owners. A zero operation counter cannot prove engine retirement.
Staging witnesses describe the original command/attempt/transaction/publication
association without making staged data durable or granting effect delivery.
Unknown stored error codes remain unavailable; they cannot manufacture a durable
abort result or retry permission.

## 2026-10-14 clean-source progress

The [progress packet](evidence/recovery970-current-progress-2026-10-14.json)
binds source `6a380a5990b0d0138fc138e74125c4cf2fe01bea`, tree
`75971ef5753fb1271f6f59925d0883bab589e9ba` and 9,494 verified tracked files.
All 1,958 active native controls pass across eleven libraries; all 66 original
ignores remain registered. Three explicit compiled-guest controls pass, and six
independently copied native tools were built from that exact clean source.
The packet records the actual compiler profiles, tool hashes, collector bytes
and private receipt hashes. Later documentation commits do not change that
execution identity.

| Signed programme on that source | Actual result |
| --- | --- |
| Early HTTP denial | Passed with typed denial, unchanged business state, zero TCP contact and physical retirement. |
| Terminal recovery | Failed at stale-edit abort proof after eighteen measured cases. All four individual post-stage trap, fuel, cancellation and native-memory cases passed; the memory case satisfied the existing strict diagnostic and original durable-abort checks. |
| Pending restore/close | Failed at the original offline resume after nine measured cases. Namespace inspection, snapshot and catalogue retirement succeeded; the retained effect remained literal unattempted Pending work. |

The terminal stale precondition returned `recovery-required` without a durable
abort fence. The pending resume refused a nested publication/policy fence;
neither refusal supplies a terminal result or retry authority. Both failed
attempts remain preserved and unqualified. Their separate fixes require fresh
native tools and complete signed programmes before these results can advance.

The new [native-memory capture packet](evidence/java-current-native-memory-capture-2026-10-14.json)
contains six actual captures from clean compiler source `eba0d96e`. The five
ordinary components remain unchanged. The diagnostic memory probe uses bounded
direct buffers under the original 4 MiB Java heap and 64 MiB native grant;
it does not relabel the earlier managed-heap trap as native exhaustion.
The closed custody controls passed nineteen signer cases, fifty-two actual
signing/material/tamper checks and eighteen Python cases. Those checks remain
separate from complete runtime and packaged-distribution acceptance.

Issues #707, #399, #388, #391, #709 and #718 remain open for their broader
requirements. No ticket closure is inferred from this progress packet or the
51 successful/skipped hosted checks observed on `6a380a5990b0`.

## Earlier source and custody records

The [original gateway record](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/testing/recovery970-current-gateway-2026-10-12.md)
retains the individual tuple builds, constructor previews, stopped attempts,
compiler controls and hosted-image observations. Their compact JSON packets
remain in the current tree, including the [default tuple](evidence/recovery970-default-tuple-1d7-2026-10-13.json),
[restored activation](evidence/recovery970-restored-activation-2026-10-13.json),
[pending conductor](evidence/recovery970-pending-conductor-2026-10-13.json) and
[native owner controls](evidence/recovery970-native-owner-controls-2026-10-14.json).
They retain their exact sources and limits; later code needs new evidence.
Full signed recovery and packaged acceptance cannot be inferred from those
separate compiler, synthetic-peer or controlled-owner observations.
