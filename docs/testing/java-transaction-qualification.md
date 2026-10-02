# Signed Java transaction qualification

The qualification conductor in `tools/java_transaction_qualification` retains
the five original Java components compiled at
`ff9ecd0733456bceacf5b96f14274b9c2dc0e8e6`. It checks the original component,
source inventory, source archive, compiler report and exact companion bytes.
It never invokes a Java compiler or replaces those materials with a new build
observation. The preserved requirements describe ceilings and grant no state,
intent, provider or dispatch permission.

## Explicit package test trust

`capsule_authoring fixture-sign-java-inputs <new-private-output> <inputs>...`
accepts at most five prepared input directories. It uses the normal
`PackageBundle`, SBOM, publisher and builder signatures, supply-chain policy
verifier and package evidence loader. It verifies the full package-input
inventory before signing, including the exact transaction-binding asset media
type and SHA-256. The output records `ephemeral-native-package-test-only` trust
and the separate synthetic provenance model. Model timestamps describe this
signing fixture, never another execution of the original compiler.

This test fixture creates no `BUILD-COMPLETE` record and does not qualify a
packaged developer distribution. The production node must still validate the
signed package, current policy, original selected publication, companion and
actual installed state and deferred HTTP providers. Successful signing alone
does not qualify signed guest execution or durable command behavior.

The artifact catalog retains the transaction manifest profile only after
checking the exact admitted package, original capsule document and digest-bound
`transaction-binding.json` asset. Bare component metadata keeps the stateless
profile. Deployment decoding and receipt hashing accept finite documents from
both supported profiles, while final catalog validation checks the deployment
against its selected package profile and original signed ceilings. These data
checks grant no execution, namespace, state, intent or dispatch authority.

Packages for the three preserved put-once variants also retain the original
`application-schema-inputs.json`, both schema definitions and exact application
source. The compatible reader and writer packages retain their original
`AggregateCodec.java`; the legacy reader's codec is in its original application
source. These exact captured assets keep their original false review and runtime
qualification flags. An installed native reviewer must independently validate
the maintained codec and recipe and obtain current operator permission.

The existing `lsf.aggregate-migration.v1` recipe continues to target `count`.
The Java components use `aggregate/count`, so the separate fixed
`lsf.java-aggregate-migration.v1` recipe preserves that exact key. Selection is an
installed closed enum, with no arbitrary key or transformer in a request. Its
exact bytes must be declared in the protected verified checkpoint and are pinned
in retained progress. The shared cell codec charges the actual key length, keeps
the namespace quiesced, advances the schema epoch, and requires separate resume
review. Neither recipe executes a guest or provider or automatically downgrades
the value.

## A fresh native clock owner

`capsule_authoring fixture-state-clock <new-private-root> <node-id>` creates an
initial protected checkpoint only for a new disposable qualification root.
The clock floor comes from `latent_core::SystemActivationClock`; the owner epoch
starts at one. The root and checkpoint use private permissions on Unix, and
the create operations refuse an existing root. Its bootstrap receipt records
the actual checkpoint digest and explicitly leaves production restore
qualification false. It writes no continuity flag. Production
`ProtectedCommandClock` derives continuity from its own actual samples.

The real immediate-HTTP negative component remains one of the five preserved
compiler inputs. The native strict-profile metadata validator must refuse its
unsupported host import before signing. This refusal has a separate original
diagnostic receipt; it is not signed node admission evidence. The other four
components continue through the normal package and signing path.

The fixture never overwrites an existing checkpoint, lowers a retained floor,
or initializes an existing state store. Restart and restore tests preserve the
original protected checkpoint and require the normal reviewed recovery paths.

## Native startup diagnosis

The private `latentd` example `transaction_recovery` diagnoses an existing
protected store after the node has physically stopped. It loads the protected
node configuration and an exact protected bearer token, authenticates through
the same native transport credential owner, and requires the matching tenant's
administrator identity. It opens with creation disabled and runs the ordinary
complete linked record validator. It returns only finite initialization and
codec failure codes, original checkpoint numbers, actual clock continuity, and
observed drain and worker-join facts. It returns no stored payload or credential.

Build the example with the normal locked managed profile and run it with
`--config`, `--credential-file`, and `--tenant`. The helper initializes no
dispatcher epoch and changes no business rows. Its descriptive owner checkpoint
does not authorize restart or restoration. A failed startup can be physically
retired while its cleanup report remains unclean; a deadline or dropped waiter
does not prove retirement. Building this helper and inspecting a failed physical
root are separate observations from signed Java guest execution.

