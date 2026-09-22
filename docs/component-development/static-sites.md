# Package an observed static site

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

The profile bounds are 120 public assets, 8 MiB per asset, 16 MiB in aggregate,
232 bytes per relative path, a 64 KiB input descriptor, and three to eight
nonempty observation files of at most 1 MiB each. Exactly one source observation
and at least one toolchain and build observation are required. Supported media
are HTML, JavaScript, CSS, JSON, text, SVG, PNG, JPEG, WebP, ICO and WOFF2. Explicit
media declarations must agree with the supported extension mapping.

Observation references retain their digest and size in private package metadata;
their contents are not copied into the public inventory. They are honestly
marked as operator supplied: capture does not attest that a compiler ran or that
its output is reproducible. The generated SBOM input inventory associates every
captured output with its exact bytes and declares incomplete dependency coverage.
Publisher and builder trust, provenance, SBOM admission and tenant publication
identity remain requirements of the existing
[package and supply-chain workflow](packaging.md).

## Choose the routing policy before signing

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

The adapter and package round-trip are implemented. The maintained Angular CSR,
static-generator and end-to-end deployment/browser receipts for issue #497 are
still being qualified; this page does not claim their completion.
