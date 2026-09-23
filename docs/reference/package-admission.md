# Authenticated package admission

Phase 2 executable admission combines the [package format](../protocol/package-format.md),
[semantic packaging checks](../component-development/packaging.md),
[publisher signatures](publisher-trust.md), [builder provenance](build-provenance.md)
and [SBOM policy](../component-development/sbom.md) before a capsule becomes eligible
for deployment or execution. `latent-policy::supply_chain::SupplyChainAuthority`
is the shared node owner. It retains approved public trust configuration and
durable policy/time floors; request data cannot construct that authority.

Phase 3 [web release admission](web-release-admission.md) adds separately typed
browser/SSR package admission through that same authority and concrete catalog.
It uses exact scoped package references, without assigning a capsule component
identity to browser assets. Its host API and receipt are distinct from the
capsule `ReleaseService` methods described below.

The accepted Phase 3 correction in
[ADR-0027](../../adr/0027-separate-publication-authority-from-component-identity.md)
and [RFC-0002](../../rfcs/0002-tenant-scoped-publication-identity.md) separates
tenant-scoped publication from component identity. The catalog now implements
independent publications, tenant-neutral package admission and package coexistence.
[Catalog format 2 and fresh-state setup](publication-catalog.md) describe the
storage boundary. [Runtime and deployment propagation](publication-runtime.md)
and [public RPC/CLI/SDK selectors](publication-api.md) carry those exact identities
through execution and management. Existing component fields retain
their byte identity. Public management requires exact publication references;
internal component reads reject ambiguous associations.

## Select the node mode

The `supplyChain` member of [node configuration](standalone-node.md) selects one
of two closed forms:

```json
{"mode":"trusted-local"}
```

```json
{"mode":"enforced","policyFile":"admission-policy.json","clockLeaseSeconds":5}
```

Use trusted-local only for the controlled local profile; the external-capsule
profile requires explicit enforced admission.
Enforced mode requires a complete valid policy file, bounded to 256 KiB. A
relative `policyFile` resolves against the node configuration file's directory.
The node derives and retains its exact policy bytes before startup. Missing,
malformed or incomplete configuration fails; it never becomes an empty
revocation list or a successful local fallback. An enforced catalog's durable
mode marker also rejects reopening through the trusted-local constructor.

The [node member schema](../../schemas/node-supply-chain.schema.json) describes
this member only. The [policy schema](../../schemas/supply-chain-policy.schema.json)
requires `formatVersion`, positive `generation`, `scope`, `validFrom`,
`validUntil`, `tenants`, `publisher`, `publisherRevocations`, `builder`,
`builderRevocations`, and `sbom`. Publisher and builder policies share the
configured scope but have independent approved keys and requirements. Every
revocation snapshot must match its exact policy. The tenant allowlist holds at
most 128 unique tenants and at most 64 unique publisher IDs per tenant. An empty
allowlist explicitly denies publication. Global publisher approval alone does
not authorize publishing for another tenant.

The policy reader bounds input before allocation-heavy decoding: 256 KiB,
16 levels, 16,384 JSON nodes, 32 members per object, 256 items per array and
4,096 bytes per generic string. The shared policy/receipt reader supports policy
booleans and receipt nulls while rejecting duplicate fields. Typed profiles
reject unknown fields and invalid values; stricter role-specific limits still
apply afterward.

Trust configuration contains public keys, not private signing keys. The node
never imports build-child environments or request annotations as trusted policy.
Replacing the complete approved snapshot through the host API is atomic across
both verifiers, SBOM policy and tenant authorization. Lower generations and
same-generation changed content are rejected against durable floors. There is
no management RPC or CLI policy-reload command in this slice.

## Publish exact package bytes

The authenticated `ReleaseService.PublishRelease` method accepts exactly one
of the existing `artifact` field or the additive `package` field. `artifact`
remains trusted-local compatibility and is rejected by enforced repositories.
For `package`, omit the `release` descriptor entirely, including empty claims.
The package input contains:

- Exact OCI `manifest` and `configuration` bytes.
- `layers`, each containing its configuration `path` and exact `data` bytes.
- Exactly one publisher `signatures` envelope and one builder `provenance`
  envelope, each carrying exact `manifest`, `configuration` and `payload` bytes.
