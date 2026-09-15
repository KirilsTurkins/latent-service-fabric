# ADR-0038: Admit web packages with componentless publication authority

## Status

Accepted; Phase 3 #225. Extends ADR-0007, ADR-0010, ADR-0024, ADR-0027,
ADR-0035 and ADR-0037. Capsule component fields and receipts keep their existing
meaning. The shared ingress, web management and renderer adapters remain their
own integration steps (#229, #226 and #233).

## Context

Browser packages have no executable component. An SSR package contains both a
renderer and client assets; a component digest cannot identify or authorize that
entire association. Treating all Asset-role layers as public would also expose
private package metadata, build inputs and inventory.

Package integrity, builder/publisher approval, tenant admission and current
permission are separate decisions. An old HTML document must not silently fetch
another deployment's asset tree, and immutable URLs must not defeat revocation.

## Decision

Use the existing `browser-assets` and `ssr-package` OCI kinds. The closed
`lsf.web-release.v1` metadata at `metadata/web-application.json` identifies the
explicit public asset table, exact document routes, and optional renderer with
its compatibility digest. Only named public entries under `public/` are served.
The complete package binds private metadata and embedded SBOM content as well.

Admit a package using `PublicationRef::package(tenant, packageDigest)`. Web
admission has separately versioned bindings, receipts and lifecycle records with
no synthetic `ReleaseDigest`. The same configured supply-chain authority checks
publisher, builder, SBOM, tenant, policy generation and trusted clock state.
Default implementations of the additive web authority methods deny admission.

Use a distinct web provenance predicate and explicitly approved build type for
supplied-file package assembly. Its ordered output descriptor digest omits only
the build-input receipt and generated embedded SBOM, avoiding identity cycles;
the signed final package authenticates both. This does not claim Angular
compilation, source-origin authentication, hermetic execution or reproducibility.
The observed Angular compiler recipe remains #234.

Store web publications inside the concrete directory catalog, under its OS root
lock, common admission work slot and publication writer. Original payloads use
the same immutable shared blobs and combined index/storage ceilings as capsules.
A distinct web lifecycle head commits exact original admission completion,
generation, selected evidence and finite operation receipts. Evidence renewal
stores a bounded separate revision; it never overwrites the original package.

Before any web payload is published, durably promote `ADMISSION_MODE` to
`lsf-enforced-admission-web-v2`. Older readers recognize only v1 and refuse the
catalog before shared-blob recovery or collection. Existing capsule-only roots
remain readable without a web upgrade. Missing committed history fails closed;
empty interrupted initialization does not create permission.

Select the entire immutable association through a sealed web eligibility token.
Every asset response or renderer start must recheck that token's repository
incarnation, tenant, generation and current admission under the shared fences.
An accepted start may finish after a later revocation, retaining its actual
resource charges until cleanup. Revoke and retire are terminal. Evidence renewal
invalidates held generations; explicit proof refresh cannot revive terminal rows.
Uncertain lifecycle writes close held and fresh web uses until restart recovery.

An immutable asset URL identifies the original scoped publication and asset
path. Switching or rolling back a deployment selects a different exact
publication; it does not rewrite old URLs. The original URL remains usable only
while its original publication remains eligible. Builders must not embed their
own package ID into stored package bytes, which would create a digest cycle.

## Consequences

Browser packages, corrected inventory packages, and authorized tenants sharing
identical renderers coexist with independent lifecycle authority. Content/code
deduplication does not share tenant grants. Selection and blob-read leases retain
their charges across copied tokens and asynchronous response ownership.

The first installed admission profile checks the exact public async
`latent:web/application@0.1.0` interface and supported context imports without
compilation or guest execution. Recognizing the Angular profile's identity does
not install its adapter: the private synchronous qualification component from
#224 remains incompatible until #233 supplies the public adapter.

The [web admission contract](../docs/reference/web-release-admission.md) records
the bounds, lifecycle policy, compatibility marker and host API. These are
catalog capabilities; a listener, SDK endpoint or observed Angular compiler is
not implied by adding a package profile.
