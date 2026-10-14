# Current installed recovery gateway checkpoint

PR #970 retains the original authenticated graph and restored-effect receipt
owners, and now wraps the current protected store instead of reinstalling a
competing runtime. The latest [clean-source progress packet](evidence/recovery970-current-progress-2026-10-14.json)
records passing native and early HTTP controls, with the complete terminal and
pending restore/close programmes still unqualified. Every receipt keeps its
actual tested source; the earlier 573-case receipt binds its earlier checkpoint.

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

The earlier `a37aa977` raw default debug node, helper, CLI and AOT products exceed the existing
256 MiB conductor material ceiling. That refusal is retained. Separate copied
products remove only nonallocated debug sections with GNU strip 2.40 and record
both original and transformed byte identities. Every allocated ELF section and
program-header byte compares identical; original Cargo artifacts remain
unchanged. All transformed products fit the same ceiling, while the bounded
contracts and signer products retain their original bytes. The recipe and
products are fixture evidence, separate from production operator qualification.

The [committed `1d7f130b` tuple packet](evidence/recovery970-default-tuple-1d7-2026-10-13.json)
records six separate Cargo builds with default features, optimization zero,
debug information zero, debug assertions and overflow checks enabled. All six
untransformed products fit the original 256 MiB material bound. Their source
archive, actual artifact graphs and immediate original-to-copy hashes are
retained. The original four-role attempt stopped before AOT at the 3 GiB host
headroom floor; only AOT and signer resumed after byte-preserving compression.
The four completed copies were rechecked, and the stopped attempt remains.

The same packet records 53 actual native policy-parser controls against that
committed source. The exact original 3692-byte policy and 287-byte binding
parse successfully with all six existing recovery purpose labels. Unknown,
miscontract, duplicate and oversized operation sets still refuse. This control
created no catalog, authority or guest, and preserves the original one-call,
64 MiB, 60-second policy ceilings. Signed execution and pending-effect
reconciliation keep separate qualification receipts.

The [combined `dd294da2` tuple packet](evidence/recovery970-default-tuple-dd294-2026-10-13.json)
includes the trusted deployment-management profile selection and separate early
HTTP fixture signer. A 1,177,600-byte Git delta plus unchanged regular build
inputs reproduces all 9418 files in its exact current tree; every blob was
verified before and after the six actual builds. Frozen regular artifacts retain
their Cargo inode and byte identity on the same filesystem and were rechecked
after every later role. The initial cross-filesystem hardlink refusal is retained;
the successful node compilation was not repeated. All six products retain the
original default features, assertion/overflow policy and material ceiling.

The [audit-profile `017131dc` tuple packet](evidence/recovery970-default-tuple-017131-2026-10-13.json)
records the same trusted selected manifest profile in managed deployment
validation and rejection-audit identity normalization. The original default
profile remains unchanged. All 131 wire unit cases and 48 management integration
cases passed for that source fix. Its six fresh builds reproduce all 9420 files
of the exact committed tree through a 1,208,320-byte Git delta and unchanged
regular source inputs. Every original-to-copy product hash and independently
copied inode was checked after the builds; previous products and failed signed
attempts remain separate. This packet establishes artifact custody and preserves
the original material ceiling. Authenticated terminal and pending-effect
execution retain their own receipts.

The [fresh signed terminal `r9` packet](evidence/recovery970-terminal-r9-017131-2026-10-13.json)
records five publications, ten authenticated policy applications, ordinary
deployment apply and namespace creation. Trigger apply then returned a known,
dispatched `invalid-argument` failure at CLI call 31. The original operation was
not retried. All four node processes and the recipient were reaped; native/store
physical retirement and zero retained state owner counters were verified from
the actual stopped reports. The recipient recorded zero POSTs and mutations,
and every frozen product hash stayed unchanged. Signed guest execution,
migration/restore and pending-effect close remain unqualified by this attempt.

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

`tools/run_java_pending_recovery_qualification.py` is a separate finite current
conductor. It selects six named ordinary node sessions and one empty-operation
restore-authority session, preserving the terminal fourteen-session program and
the original six-session default. Its twelve native actions export an actual
unattempted pending effect, resume the original installation for real remote
acceptance and reply loss, restore the older pending bytes, inspect and close
the exact stable effect ID, replay that close, review and resume. The dispatcher
control uses the existing authenticated node operator, original owner epoch and
revision, durable audit and immutable receipt lookup. Logical pause alone cannot
satisfy the physical drain required before backup.

The [pending conductor source packet](evidence/recovery970-pending-conductor-2026-10-13.json)
records ten new closed observer/sequence controls and thirty-one retained
current/recovery controls. A live physical owner prevents export; a changed close
replay prevents review and activation; delivery acknowledgements cannot replace
explicit no-redrive abandonment. These are source controls. Signed pending
execution, original post-stage immediate-HTTP rollback and packaged operator
acceptance remain unqualified. The original six-input signer failure is retained:
its forbidden fixture has its own captured service, and the separate six-mode
now preserves that service instead of selecting the positive aggregate service.