- Zero or one detached `sboms` envelope, according to the configured SBOM policy.

Paths associate immutable bytes with the verified configuration; the server
does not use them as caller-selected filesystem destinations. Detached evidence
uses the exact empty configuration `{}`. Registry discovery and evidence
association alone confer no authority. The [closed JSON projection](../../schemas/package-admission-upload.schema.json)
represents binary fields as padded base64; it is not a new `latent` CLI input
format. Generated RPC clients and the Rust repository API expose admission.
The [operator CLI](../phase-2-operator-workflows.md) publishes selected local
package and evidence bytes with `release publish-package`; the node repeats its
current admission checks. Signature production remains the explicit host
signing API, independent of package build and diagnostic verification.

The adapter authenticates and authorizes the administrator before inspecting the
upload. It bounds retained input capacities and encoded size before conversion.
Existing management defaults remain 20 MiB per request, 16 MiB per layer, and
4 MiB per response. Additional transport ceilings are 256 KiB per document,
256 layers, 240 bytes per path, and eight evidence slots per kind; the enforced
authority then requires the stricter cardinalities above. Signature, provenance
and SBOM payload ceilings are respectively 4 KiB, 48 KiB and 1 MiB. Limits
intersect with configured lower bounds and the aggregate request allowance;
individual maxima are not additive entitlements.

The configured authority verifies the complete bundle, all digest/size
associations, the capsule manifest and actual component/WIT contract semantics.
Only `capsule` packages are executable on this surface. Publisher and builder
proofs must bind the same exact package and observed component, satisfy current
policy/revocations, and authorize the authenticated tenant. Embedded and supplied
detached SBOMs must agree with their package association and content policy.
When provenance and SBOM both declare a source snapshot, those digests must
agree. Missing attribution is never invented.

[Runtime compatibility](release-compatibility.md) also checks the capsule's
declared engine, target and CPU requirements against the actual node profile
before creating current eligibility. Signed requirements cannot substitute for
host support. Recovery preserves exact historical data when the present host is
incompatible, without granting eligibility or making that release routable.

The repository derives publisher and catalog metadata from the verified result.
Its reject-only preflight callback runs before staging, outside the authority
and index locks. The wire adapter constructs and bounds the exact prospective
response there. Only after that succeeds may the repository stage immutable
files and enter the guarded commit. The returned summary must equal the
preflight summary. No API accepts a caller-provided successful receipt, admitted
boolean or serialized grant as a substitute for verification.

## Historical admission and current execution

The [admission receipt](../../schemas/package-admission-receipt.schema.json)
records tenant, package and component identities; publisher/builder key and
evidence identities; optional SBOM identities; policy/revocation identities and
generations; coordinator epoch; and verification/expiry times. Its closed
canonical JSON is limited to 16 KiB. It is historical data, never executable
authority. `ReleaseDescriptor.admitted=true` also describes historical catalog
publication, including the explicitly selected trusted-local mode. `GetRelease` and
`ListReleases` do not turn it into a current authorization grant.

The enforced repository hash-binds the receipt and retained exact package and
evidence bytes in its versioned completion record. Publication rechecks current
trust before rename and after synchronization, before adopting the release.
Recovery checks stored integrity and freshly verifies retained evidence against
the supplied current policy. Corrupt or missing required bytes are corruption;
expired, revoked or unavailable evidence cannot create current eligibility.
No registry connection is required when all exact bytes and fresh approved
snapshots are already local.

Recovery and `DirectoryArtifactRepository::reverify_publication(publication)`
are explicit synchronous control operations. Re-verification requires an exact
scoped publication reference; a component digest cannot select the proof to refresh.
These operations may wait for the private
authority fence, then renew the clock lease and verify retained evidence under
one guard. Publication and re-verification share one nonblocking catalog work
slot. Re-verification returns the historical catalog summary and refreshes only
a bounded process-local grant; it preserves the original receipt and completion
record. This host API is not an invocation-path wait or a new management RPC.

Eligibility identity binds the tenant, exact package and component identities,
and historical receipt bytes. Prepared-cache identity additionally includes the
process-local repository owner and exact grant instance; a refreshed grant cannot
reuse an old grant's authority. Currentness still checks the coordinator epoch,
publisher and builder trust states, proof age, validity intervals and clock lease.
There is no separate positive-verification cache or waiting verification queue.

