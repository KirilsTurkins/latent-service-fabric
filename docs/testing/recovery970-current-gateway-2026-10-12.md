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
exactly `publication` and `request`. Neither digests nor paths convey authority.
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

Digests use `sha256:` and 64 lowercase hexadecimal digits. Restore inspection
returns `windowDigest`; restore requires that exact acknowledgement. Namespace
inspection returns encoded `namespace`, `history`, current `view`, optional
`guard`, and `reviewDigest`. Migration resume returns action `resume-migration`,
encoded current `receipt`, current `view`, and `resourcePhysicallyRetired`.
Generic resume refuses a retained current migration and cannot replace its
protected checkpoint and activation owner. Old v1 recipes and bytes retain
their own approval boundary.

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
created. Private exact evidence is `target/recovery970/current-http-preview-r4`
and binary build attempt 2; only descriptive evidence is publishable.

## Qualification boundaries

Real signed compact installation/retirement and exact operation-selection
profile controls passed. The real finite fresh restore passed, including the
preserved broad-profile refusal. Eight actual custody controls, five actual
adoption controls and three current NRS2 accounting/final-fence/immutable replay
controls passed. Encoded row/manifest limits refuse before reading the declared
body. Original failed attempts remain retained in the private evidence root.

These physical controls use explicit native codec/authority fixtures. They do
not replace the complete authenticated signed Java backup/restore/close campaign,
ordinary restored-node policy reauthorization, clean-host packaged operator
qualification or independent acceptance review. New current HTTP source bytes
need distinct reviewed component/source entries; the original pinned table is
preserved. Issues #399, #388, #391 and #709 remain open.
