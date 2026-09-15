# Exact web release admission

The directory catalog admits signed browser and SSR packages using independent
tenant-scoped publication references. This implements Phase 3 #225 and
[ADR-0038](../../adr/0038-admit-web-packages-with-componentless-publication-authority.md).
The shared HTTP listener (#229), renderer adapter (#233), observed Angular build
(#234), and public web management operations (#226) integrate this catalog API.

## Package profile

Use the existing [OCI package kinds](../protocol/package-format.md):
`browser-assets` for client/prerendered documents, or `ssr-package` for a renderer
and its client assets. Add the exact Asset-role JSON layer
`metadata/web-application.json`, described by the
[web application schema](../../schemas/web-application.schema.json).

The closed `lsf.web-release.v1` document contains `formatVersion: 1`, `profile`,
`assetsDigest`, `assets`, `routes`, and an optional `renderer`. The public asset
table is sorted by canonical URL path. Each entry names one `public/` layer and
its exact SHA-256, byte size and MIME type. A path cannot alias a second layer.
Both URL and layer suffix must match the supported MIME type. Package metadata,
SBOMs, build receipts and renderer code stay private, including Asset-role layers
outside this table.

Each route names one exact path and a `client`, `prerender`, or `server` mode.
Client/prerender routes name a declared HTML asset. Server routes require the
package's renderer and cannot name an unrelated document. Hostnames, tenant
selection, public authentication and deployment aliases are host policy; the
package cannot grant them to itself.

An SSR renderer names the package entrypoint's Renderer-role Wasm layer, its
digest and size, the exact public asset-tree digest, and a profile digest.
`renderer_profile_digest` binds the public WIT bytes, host ABI profile, engine
profile and renderer-specific restrictions. Native target/CPU configuration and
authenticated AOT identity remain separate preparation inputs.

`wasm-web-buffered-v1` validates the exact public async
`latent:web/application@0.1.0` export and the closed supported context imports.
Validation uses bounded structural and WIT checks without compiling or executing
untrusted Wasm. `angular-ssr-component-v1` now validates the composed public
adapter with separate finite binary-work ceilings and the unchanged public WIT
limits. The [installed renderer](../runtime/angular-renderer-runtime.md) requires
an explicit node profile. The original private synchronous qualification ABI
still fails the public interface check. Checked web publication is not yet a
callable capsule or deployment grant; #226 supplies that authority integration.

## Publisher, builder and inventory policy

`SupplyChainAuthority::verify_web` and `recover_web` use the same approved
publisher, builder, SBOM, tenant, generation, clock-lease and retirement owners
as capsule admission. Every request carries exact manifest/configuration/layers,
one publisher envelope and one builder envelope, with SBOM presence determined
by policy. Registry discovery does not substitute for these checks.

Web builder statements use the distinct predicate
`https://latent.dev/web-provenance/v1` and build type
`https://latent.dev/build/web-package-assembly/v1`. The builder policy must
explicitly approve that type and its source requirement. The
[web observation](../../schemas/web-build-observation.schema.json) and
[statement](../../schemas/web-provenance-statement.schema.json) describe
supplied-file assembly: `lsf-web-package-assembly`, recipe version 1,
`explicit-supplied-files`. Source origin remains operator asserted; the revision
is the supplied snapshot digest's hex, not a verified remote Git commit.

The observation authenticates the ordered output descriptors, count and byte
sum. Its output hash excludes only `package/sbom.cdx.json` and
`package/build-inputs.json` to avoid cycles. The exact final signed package binds
both excluded layers. Required materials are `source-snapshot`, `build-recipe`,
`toolchain-config` and `package-assembler`; names are unique and bounded.
Hermetic execution is false and dependency completeness is explicitly limited.
The verifier trusts an approved builder's assertions; the unsigned observation
and the signer API do not themselves observe a compiler. #234 supplies the
maintained observed Angular recipe. Reproducibility is a separately checked
builder assertion, never inferred from a repeated input list.

The [web admission receipt](../../schemas/web-admission-receipt.schema.json)
uses `lsf.web-admission.v1` and binds tenant, package, web manifest, public tree,
publisher/builder/evidence/SBOM identities and policy/time history. It contains
no `release` field. Historical receipts never confer permission; recovery checks
original structure/content before classifying current policy denial, then
reverifies the selected evidence against current trust.

## Exact selection and lifecycle

The trusted host authenticates and authorizes the scope and actor before calling
these `DirectoryArtifactRepository` methods:

| Method | Result |
| --- | --- |
| `publish_web_package` | Admit an exact package with expected generation zero. |
| `select_web_publication` | Retain one coherent, currently eligible association. |
| `read_web_asset` / `read_web_renderer` | Read the selected integrity-checked blob with retained capacity ownership. |
| `transition_web_publication` | Revoke or retire with an exact generation precondition. |
| `renew_web_evidence` | Replace evidence for the same retained package and advance its generation. |
| `reverify_web_publication` | Refresh a positive proof from selected raw evidence without rewriting history. |
| `web_publication_status` / `web_operation_status` | Inspect bounded historical status or a retained operation result. |
| `reclaim_uncommitted_web_content` | Collect bounded uncommitted packages and obsolete evidence revisions. |

Mutations require an operation ID and compare-and-swap generation. The host's
response preflight runs before staging or lifecycle writes. An exact retained
retry returns its original receipt; changing the request under that scoped ID
conflicts. Receipt retention is finite, so absence is not proof of rollback.
After an uncertain write, reopen and inspect operation/lifecycle state before
retrying. Terminal records cannot be revived by renewal, refresh or rollback.

Two authorized tenants can admit identical package bytes. Correcting an embedded
SBOM produces a separate immutable package/publication even when the renderer
is unchanged. Revocation, selected evidence and generations stay independent.
The legacy capsule indexes and RPC component fields keep their original meaning;
a browser package is never assigned a placeholder component.

Call `with_current` at response or renderer-start acceptance. It checks the
repository incarnation, captured generation, authenticated tenant and current
admission while holding the relevant synchronous fences. It is not a lock held
through an async network send. Already accepted work may complete after a later
revocation, retaining its real read/activation charges through cleanup. Dropping
the repository invalidates its held tokens even after a new owner reopens it.

`WebSelection::asset_url` returns
`/_lsf/assets/<publication:sha256:...>/<asset path>`. Changing a deployment does
not mutate this association. Old documents can fetch their original assets while
that publication remains eligible; revocation, retirement or expired authority
can deny a subsequent fetch. No historical URL grants perpetual public access.

Do not embed the package's own final ID in its stored HTML: that creates an
identity cycle. The serving integration must bind the selected asset base at
response time, or serve a pinned document with supported relative references.
Arbitrary HTML is not rewritten or sanitized by catalog admission; the renderer,
browser-serving and browser-defense tickets define those response semantics.

## Storage, bounds and recovery

Web publications share the catalog's OS root lock, single admission work slot,
publication writer, index budget and immutable blob store. No dormant web
application owns a process, thread, timer, listener, read buffer or renderer.

Before the first web payload, `ADMISSION_MODE` becomes
`lsf-enforced-admission-web-v2`. Older binaries accepting only v1 refuse this root
before shared-content recovery/GC. Unchanged capsule-only roots keep v1. This
adds a web storage profile without reinterpreting the existing capsule lifecycle
format 2 or the control-plane route catalog's separate format version.

Original exact files are linked under `web/publications/<publication hex>/`.
The bounded canonical `web/HEAD` stores sorted lifecycle records, original
admission-completion digests and finite operation receipts, followed by a
checksum. Each JSON line has its own typed and lexical bounds. Only the durable
head is authoritative. `.next` files are bounded, charged and never interpreted
as committed permission. Missing committed history or changed original bytes
fails closed, including when a publication is already revoked or proof-expired.

Renewed proof material lives in separately bounded `web/evidence/<digest>/`
directories. Current and terminal rows retain their original package and selected
evidence. Bounded explicit collection can remove uncommitted packages and
superseded/interrupted evidence; shared zero-reference blob collection remains
the existing catalog maintenance operation. A failed deletion retains its
conservative charge until recovery.

| Bound | Initial profile/default |
| --- | --- |
| Web manifest | 64 KiB; 128 public assets and 128 exact routes |
| Public asset | 8 MiB each; 16 MiB aggregate |
| Renderer input | 32 MiB; lower repository limits still apply |
| Catalog index | Shared 250,000 entries / 64 MiB conservative metadata; lifecycle entry limits also apply |
| Content storage | Shared 4 GiB conservative blob plus publication-link exposure |
| Recent web operations | 256 scoped receipts; lower lifecycle settings apply |
| Evidence revisions | 2 MiB each / 256 MiB aggregate by default, including interrupted revisions |
| Active web reads/selections | 32 owners / 64 MiB retained capacity across the repository |

These are explicit ownership ceilings, not total RSS or allocated filesystem
blocks. One bounded control operation may additionally hold its input, recovery
or replacement snapshot. Head replacement reserves old and next-file exposure.
Selection and blob reads charge their metadata and buffer before allocation;
copied eligibility tokens retain the lease until the last consumer releases it.
Asset reads anchor the stored header to the retained lifecycle completion and
verify the selected blob. Admission and restart verify the full package.

The tests cover real publisher/builder/SBOM admission, browser and public async
SSR packages, cross-tenant/package coexistence, private-layer denial, shared
quotas, retained read leases, preflight rejection, exact retries, evidence renewal
and collection, revocation, corrupt/missing history, and failures on both sides
of the durable head commit. The tiny public SSR fixture checks compatibility;
it does not claim Angular runtime integration or a performance benchmark.

CI also pushes both package kinds and all three evidence kinds through the owned
TLS/authenticated OCI registry, discovers and retrieves digest-pinned evidence,
admits under real approved policy, moves a mutable tag and reopens the catalog.
Registry retention tags keep the test's remote manifests available; a digest
alone does not compel a registry to retain untagged content. Admitted catalog
content remains locally retained independently of registry tag changes.

After `tools/validate_contracts.sh` builds the public fixture, run:

```sh
python3 tools/run_oci_registry_tests.py \
  --web-admission-component target/capsules/web-contract/component.wasm
```

The runner uses a disposable bounded registry and fresh public test credentials.
The schema fixtures are deliberately synthetic; Rust/OCI tests verify actual
signatures and the built public web component. No load benchmark is required.
