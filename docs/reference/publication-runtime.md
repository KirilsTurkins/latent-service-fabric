# Publication-bound deployment and execution

Phase 3 issue #266 carries the [catalog publication identity](publication-catalog.md)
through deployment, preparation and actual guest start. `ReleaseDigest` continues
to identify executable bytes; it does not identify a tenant's admission. This
implements the runtime portion of [ADR-0027](../../adr/0027-separate-publication-authority-from-component-identity.md).
Public RPC, CLI and SDK selectors are the separate integration in #267.

## Deployment selection and persistence

The Rust `DeploymentManifest` and deployment JSON accept an optional
`spec.publication` string containing the exact `publication:sha256:` ID. Its scope
comes from `metadata.tenant`; `spec.release` remains the unchanged component
digest. Null, malformed and foreign selectors fail closed. An explicit selector
must identify that component in the authorized scope.

A new legacy deployment without the field resolves only a unique publication in
its tenant, including the explicit trusted-local unscoped compatibility path.
Revoked and retired publications still count toward ambiguity. Existing
deployments retain their captured selection through unrelated writes, weight
changes and equivalent reapplication. Selecting another package requires an
explicit publication. No new selection chooses the latest eligible package.

The compiled revision and `ResolvedRevision` carry the exact ID. The reserved
`lsf.publication` snapshot attribute carries the same value, so existing v1 scoped
route digests also authenticate publication selection. A projection must keep
the attribute and typed ID consistent. A held route cannot substitute another
publication with identical component bytes.

Deployment catalog envelope **format 5** stores exact publication pins separately
from the original canonical deployment manifests. It also retains combined
rollout and deployment-operation histories. These are different versions from
artifact catalog format 2 and the public manifest API version.

Startup accepts deployment formats 1–4 after validating their original checksum,
snapshot, object versions and histories. It resolves old associations through the
immutable mapping produced by offline artifact catalog migration, or through
unique scoped resolution when no mapping exists. Ambiguous unmapped history is
rejected. The mapping is used only for recovery; it grants no current permission.

Before exposing routes, startup durably writes format 5 through the existing
staging, rename and directory-sync protocol under the exclusive owner lock and
current admission fence. It preserves canonical legacy manifests, revision IDs,
object generations, route generations, transaction versions and historical
receipt bytes. A failed upgrade returns no usable catalog; reopening resumes
from the validated old or completed new record. A current format-5 restart does
not rewrite accepted source bytes. Keep a stopped backup for rollback to older
binaries, which cannot read this new envelope.

## Rollouts and historical authority

Base and candidate carry independently selected publication IDs and package
identities. Distinct packages with unchanged executable bytes may participate in
a rollout. Forward compatibility, retained package inputs, reverse compatibility
and rollback authorization all use the selected publication.

New rollout plan hashes use plan version 2 and bind both publication IDs. Recovery
retains the version-1 hash algorithm for old plans while adding their captured
associations. Old request and receipt hashes remain unchanged. Replaying a
successful operation returns its historical result; it does not restore a grant.
Rollback creates a new route generation pointing at the original base publication,
even when another package containing those bytes has since appeared.

Expired, revoked or retired history remains inspectable through the sealed
historical source. Current execution requires a newly checked positive capability.
Reading a replaced, ineligible candidate for compatibility does not authorize it.

## Preparation, native reuse and guarded start

Sealed borrowed and owned preparation sources accept an exact publication. One
selection binds metadata, package identity, source bytes, lifecycle generation
and configured admission authority. A repository adapter cannot supply metadata
from one source while borrowing another source's grant.

`PreparationKey.publication`, authenticated preparation identity and the prepared
handle keep publications distinct. The standalone activation manager propagates
the captured route ID into its queued preparation. Ready owners and cached
descriptors retain their original eligibility; they cannot silently adopt renewed
authority. Actual guest start checks the prepared descriptor, requested publication,
tenant, lifecycle and current admission at the existing guarded-start boundary.

`IsolatedAotCompiler::reserve_selected` retains this same selection through the
bounded source read and child compilation. Native compatibility keys include the
publication under key domain version 3, in addition to package, component, engine,
target, ABI, producer and policy identities. Old keys and receipts are cache misses
or are rejected; no old wire identity is reinterpreted. Native output or receipts
from another publication cannot authorize loading, even with identical Wasm.
This change keeps native authority separate rather than broadening native sharing.

Compiled/prepared entries remain bounded shared cache resources. Their metadata
accounting includes publication IDs; no publication allocates a dormant guest,
thread or process. Every actual invocation still creates fresh activation-owned
guest state. Cancellation and denial keep source, compiler, ready, instance and
native-image charges until their real owners are released.

## Bounded regression coverage

Tests use small real directory catalogs and tiny components. They cover independent
tenant/package selection, held routes, wrong-publication substitution, revocation,
retirement, warm invocation, native output/receipt rejection, legacy deployment
and rollout migration, byte-exact operation replay, exact rollback after restart,
and interruption of the deployment migration write. Cryptographic policy tests
remain separate from runtime tests that inject a trusted host verifier.

These checks establish the selected authority and ownership behavior. They are
not throughput benchmarks or evidence of hostile-multitenant production qualification.
