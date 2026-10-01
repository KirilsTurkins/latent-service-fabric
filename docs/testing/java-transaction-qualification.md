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
  --conductor-source-commit <exact-collector-commit>
```

Both source identities are supplied explicitly and remain separate from the
original Java compiler source. The runner hashes all five native executables and
the collector files before and after execution. It creates fresh ephemeral
package trust, uses the actual native clock sample, and obtains real provider
and authenticated-caller observations from the stopped node. Policy mutation
receipts establish authority; the observation and configuration do not.

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
