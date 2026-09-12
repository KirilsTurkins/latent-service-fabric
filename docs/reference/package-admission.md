# Authenticated package admission

Phase 2 executable admission combines the [package format](../protocol/package-format.md),
[semantic packaging checks](../component-development/packaging.md),
[publisher signatures](publisher-trust.md), [builder provenance](build-provenance.md)
and [SBOM policy](../component-development/sbom.md) before a capsule becomes eligible
for deployment or execution. `latent-policy::supply_chain::SupplyChainAuthority`
is the shared node owner. It retains approved public trust configuration and
durable policy/time floors; request data cannot construct that authority.

## Select the node mode

The `supplyChain` member of [node configuration](standalone-node.md) selects one
of two closed forms:

```json
{"mode":"trusted-local"}
```

```json
{"mode":"enforced","policyFile":"admission-policy.json","clockLeaseSeconds":5}
```

Omission preserves Phase 1 trusted-local compatibility for local catalogs.
Enforced mode requires a complete valid policy file, bounded to 256 KiB. A
relative `policyFile` resolves against the node configuration file's directory.
The node derives and retains its exact policy bytes before startup. Missing,
malformed or incomplete configuration fails; it never becomes an empty
revocation list or a successful local fallback. An enforced catalog's durable
mode marker also rejects reopening through the legacy local constructor.

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
format. Generated RPC clients and the Rust repository API expose admission;
the complete package/sign/push/admit CLI workflow is tracked in
[#156](https://github.com/KirilsTurkins/latent-service-fabric/issues/156).

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
publication, including the legacy locally trusted mode. `GetRelease` and
`ListReleases` do not turn it into a current authorization grant.

The enforced repository hash-binds the receipt and retained exact package and
evidence bytes in its versioned completion record. Publication rechecks current
trust before rename and after synchronization, before adopting the release.
Recovery checks stored integrity and freshly verifies retained evidence against
the supplied current policy. Corrupt or missing required bytes are corruption;
expired, revoked or unavailable evidence cannot create current eligibility.
No registry connection is required when all exact bytes and fresh approved
snapshots are already local.

Recovery and `DirectoryArtifactRepository::reverify_retained(tenant, release)`
are explicit synchronous control operations. They may wait for the private
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
stamps. The repository, deployment commit, prepared-cache reuse, compiler work,
readiness and actual activation start all enforce current authority. Cached
code and an old route or ready object cannot authorize a new activation after
expiry or revocation. Final guarded start produces one affine execution grant;
an activation already accepted at that point may finish. This does not claim
atomicity between an external revocation and the literal first guest instruction.
Retiring the catalog owner also retires its old eligibility capabilities.

## Clock leases, retries and migration

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

Exact retries use the original package/artifact/evidence bytes and current
trust. The original historical receipt and verification time are retained.
There is one immutable package association per component release digest;
different package, tenant, metadata or evidence for the same component conflicts.
Retained original evidence can be explicitly reverified to refresh current
eligibility while it remains valid. Reissued signature/provenance envelopes and
atomic evidence renewal belong to [release lifecycle #148](https://github.com/KirilsTurkins/latent-service-fabric/issues/148).
Do not overwrite evidence or invent a different component identity to bypass
expiry. A lost or post-rename failed response can leave a pending durable
candidate; reconcile with the repository's recovery/retry procedure.

To migrate a Phase 1 local catalog:

1. Stop its owner and preserve the existing root and original source/build inputs.
2. Repackage each selected capsule with complete pinned WIT and typed metadata.
   Produce an honestly observed build and required SBOM, then sign and attest
   the exact final package using separately approved publisher/builder keys.
3. Configure a fresh enforced catalog with complete current policies,
   revocations and explicit tenant-to-publisher authorization.
4. Submit the full package and evidence through authenticated admission, then
   apply deployments to its accepted release identities.

Version-1 local completion records are not auto-upgraded. Copying a receipt,
setting `admitted`, changing a marker, or omitting enforced configuration is not
a migration. Preserve the old root for history; the enforced boundary cannot
establish an observed build from a legacy digest alone. Catalog storage still
assumes a cooperating local filesystem owner: cryptographic package admission
does not protect against an administrator replacing the node executable,
approved trust configuration, or its entire storage history.