The explicit `--diagnose-startup` switch runs the normal startup path and its
ordinary shutdown under the same protected administrator and tenant check.
Its `latent.startup-failure-observation.v1` report retains at most 32 finite
stage and producer error codes in an isolated async task scope. It records
failures only, preserves the original public errors, and excludes error messages,
configuration, paths and credentials. `startupSucceeded`, `terminalFailure`
and the actual shutdown report describe the outcome; helper process success
means that it returned an observation.

Normal startup can advance the durable dispatcher epoch and process an existing
backlog. Run this switch only as a separately retained attempt on a disposable
qualification root. Keep the original failed root and read-only diagnosis
receipt intact. The trace grants no checkpoint, namespace, provider or recovery
authority and follows all ordinary startup and shutdown limits.

## Evidence boundaries

The bounded receipt parser checks full-width unsigned values, absence versus
presence, canonical 67-byte view/key tokens, original durable result bytes,
command/attempt/effect identities, expiry and server-issued abort fences. Its
unit inputs are synthetic frames and are not guest or node evidence. An actual
campaign must record the original signed package inputs, exact native binary
hashes, authenticated policy mutations, retained query views, socket responses,
provider observations and positive shutdown/retirement reports separately.

The immutable production binaries built at
`0537a6682f7a7e89c00c13d2bb327432cc3ad6cb` precede the transaction manifest
profile closure and the historical result-read change described in
[Historical transaction results](../development/historical-transaction-results.md).
A signed Java campaign must use new native binaries containing both changes.
The older binaries cannot supply signed Java or positive schema/restore
result-recovery evidence.

The disposable external recipient implements the existing native
`latent.http-effect.put-once.v1` HTTPS contract. Its bounded private records
preserve original effect, payload digest, provider incarnation and retention
horizon across restart. Reserved acceptance and applied receipt are distinct;
the transition appends a record without overwriting the original acceptance.
The fixture can disconnect after durable recipient acceptance and withhold
lookup delivery until its fault mode changes. These are external observations,
never evidence of platform commitment, a namespace grant or recipient delivery.

## Current policy provisioning

The conductor provisions a private empty state directory, then starts the same
production node with no installed transaction operations. It publishes the four
signed original packages through the normal authenticated release API. A separate
stopped-node `inspect-transaction-hosts` observation reads the exact retained
publications and real native state, clock and qualified HTTP constructors.

Policy proposals must retain that actual observation's state and effect profile,
configuration digest and epoch. The HTTP caller and management RPC caller use
their separate actual authenticated `OriginalCaller` scopes; independent deferred
dispatch uses the original source service's `ServiceIntegration` scope. The
conductor refuses an earlier runtime that cannot describe the real transport
principal. Python never derives a recovery scope, provider digest or grant from
the declarations. Explicit authenticated policy mutations, their original
receipts and current acceptance checks remain authoritative.

Only after those mutations does the node start with the exact signed operation
descriptors. The administrator creates the namespace through the normal state
management API. The fixed HTTP routes select command, fresh query and original
result lookup. Bodyless queries and result requests carry no content type or
business body. Synthetic provisioning/parser tests and the local HTTP transport
fixture do not qualify native transaction execution.

## Run the focused native campaign

After building current production binaries, run the compiler-free conductor in
an isolated Linux environment with Python 3.13 and a new private output root:

```bash
python3.13 tools/run_java_transaction_http_qualification.py \
  --cli /native/latent --node /native/latentd \
  --aot-compiler /native/latent-aot-compiler \
  --contracts-tool /native/capsule_contracts --signer /native/capsule_authoring \
  --portable /inputs/portable-r3 --output /owned/java-transaction-r1 \
  --native-source-commit <exact-binary-build-commit> \
  --conductor-source-commit <exact-collector-commit> \
  --timeout 1200 --prepare-authority-only
```

Both source identities are supplied explicitly and remain separate from the
original Java compiler source. The runner hashes all five native executables and
the collector files before and after execution. It creates fresh ephemeral
package trust, uses the actual native clock sample, and obtains real provider
and authenticated-caller observations from the stopped node. Policy mutation
receipts establish authority; the observation and configuration do not.

