# Package an observed static site

For actual Angular/PrimeNG and bilingual Docusaurus examples, follow
[Serve Angular and Docusaurus sites](../how-to/serve-angular-and-docusaurus.md).

To release your existing frontend output with installed binaries and Node.js,
follow the [frontend release guide](../operations/static-release-workflow.md).
It covers organization signing, verification, OCI transfer, publication,
GET/HEAD promotion and rollback without a Rust toolchain. This page explains
the inventory and routing inputs used by that workflow.

`tools/static_site.py` captures an explicit finite file map from an existing
framework build. It writes ordinary `browser-assets` package inputs and a
`static-site-v1` web manifest. Compilation, package assembly and deployment are
separate steps. Neither this adapter nor `latent package build` runs npm scripts.

The adapter accepts this closed input shape (the digest strings below must be
replaced by the SHA-256 digests of the actual observation files):

```json
{
  "formatVersion": 1,
  "profile": "static-site-input-v1",
  "name": "orders-site",
  "version": "1.0.0",
  "assets": [
    {"path": "/index.html", "source": "index.html"},
    {"path": "/assets/main.js", "source": "assets/main.js"},
    {"path": "/assets/main.css", "source": "assets/main.css"}
  ],
  "entryDocument": "/index.html",
  "directoryIndex": {"mode": "disabled", "document": "/index.html"},
  "fallback": {"mode": "spa", "document": "/index.html"},
  "excluded": ["server/main.mjs", ".env"],
  "observations": [
    {"kind": "source", "source": "source.json", "digest": "sha256:<source-observation>"},
    {"kind": "toolchain", "source": "toolchain.json", "digest": "sha256:<toolchain-observation>"},
    {"kind": "build", "source": "build.json", "digest": "sha256:<build-observation>"}
  ]
}
```

```sh
python3 tools/static_site.py --build-output target/site-build \
  --input static-site.json --output target/site-inputs
latent --output json package build \
  --source target/site-inputs/package-source.json \
  --input-root target/site-inputs \
  --sbom-inputs target/site-inputs/sbom-inputs.json \
  --output-dir target/site-package --validate-web
```

The output directory must be new and outside the build tree. Only the named
files become public; the adapter never discovers files recursively. Input paths
are relative portable paths, public paths start with `/`, and both are checked
for aliases and case collisions. Symlinks and reparse points, traversal, the
reserved `/_lsf/` namespace, unsupported media, hidden files, source maps and
obvious server/private output are rejected before writing package inputs.
Exclusions cannot also be public assets. This is an explicit publication
allowlist, not a secret scanner: review the selected bytes before signing.

The profile bounds are 252 public assets, 8 MiB per asset, 16 MiB in aggregate,
232 bytes per relative path, a 256 KiB input descriptor, and three to eight
nonempty observation files of at most 1 MiB each. Exactly one source observation
and at least one toolchain and build observation are required. Supported media
are HTML, JavaScript, CSS, JSON, XML, text, SVG, PNG, JPEG, WebP, ICO and WOFF2. Explicit
media declarations must agree with the supported extension mapping.

The web manifest is also bounded to 256 KiB. Public paths count independently
even when their content hashes match. The 252-file ceiling reserves four of the
package format's 256 layers for web/capture metadata, its SBOM and build-input
receipt. Extra custom package layers consume that same total budget. Native
admission uses the same logical asset count, with a separately bounded 256-slot
allocation allowance that is charged to retained metadata.

Count and byte-limit diagnostics identify the bound, actual value and maximum.
Reduce the complete reviewed output or use explicitly separate publications
when a limit is exceeded; the adapter never silently drops files. The maintained
generator builds and publishes a complete 250-file English/German documentation
fixture at both root and mounted paths. See the
[capacity decision](../../adr/0045-bound-larger-static-documentation-inventories.md)
for the coupled package, SBOM, memory and serving limits.

## Sitemaps and fonts

Include your generated `sitemap.xml` and sitemap index in the explicit asset
inventory. `.xml` files use exactly `application/xml`, with `nosniff`, the normal
size limits and the same GET/HEAD/conditional-response behavior as other assets.
LSF serves the admitted bytes without parsing XML or resolving entities; it does
not generate a sitemap or infer the site's public origin. Set the generator's
public URL and mounted base path before building.

For font-based PrimeIcons applications, prepare the pinned WOFF2-only stylesheet
**before** the Angular or documentation build:

```sh
npm install --save-exact primeicons@8.0.1
python3 tools/static_fonts.py --primeicons node_modules/primeicons --output src/primeicons-woff2
```