## Current controls and hosted image evidence

The separate [clean early HTTP campaign](evidence/java-early-http-clean-source-2026-10-13.json)
passed on `7c4a0dcc`: typed immediate denial, unchanged business state,
byte-identical duplicate and retained-result replay, zero TCP contact and
physical retirement of four node sessions. This does not establish the
post-stage immediate-HTTP rollback case or the terminal and pending programmes.

The current dispatcher CLI includes a recovery selector with the original
operation, action, tenant, scope and owner generation. The pending collector
checks that exact selector on both the mutation response and the read-only
operation lookup, including `automaticRetry=false`. The lookup must also match
the original receipt and durable audit acknowledgement. Both response shapes
remain closed. The regressions fail the previous collector;
all related controls preserve the original no-retry and unknown-outcome checks.
No new mutation follows a receipt lookup or an uncertain result.

The explicit read-only observers can consume up to eight attempts when a
dispatcher inspection or original-command lookup returns the closed
`resource-exhausted` transport response. Each refused read remains recorded with
its dispatched, unknown outcome. The observers keep the original absolute
cutoff, ten-second drain bound and 256-call campaign limit; they infer no result
until the actual audited response passes its original checks. Mutation, receipt
replay and cancellation calls retain their single-call behavior.

A stored pending command lookup reports `RECOVERY_REQUIRED`,
`outcomeKnown=false` and `metadataDurable=false`. These conservative fields are
preserved. The collector verifies the original key, scope, source and distinct
retention identities, then requires the current original host's running staging
witness before issuing the one cancellation request. The stored description
supplies no live owner, commit or abort authority. Fifty-five focused controls
pass with all original cases and CI fixture guards retained; collector identity
also binds the new observer helper bytes.

Dispatcher inspection reports bytes retained by accepted operations separately
from the resident engine and worker allocation. The original reservation lock
charges this counter and refunds it after the affine keeper and completion value
are destroyed. The total byte budget, resident charge and worker-retirement
requirements remain unchanged. The authenticated paused-inspection regression
fails the old implementation; the fixed state, effect and wire library controls
pass with all original ignore obligations retained. A zero operation counter
alone does not establish physical engine retirement.

Retained durable abort lookup and replay preserve codes recognized by the
existing platform-error decoder. Unknown codes remain `unavailable`. These
projections keep their original terminal classification, consumption, proof
association and generic redacted message; they reconstruct no guest diagnostics
or retry authority. The controls publish an actual metadata-only abort after
affine physical retirement, reopen the original store and verify the linked
command/result before projection. Both old mappings fail the `guest-trap`
regression. These source controls do not replace the signed terminal campaign.

The original command host binds a staging observer to its journal owner before
guest access. Only successful insertion of a captured intent produces a witness;
its command, attempt, transaction and publication identifiers come from the
original admitted claim. The journal charges 2048 bytes within the existing
record limit, retains no guest or payload, and rejects stale serials, reused
identities, terminal updates and progress outside the original grant. Inspection
keeps its authenticated tenant, administrator and pagination gates. Wire and CLI
project the existing optional witness field. A maintained compiled Rust guest
proves the complete host-to-manager-to-inspection path: the original code omits
the witness, and the fixed path reports the actual staging before strict runtime
teardown. This source control grants no persistence, delivery or retry authority;
the signed Java campaigns retain their separate acceptance receipts.

The [clean combined native receipt](evidence/recovery970-native-owner-controls-2026-10-14.json)
records 1045 passing active controls, exact suite inventories, all 27 retained
wire ignores and the explicit compiled-guest staging case on `4f88f9cb`. It also
binds six independently frozen native tools to that complete clean source tree.
The terminal and pending signed attempts on those tools remain failed at a
dispatched management RPC returning `resource-exhausted`; neither attempt
establishes complete signed recovery acceptance.

Recovery recognizes only the original and separately reviewed fresh HTTP
marker. Each must match the installed component, signed companion and exact
requirement bytes. The selected marker enters the conformance proof; the
original proof remains byte-for-byte unchanged. The fresh-marker regression
fails the old source, and twelve recovery plus seven clock controls pass with
the fix. Unknown, changed and mixed associations remain refused. These are
controlled-owner results, independent of signed recovery acceptance.

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

The [hosted WSL image receipt](evidence/recovery970-wsl-hosted-image-2026-10-13.json)
records actual successful assembly and inspection of 133 candidate files,
all sixteen pinned packages, licenses, SBOM entries and preserved runtime
repository/keyring bytes. Its clean checkout `7fb713e2` has exactly the
`d30bcf8c` tree. Temporary build sources and package lists are absent from the
export. Account smoke completed through the checked builder path, but its raw
JSON was not uploaded for independent inspection. Publisher authentication,
WSL import and packaged operator qualification remain false; earlier local
upstream failures retain their original failed status.
