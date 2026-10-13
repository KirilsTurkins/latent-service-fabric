# Current installed recovery gateway checkpoint

PR #970 retains the original authenticated graph and restored-effect receipt
owners, and now wraps the current protected store instead of reinstalling a
competing runtime. Complete signed Java/operator qualification is still pending.
The earlier 573-case receipt binds the earlier source checkpoint and is not a
receipt for this new gateway.

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
| `inspect-restore` | `file`, `destinationRoot`, `destinationCheckpointRoot`, `operationId`, `snapshotDigest`, `manifestDigest` |
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

`latentd inspect-configured-http-effects --config CONFIG` exposes actual
constructor-derived adapter profiles before publications exist. The schema is
`latent.configured-http-effect-inspection.v1`, with `adapters` containing
`endpointIncarnation` and `profile` fields `provider`, `destination`, `adapter`,
`intent_format`, `payload_format`, and `idempotency_profile`. This is a proposal,
never an approval. The current provider guard accepts Phase 4 with all existing
protected-file/audit/policy/binding requirements; the exact counter field is
`maximumEffectCount`.

Actual fixed-r2 preview passed using the real native constructor and an exact
public synthetic trust policy. It produced
`qualified-http-v1:96de426fb7aebd66c97033631e9aec1f85d4eac11f581637e67b7f25239bd161`
for `https://localhost:52027/effect`, the `e` repeated 64 times incarnation,
27-byte request/payload, 2048-byte response/encoded response, 8192 header bytes,
32 headers and zero redirects. Neither business nor checkpoint files were
created. The earlier r4 preview binds an uncommitted all-features product.
The later r5 preview independently passed with frozen committed source
`a37aa97780a15aee55b049cdb23833b0474386d6`, its exact Cargo default-feature
artifact graph, node digest
`1ef7ae4c3782a417a6bc61ff8f01c52e76f8c32de7994d24d022885a46362983`,
the same profile and no business/checkpoint files. These are constructor
controls, not a signed recovery campaign.

The raw default debug node, helper, CLI and AOT products exceed the existing
256 MiB conductor material ceiling. That refusal is retained. Separate copied
products remove only nonallocated debug sections with GNU strip 2.40 and record
both original and transformed byte identities. Every allocated ELF section and
program-header byte compares identical; original Cargo artifacts remain
unchanged. All transformed products fit the same ceiling, while the bounded
contracts and signer products retain their original bytes. The recipe and
products are fixture evidence, separate from production operator qualification.

## Qualification boundaries

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

The [restored activation packet](evidence/recovery970-restored-activation-2026-10-13.json)
records five passing focused controls: real finite Java migration, protected
snapshot, Fresh import and physical adoption; revoked/ignored native fences;
immutable replay after later quiesce; response capacity retained through file
retirement and released to zero; exact guard/source/CAS/codec refusals; and
byte-identical original-file substitution refusal. All 374 state library cases
and 327 active node cases passed, with all 30 existing node ignores preserved.
The strict node Clippy policy passed. These are controlled-owner physical and
library controls; the complete authenticated signed Java campaign remains
pending.

Real signed compact installation/retirement and exact operation-selection
profile controls passed. The real finite fresh restore passed, including the
preserved broad-profile refusal. Eight actual custody controls, five actual
adoption controls and three current NRS2 accounting/final-fence/immutable replay
controls passed. Encoded row/manifest limits refuse before reading the declared
body. Original failed attempts remain retained in the private evidence root.
The decoder-selector update passed all 326 active `latentd` library controls
with 30 existing ignored qualification cases retained, plus the maintained
strict Clippy policy. The complete signed Java gateway campaign remains pending.

These physical controls use explicit native codec/authority fixtures. They do
not replace the complete authenticated signed Java backup/restore/close campaign,
ordinary restored-node policy reauthorization, clean-host packaged operator
qualification or independent acceptance review. New current HTTP source bytes
need distinct reviewed component/source entries; the original pinned table is
preserved. Issues #399, #388, #391 and #709 remain open.
