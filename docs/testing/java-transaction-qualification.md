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

## A fresh native clock owner

`capsule_authoring fixture-state-clock <new-private-root> <node-id>` creates an
initial protected checkpoint only for a new disposable qualification root.
The clock floor comes from `latent_core::SystemActivationClock`; the owner epoch
starts at one. The root and checkpoint use private permissions on Unix, and
the create operations refuse an existing root. Its bootstrap receipt records
the actual checkpoint digest and explicitly leaves production restore
qualification false. It writes no continuity flag. Production
`ProtectedCommandClock` derives continuity from its own actual samples.

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
`0537a6682f7a7e89c00c13d2bb327432cc3ad6cb` can qualify ordinary transactions.
They precede the historical result-read change described in
[Historical transaction results](../development/historical-transaction-results.md).
Positive schema/restore result-recovery evidence requires a new native binary
containing that change; old binaries cannot supply that evidence.