The preparation mode stops before policy mutation or namespace creation. It
publishes the preserved signed test packages, obtains the actual stopped-node
host observations and current catalog receipts, then positively stops the
original node and recipient owners. Its private `authority-candidate.json`
contains the exact proposal documents, signed/publication identities, native
and collector hashes, source observations, original clock and stopped-owner
reports. Each proposed policy apply retains its exact compact JSON file, digest,
byte count, fixed operation ID and original expected generation zero.
Successful preparation reports `authorityPrepared: true`, zero candidate policy
mutations, and false campaign and signed-guest qualification status.

After review of these current candidate bytes, rerun the same command with the
same tools, source identities, portable inputs, output root and timeout. Replace
`--prepare-authority-only` with both:

```bash
--resume-candidate /owned/java-transaction-r1/authority-candidate.json \
--candidate-digest sha256:<exact-reviewed-candidate-sha256>
```

The supplied digest pins the reviewed bytes. Native authenticated policy
mutation and current-purpose checks still determine permission. Earlier approval
for another conductor, native build, package or policy document cannot approve
this changed candidate. Preparation and resumption use the same original Linux
boot and monotonic deadline; the pause consumes the original 1,200-second
lifetime. Expiry, a boot change, or observed wall/monotonic drift refuses
continuation. This observer never certifies native clock continuity.

Resume verifies the original private root identity and retained-file census before
consuming a one-shot `authority-candidate-used.json` marker. The census excludes
only the candidate itself and the descriptive preparation footer written after
capture; both remain outside native authority. It preserves the
original signed package expiry, listener port, TLS and credential bytes,
recipient incarnation, policy files, mutation IDs and preconditions. The actual
native host tuple and selected publication and empty-policy catalog receipts
must still match before the first policy apply. It does not regenerate a
profile, re-sign a package, republish a component or refresh a grant. An expired
or changed candidate requires a separate fresh attempt and fresh review; a
failed or uncertain consumed attempt is preserved and cannot automatically retry.

All original counts are cumulative: at most six node sessions, three recipient
sessions, 256 CLI calls, 64 recipient requests, 96 recipient connections and 32
retained external records. The recipient resumes its original stopped counters
and retains the 69-entry directory limit. Evidence retains its original 1,024
files, 32 MiB total and 64 measured-case bounds. The stopped-file observation
refuses links, more than 4,096 entries, more than 16 directory levels, a file
above 256 MiB or a total above 1 GiB; the candidate document is at most 1 MiB.
These observer bounds change no production profile or grant.

The original preparation receipt and evidence bytes remain intact. The final
`campaign-resume-receipt.json` adds only actual resumed observations. The use
marker prevents a conductor retry; it establishes no durable command outcome,
physical retirement, delivery, native grant or packaged qualification. Synthetic
source tests of this protocol remain separate from actual signed-node execution.

The campaign checks real command/query/scan sockets, lost response recovery,
canonical duplicate input, changed input under the original command ID,
declared rejection replay after a later business change, stale edit and caller
and tenant isolation, current read revocation/restoration, and compatible
publication cutover. It then crashes its own reserved node leader only after
proven commitment and actual uncertain dispatch with durable recipient
acceptance. Restart must preserve the original result, effect, receipt and
retention horizon. External recipient acceptance never establishes LSF
commitment or recipient delivery.

Every CLI/native process and socket response has a bounded original observation.
Failed attempts remain in their private output root. The final receipt reports
only cases actually completed, requires positive final native shutdown counters,
and explicitly lists missing schema/restore, trap/fuel, precommit cancellation,
memory exhaustion and full retention-window scenarios. A pass of this focused
campaign does not complete the full Java or Phase 4 acceptance checklist.

To include the installed schema and terminal-history restore sequence, also pass
`--recovery-helper /native/transaction_recovery` and
`--recovery-source-commit <exact-binary-build-commit>`. The helper must come from
the same source as all five native executables and is hashed before and after
execution. The conductor waits for actual quiescence and positive physical
shutdown before each of its twelve offline calls. It supplies the native
snapshot/manifest digests, original 67-byte views and exact observed restore-window
acknowledgement to the installed current-purpose reviewer. It never supplies an
approval, grant or clock-continuity field.

