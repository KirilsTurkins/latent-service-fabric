# Sign independently built related capsules

This development workflow extends the existing [signing contract](../reference/publisher-trust.md)
and [static delivery workflow](static-release-workflow.md). Each capsule keeps its
own package, component, source snapshot, compiler observation and signatures.
Related artifacts do not share a component identity or gain interchangeable trust.
The `canonical-policy` command requires a CLI built from this development source;
it is not a command in the released alpha.4 or alpha.5 CLI.

## Prepare approved public inputs

An operator supplies approved publisher and builder policy documents in the
existing v1 formats. Include a separate exact source requirement for the adapter
and domain builds. Keep each `builderId`, `buildType`, `sourceRepository`,
`sourceRevision`, `sourceSnapshotDigest` and `requireReproducible` requirement
unchanged. Requirements are alternatives under the authoritative verifier;
combining them into a wildcard source or substituting another builder widens trust.

```sh
"$Cli" --output json package canonical-policy --publisher-policy "$ApprovedPublisherPolicy" --builder-policy "$ApprovedBuilderPolicy" > "$CanonicalPolicyResult"
```

The normal `latent.cli.result.v1` result contains a
`latent.signing.canonical-policy.v1` data document. Each role has `canonicalJson`
and `policyDigest`. Use the exact digest for that role's approved revocation
snapshot. Retain the exact canonical JSON string when comparing bytes; ordinary
JSON object serialization can change field order. The command neither creates
revocations nor substitutes a corrected digest into an already approved policy.
Have the policy owner approve the assembled current policy and revocations.

The runtime's `PublisherPolicy` and `BuilderPolicy` parsers perform all validation
and ordering. Keys are ordered by SHA-256 of the decoded raw Ed25519 public key,
not their textual base64, identity label or input position. Builder requirements
use the runtime's ordering. The helper permits at most 64 keys per role, 64 builder
requirements and 65,536 input bytes per role. Duplicate decoded keys, conflicting
key identities, repeated identical requirements, weak keys, invalid/noncanonical
base64, duplicate JSON fields and unsupported source/build profiles fail closed.
It does not merge overlapping requirements or accept a new trust anchor.

The shared [public golden vectors](../../examples/signing-policy/canonical-vectors.json)
cover two keys and two exact Java sources. The CLI tests validate their complete
canonical bytes and digests through the actual runtime constructors and compare
independent permutations. These public keys are test data, with no private keys
or production authority. A vector is not an attestation or build observation.

## Sign and verify each actual artifact

Use the maintained [Java authoring build/sign workflow](../component-development/java-authoring.md)
independently for the adapter and domain. Approve both observed output identities
under the selected policy. Keep production signing material outside source,
capture and build outputs; ephemeral qualification trust belongs only to the
isolated test node. No unsigned package, synthetic observation or downloaded
binary becomes approved by running this helper.

```sh
"$Cli" --tenant "$Tenant" package verify "$AdapterPackage" --evidence-index "$AdapterEvidence/index.json" --evidence-root "$AdapterEvidence" --policy "$ApprovedPolicy"
"$Cli" --tenant "$Tenant" package verify "$DomainPackage" --evidence-index "$DomainEvidence/index.json" --evidence-root "$DomainEvidence" --policy "$ApprovedPolicy"
```

Publish the original verified packages through the existing signed-publication
workflow using distinct persisted operation IDs and exact generation preconditions.
If a management response is lost, recover that operation's receipt. A policy
canonicalization pass provides no publication, admission, execution, reservation
or retry authority. Do not replay an uncertain publication with a new identity.

Changing either package or observation invalidates its approval/signature.
Changing policy invalidates the revocation policy digest; wrong builder, missing
evidence, revoked keys/evidence and stale proofs remain verifier failures. The
former input-order mistake is addressed by obtaining `policyDigest` from the
authoritative constructor before approval, while invalid evidence stays rejected.

The two-Java-component execution qualification is owned by the maintained
HTTP composition fixture from [issue #708](https://github.com/KirilsTurkins/latent-service-fabric/issues/708).
Canonical vectors and CLI unit tests do not alone qualify its live admission,
deployment, HTTP behavior or a private application integration.