The output directory must be new. The helper preserves the icon classes and
license, replacing the font declaration with a single local WOFF2 reference.
Include `src/primeicons-woff2/primeicons.css` in Angular's `styles` list, or use
that stylesheet as a Docusaurus `customCss` input. Remove the original
`primeicons/primeicons.css` import, so the framework bundler does not emit its
WOFF, TTF and EOT alternatives. The framework can hash/copy the WOFF2 asset in
its normal build. Keep the resulting CSS, font and license in the reviewed
public inventory. This recipe targets the font-based package; SVG component
icon libraries do not need font preparation.

PrimeIcons 8.0.1 ships under the [PrimeUI licensing terms](https://primeui.dev/licenses/community),
replacing the MIT notice shipped with 7.0.0. The helper copies the package's
`LICENSE.md` verbatim to the generated `LICENSE.txt`; that notice remains part
of the published asset inventory.

Use the same prepared output for every hosting route you compare. Review
deployment-only files such as `.nojekyll` separately and list deliberate
exclusions; never enable arbitrary hidden files or silently discard referenced
fonts. The maintained generator/browser check loads an actual WOFF2 icon and
checks that no legacy font URL is requested.

Observation references retain their digest and size in private package metadata;
their contents are not copied into the public inventory. They are honestly
marked as operator supplied: capture does not attest that a compiler ran or that
its output is reproducible. The generated SBOM input inventory associates every
captured output with its exact bytes and declares incomplete dependency coverage.
Publisher and builder trust, provenance, SBOM admission and tenant publication
identity remain requirements of the existing
[package and supply-chain workflow](packaging.md).

## Choose the routing policy before signing

Editors and schema-based CI can validate `metadata/web-application.json` with
the [web application schema](../../schemas/web-application.schema.json).
It supports both a CSR entry route and a generator's empty `routes` list with
`staticRouting`. Routing fields and fallback modes are closed: SPA fallback
requires a document, while `none` forbids one. Static routing cannot accompany
a server renderer.

Also run `latent package build --validate-web` and `latent package inspect`.
Native validation checks the actual package kind, digests, asset bytes and that
each routing document names an admitted HTML asset. JSON Schema validates the
document's structure; it cannot verify those package associations or establish
publisher trust.

For Angular CSR, keep directory indexes disabled and select the admitted HTML
entry as the SPA fallback. For static-generator output, choose `redirect` with
`/index.html` as the directory-index document and `{"mode":"none"}` as fallback.
Include `/guide/index.html` explicitly to serve `/guide/`. A request to `/guide`
then redirects to `/guide/` with status 308; `/guide/missing` remains 404.

The operator controls the host and mount in the static HTTP trigger. The signed
web manifest controls entry, directory indexes and fallback. Changing any routing
policy changes the checked manifest and package identity even when the public
asset bytes are unchanged. Do not edit routing metadata after signing.

Compared with nginx `try_files $uri $uri/ /index.html`, LSF resolves an exact
admitted route or asset, then an optional directory index, then a
navigation-qualified SPA fallback. Script, style, image and API/JSON requests
do not receive HTML fallback. There is no rewrite language, directory listing,
arbitrary filesystem root or framework development server. See the exact
[HTTP and cache contract](../immutable-browser-assets.md).

Routed aliases revalidate; immutable publication URLs retain their exact
publication identity and cache policy. A trigger update is an explicit atomic
control operation. Rollback requires a new operation selecting a currently
eligible publication. Cached bytes never restore revoked authority. Use content
hashed asset names so stale HTML cannot silently load a different version at the
same name; any intentionally retained assets must be present in the selected
publication's signed inventory.

## Build and qualify the maintained references

This section is for contributors testing LSF itself. Application delivery uses
the [frontend release guide](../operations/static-release-workflow.md) and your
organization's signing identities.

`examples/static-sites/csr` is an Angular client-only application with a home
view, a lazy `/orders/:id` route, CSS and visible A/B version markers. Its build
uses the pinned Angular compiler and linker in `examples/renderer-profile`;
the application contains no server renderer. `examples/static-sites/generator`
contains two finite pages representative of a static generator's directory
output. The generator is a conformance fixture, not a Docusaurus runtime.

On the qualified Linux toolchain, build the CLI/node and install the locked
JavaScript toolchain before running the maintained reference build:

```sh
cargo build --locked -p latent -p latentd --all-features
npm ci --prefix examples/renderer-profile --ignore-scripts --no-audit --no-fund
mkdir -p target/static-conformance
objcopy --strip-debug target/debug/latent target/static-conformance/latent
objcopy --strip-debug target/debug/latentd target/static-conformance/latentd
python3 tools/build_static_sites.py \
  --cli target/static-conformance/latent \
  --toolchain examples/renderer-profile \
  --output target/static-conformance/builds
LSF_STATIC_BUILDS="$PWD/target/static-conformance/builds" \
LSF_STATIC_FIXTURE_ROOT="$PWD/target/static-conformance/fixture" \
  cargo test --locked -p latentd --test phase3_static_fixture --all-features \
  -- --ignored --exact export_actual_static_site_fixtures
python3 tools/run_static_site_workflow.py \
  --cli target/static-conformance/latent \
  --node target/static-conformance/latentd \
  --fixture target/static-conformance/fixture \
  --toolchain examples/renderer-profile \
  --chrome "$(command -v google-chrome)" \
  > target/static-conformance/receipt.json
```

The build output directory must be new. Docker supplies the owned, pinned TLS
OCI registry; an explicitly supplied `--registry-origin` and `--registry-ca`
can select an existing test registry. The fixture exporter signs the actual
four packages using test publisher/builder keys and a finite test policy.
Export fresh evidence immediately before the workflow so its admission proof
remains current. These fixture keys and policy are local conformance inputs;
operator deployments use their own publisher, builder and tenant policy.

The build keeps source, toolchain, generated-byte and package observations
separate. It records the supplied-file assembly profile, incomplete declared
dependency coverage and `reproducibility: not-checked`. It does not claim a
hermetic or independently reproduced framework build. B explicitly retains A's
content hashed public assets in B's signed inventory so an A document already
loaded during cutover can finish loading its original scripts.

The workflow inspects and verifies every package, pushes it to OCI, pulls by
exact package digest, compares all package/evidence bytes and publishes the
pulled package. It then uses the existing `trigger` management commands and
recovers each operation receipt by operation ID. Real Chromium checks deep
links, router navigation without a document reload, refresh, lazy scripts,
CSS, CSP, missing scripts/API requests, root and `/docs` generator mounts and
canonical 308 redirects. It holds A's script request across a committed B
trigger update and proves both the completed A view and a fresh B view.

The same run performs an explicit rollback to A, switches to B again, revokes
A, rejects conditional reads of A and refuses a new rollback to revoked A.
It checks foreign publication denial and paginates the actual audit API to
associate committed operations with exact static identities. Initial, dormant
and final node inventories retain zero granted cells, active activations and
compiled images; request owners return to baseline and the actual node joins
its HTTP, asset, compiler and control owners during shutdown. Cold and warm
request timings are bounded observations, not throughput or CDN benchmarks.
The [retained local qualification](../evidence/static-site-local-2026-09-22.json)
records Chromium 153, 73 actual CLI processes, ten committed static operations
across 15 audit pages, and the exact CLI/node and package digests. The CI receipt
is produced independently from its checked-out source and built executables.

CI runs this workflow inside the existing conditional renderer/browser job
and retains `static-site-receipt.json` with the other delivery receipts. The
adapter's adversarial tests and the real HTTP tests additionally cover path
aliases, private outputs, symlinks, saturation, corrupt assets, revocation
between selection and delivery and blocking-read ownership during shutdown.

## Apply a static publication and recover an operation

After verifying and publishing your signed package, put the returned exact
publication ID into a trigger such as:

```yaml
apiVersion: latent.dev/v1alpha1
kind: HttpTrigger
metadata:
  name: orders-get
  tenant: customer-a
spec:
  target:
    kind: static-web
    publication: publication:sha256:<admitted-publication-id>
  configuration:
    profile: static-site-v1
    scheme: https
    host: customer-a.example.com
    path: /
    pathMatch: prefix
    method: GET
```

Use the authenticated operator profile and the generation/state version from
`latent trigger get orders-get` as explicit compare-and-set preconditions:

```sh
latent trigger apply orders-get.yaml --operation-id orders-to-b \
  --expected-generation <current-trigger-generation> \
  --expected-state-version <current-state-version>
latent trigger operation orders-to-b
```

A new trigger has generation zero. Create a separate named HEAD trigger with
`method: HEAD` when HEAD is required; unrelated application triggers do not
inherit GET behavior. For the generator mounted at `/docs`, build its public
links with that mount and use `path: /docs` with `pathMatch: prefix`.

If a connection fails after submission, query the original operation ID before
deciding whether to retry. A cutover changes the exact publication in a new
trigger operation using current preconditions. Rollback follows the same
procedure and selects a still-eligible prior publication; a revoked publication
must remain denied even when its bytes are cached. Inspect the returned target,
trigger generation, publication, web manifest and asset digests before treating
the operation as complete.