The sequence stages and completes the fixed migration, explicitly resumes it,
then queries the real V2 Java writer and replays the original V1 commitment and
business rejection through current result-read authority. It rejects the old
query minimum. A later V2 command establishes a deliberate post-backup loss
window before fresh-root restore, current review and explicit resume. Recovery
must preserve the original result bytes and IDs, invalidate the old query view,
and return unknown for the lost newer command without rerunning it.

One private bounded recipient observation records its actual GET/PUT counters
before replies or accepted disconnects. It does not establish LSF commitment or
recipient delivery. Migration and terminal-history restore/replay must leave
those counters unchanged, including before recovery review. The recipient keeps
its original 64-request, 32-retained-record and 69-directory-entry bounds.
Snapshots and credentials stay in the private output root. The case status and
remaining-scenario list change only after the actual sequence completes. This
terminal-effect snapshot does not qualify the separate pending-effect restore
reconciliation case, nor trap/fuel, precommit cancellation, memory exhaustion,
full retention expiry or packaged distribution acceptance.

## Installed native offline actions

On Linux x86-64, `transaction_recovery --request-file <protected-json>` selects
one bounded offline action through the normal native catalog owners. It is
mutually exclusive with startup diagnosis. The request is at most 16 KiB and
contains an exact installed publication plus a closed action: snapshot,
inspect-namespace, inspect-restore, restore, stage-migration,
complete-migration, review, or resume. Original operation IDs, checkpoint
digests, restore-window acknowledgement and 67-byte view tokens remain data;
the request has no approval, grant, plugin or deadline fields.

The helper authenticates the configured transport administrator and selected
tenant, loads the actual signed companion and retained package assets, and
retains current purpose-specific policy decisions under the real native state
profile. Native recovery purposes use a separate explicit administrator rule;
every policy/binding operation array retains its original 16-operation bound.
The helper refuses any actual retained decision that requires a durable audit
acknowledgement: this bridge has no recovery audit append port and never treats
an operator ID, snapshot receipt or configuration as that acknowledgement. The
finite fixture proposal does not request mandatory audit. Its authenticated
actor and original action IDs remain attributable through the native receipts;
this does not qualify recovery under a policy that requires durable audit.
The installed Java codec reviewer executes finite reader, writer and fixed
migration-recipe conformance against the original schema/source associations.
That native conformance does not establish Java runtime qualification.

Opening the existing protected owner is exclusive and never creates a missing
store, initializes a dispatcher epoch or executes a guest/provider. The full
linked registry checks every retained family in one native view; unknown formats
and foreign scopes refuse. Snapshot files can only narrow the original native
size ceiling to the retained operator grant. Original retained command, result,
effect, payload and schema identities remain recognizable, and unresolved local
work blocks recovery review. A retained pending effect does not establish whether
an external request was sent or completed.

This bridge authorizes one tenant, namespace and incarnation. It refuses a
second namespace even when that namespace has no business cells, including its
original operation receipts and history rows. Retained effects and expired
command floors must belong to the same scope. An installed tenant accounting
manifest must contain exactly that tenant; the helper cannot widen its selected
namespace grant into a tenant-wide or multi-tenant snapshot grant.

Restore, migration, reconciliation and resume recheck their actual retained
purpose and current publication at the existing final writer/publication fences.
The retained owner must meet the original protected checkpoint's minimum epoch
and floor, and actual continuous observed time must meet the retained floor.
Descriptive row numbers cannot update that checkpoint or mint clock continuity.
A staged restore, missing current authority, incompatible codec or rollback
below that protected minimum stays refused. Migration remains quiesced and requires
separate reviewed resume; neither action replays historical effects.

The closed report separates `operationSucceeded` and its original result from
physical worker retirement and `catalogsRetired`. Cleanup failure preserves the
original operation disposition. The example bounds serialized output to 4 MiB.
These source interfaces and native codec/request cases still require compiled
native and actual signed-Java schema/restore campaign evidence before acceptance.

Deliberate staged-restore activation can select the fresh protected destination
with the optional `state.stateRoot` configuration field. It must be an absolute,
bounded operator path; omitting it preserves `dataDirectory/state`. The normal
state owner, read-only host inspection, startup diagnosis and offline recovery
all select that same root through the existing protected engine, lock and layout
owner. Links, unsafe permissions and malformed existing stores remain refused.
The artifact, publication, policy, provider and credential catalogs still use
the original `dataDirectory`. Selecting a root does not grant access, update a
checkpoint, establish continuity, approve a schema or resume paused history.