Sealed process-local eligibility remains separate from preparation optimization
stamps. A catalog-owned [lifecycle capability](release-lifecycle.md) composes
with the current signed grant; local catalogs have lifecycle without a fabricated
signature or package identity. The repository, deployment commit, prepared-cache reuse, compiler work,
readiness and actual activation start all enforce current authority. Cached
code and an old route or ready object cannot authorize a new activation after
expiry or revocation. Final guarded start produces one affine execution grant;
an activation already accepted at that point may finish. This does not claim
atomicity between an external revocation and the literal first guest instruction.
Retiring the catalog owner also retires its old eligibility capabilities.

## Clock leases, retries and fresh admission

`clockLeaseSeconds` is an integer from 1 through 5, default 5. The authority
durably records a future restart floor before enabling a lease. Currentness
checks require a fresh trusted clock sample inside that lease and every
applicable evidence/snapshot interval. A sample behind the observed clock,
outside coverage, or under unavailable authority fails closed. The existing
bounded control sampler starts before enforced catalog loading, renews leases,
and transfers to the running node. Startup deployment recovery retries only
the exact transient `admission-authority-busy` result: each read/check has a
five-second budget and a ten-millisecond timer. It does not retry entire
compilations or mutations; a final recovery fence may retry only before its
callback starts. Invocation and ordinary verification/currentness use
nonblocking ownership checks; invocation does not fsync, wait for renewal,
or allocate a per-release timer or worker. Indeterminate durability
halts acceptance until recovery. A restart before the persisted future floor
may therefore be unavailable for up to the configured lease duration.
Missing floor data in an initialized authority is corruption, not permission to
reset the policy generation or clock history.

Internal lock diagnostics distinguish temporary `admission-authority-busy`
contention from `admission-authority-poisoned`. Both preserve the existing public
`Unavailable` shape and fail closed. Retrying the same poisoned authority cannot
clear poison, renew its clock lease or restore grants; startup's exact busy-only
retry does not retry poison. Public RPC error redaction remains unchanged, so a
generic `Unavailable` response alone does not identify either internal cause.

A valid policy outside its current validity interval may open with no positive
verification grants, allowing historical lifecycle status and management of
retained releases. It cannot admit or execute them until current checks pass.
Malformed policy configuration, invalid persisted floors and unusable clock
state still abort opening; expired validity does not enable local-mode fallback.

Exact retries use the original package/artifact/evidence bytes and current
trust. The original historical receipt and verification time are retained.
One immutable package can be admitted independently in each authorized tenant.
Different packages containing the same component have distinct publications;
correcting an embedded SBOM requires a new package and its own valid proofs.
An embedded tenant restricts admission to that tenant. A tenant-neutral manifest
keeps its original bytes when admitted into an explicitly authorized scope.
Ordinary publication cannot overwrite the original evidence of an existing
publication. Retained selected evidence can be
explicitly reverified while it remains valid. Reissued envelopes use the separate
[lifecycle evidence-renewal operation](release-lifecycle.md#evidence-renewal-and-route-refresh),
with an exact generation precondition and immutable evidence revision. Original
completion records remain unchanged. Old routes retain their old grants; fresh
bounded control compilation, including startup deployment recovery, can obtain
current capabilities for an admitted release that still passes all checks.
Do not overwrite evidence or invent a different component identity to bypass
expiry. A lost or post-rename failed response can leave a pending durable
candidate; reconcile with the repository's recovery/retry procedure.

To replace an obsolete catalog, use the
[fresh-state procedure](publication-catalog.md#supported-storage-and-fresh-state).
Create a new enforced root, select complete packages with honestly observed
builds and required SBOMs, supply independently approved publisher/builder
policies, and admit each intended package. Apply deployments with the exact
accepted publication references. There is no in-place migration or obsolete
format reader.

A trusted-local completion record or component digest cannot establish publisher
authentication or observed build provenance. Copying a receipt, changing a mode
marker or setting `admitted` cannot create that authority. Catalog storage assumes
a cooperating local filesystem owner: cryptographic package admission does not
protect against an administrator replacing the node executable, approved trust
configuration or its entire storage history.
