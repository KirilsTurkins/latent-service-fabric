# Publication-bound deployment and execution

Phase 3 issue #266 carries the [catalog publication identity](publication-catalog.md)
through deployment, preparation and actual guest start. `ReleaseDigest` continues
to identify executable bytes; it does not identify a tenant's admission. This
implements the runtime portion of [ADR-0027](../../adr/0027-separate-publication-authority-from-component-identity.md).
The [management API contract](publication-api.md) requires exact tenant publications
for release queries, deployment apply and rollout candidates.

## Deployment selection and persistence

For CLI apply and rollout start, deployment JSON requires `spec.publication`
containing the exact `publication:sha256:` ID returned by admission. Its scope
comes from `metadata.tenant`; `spec.release` asserts the component digest.
Missing, null, malformed and foreign selectors fail closed. The selector must
identify that component in the authorized scope. A checksum alone cannot select
a publication, even when the catalog currently has only one matching entry.

Existing compiled deployments retain their captured association. Selecting
another package requires another explicit publication; selection never chooses
the latest eligible package. The internal manifest representation still reads
retained catalog histories; that does not enable component-only network input.

The compiled revision and `ResolvedRevision` carry the exact ID. The reserved
`lsf.publication` snapshot attribute carries the same value, so existing v1 scoped
route digests also authenticate publication selection. A projection must keep
the attribute and typed ID consistent. A held route cannot substitute another
publication with identical component bytes.

Deployment catalog envelopes **5, 6 and 7** store exact publication pins separately
from canonical deployment manifests. Format 5 covers ordinary deployments,
format 6 adds capability bindings, and format 7 includes HTTP route state. These
are current formats, distinct from artifact catalog format 2 and the public
manifest API version. Current operation tables use format 2; their canonical
receipts still use format 1.

Startup rejects obsolete deployment envelopes 1?4, operation tables 1 and rollout
plans 1. It neither infers publication associations nor rewrites old state. The
stored catalog and pending staging files remain unchanged on rejection. Use the
[fresh-state procedure](publication-catalog.md#supported-storage-and-fresh-state)
and explicitly admit and deploy the intended packages again.

Current catalogs retain exact manifests, revisions, object generations, route
generations, transaction versions and historical receipts across restart. Startup
validates the complete catalog and histories before discarding abandoned staging
files or exposing routes. It does not rewrite accepted current catalog bytes.

## Rollouts and historical authority

Base and candidate carry independently selected publication IDs and package
identities. Distinct packages with unchanged executable bytes may participate in
a rollout. Forward compatibility, retained package inputs, reverse compatibility
and rollback authorization all use the selected publication.

Rollout plan hashes use version 2 and bind both publication IDs. Recovery requires
that version and validates the captured associations. Replaying a successful
current operation returns its historical result; it does not restore a grant.
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
retirement, warm invocation, native output/receipt rejection, obsolete catalog,
operation-table and rollout-plan rejection, byte-exact operation replay, exact
rollback after restart, and preservation of rejected state and staging files.
Cryptographic policy tests
remain separate from runtime tests that inject a trusted host verifier.

These checks establish the selected authority and ownership behavior. They are
not throughput benchmarks or evidence of hostile-multitenant production qualification.

## Local currentness and the future cluster boundary

These exact-publication checks consult the configured local lifecycle/admission
owners. They do not establish freshness relative to a remote controller.
[ADR-0030](../../adr/0030-bound-disconnected-authorization-validity.md) and
[RFC-0004](../../rfcs/0004-route-and-authorization-freshness.md) require future
cluster leases to bind this same publication and current authority independently
from route retention and component/code identity. Finite expiry, new-boot
revalidation and conservative clock checks are Phase 5 implementation work.

The guarded-start callback is the acceptance cutover, not the first literal
guest instruction. Work accepted before a later denial may finish under its own
finite deadline/resources; routed, queued or prepared work still has to pass the
current check. [Cluster conformance](../architecture/cluster-freshness-handoff.md)
must preserve this boundary and test its distributed assumptions separately.
