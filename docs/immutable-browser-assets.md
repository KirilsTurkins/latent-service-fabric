# Immutable browser asset HTTP profile

Issue #231 adds browser asset delivery to the existing standalone HTTP ingress. It is a sibling of capsule invocation, not a renderer function. The supported serving profile is Linux x86-64, matching the qualified standalone runtime. An enabled HTTP ingress owns one asset service for the node. No application-specific listener, worker, renderer, Wasmtime store, or JavaScript heap is created for an asset request or an idle publication.

## Exact publication and public asset selection

Use the URL returned by the admitted web selection's `asset_url` method. Its shape is:

```text
/_lsf/assets/publication:sha256:<publication-id>/<manifest-public-path>
```

The publication identity binds the tenant and package. The existing HTTP credential and authority checks run first. The authenticated principal supplies the tenant scope; neither a URL digest nor cached bytes grant access. A fresh `WebSelection` resolves the exact publication, and only an entry in its validated public asset manifest may be served. Package metadata, evidence, renderer code, private layers, and unlisted files are not exposed. A public path is not a path under the node's filesystem.

The reserved namespace is dispatched before HTTP trigger lookup and activation reservation. Misses, rejected methods, malformed asset locators, cache hits, HEAD, and conditional requests do not fall through to a renderer. The reserved asset endpoint itself has no directory indexes, SPA fallbacks, query-string aliases, percent-encoded aliases, or double decoding. Dot segments, encoded separators, backslashes, and noncanonical package paths are rejected.

The same publication identity cannot silently select another package. Publishing a replacement produces a different URL; an old URL continues to identify the old bytes while that exact publication remains selectable. Current lifecycle and policy permission is checked again at response acceptance, after reading/verifying the representation and immediately before beginning output. Revocation or a stale selection causes rejection even when the bytes are cached or the conditional result would otherwise be 304.

Browser caching is not a revocation channel: an origin cannot recall a representation already stored by a client. This profile uses private caching and varies on authorization to prevent shared/inter-credential cache reuse, while retaining immutable content semantics. The origin rechecks admission whenever a request actually reaches it.

## Signed static-site routing metadata

A BrowserAssets publication may additionally carry a closed `staticRouting`
record inside its signed web application manifest:

```json
{
  "profile": "static-site-v1",
  "entryDocument": "/index.html",
  "directoryIndex": "redirect",
  "directoryIndexDocument": "/index.html",
  "fallback": {
    "mode": "spa",
    "document": "/index.html"
  }
}
```

Every document path is canonical, listed in the same publication's public asset
manifest and has media type `text/html`. `directoryIndex` is only `disabled`
or `redirect`; fallback is only `none` or `spa`, and `spa` requires its
document. The record is rejected on SSR packages. Unknown fields are rejected,
so it cannot smuggle hostnames, tenants, credentials, filesystem paths, proxy
destinations or mutable external URLs into publication authority.

The record participates in the web-manifest/package digest and admission proof.
It is not an external host/path rule. A `static-web` HTTP trigger supplies that
external mount and stores the exact publication plus manifest/assets/generation
identity. The shared trigger matcher keeps exact/prefix precedence and conflict
rules; a stale winning static route fails closed.

This metadata does not change the reserved `/_lsf/assets/*` endpoint described
above. Direct immutable asset URLs still have no directory-index or SPA-fallback
behavior. Site-level entry/index/fallback behavior is consumed only by the
shared static-serving runtime after a first-class static target has been
selected. No filesystem root, directory listing, arbitrary rewrite/redirect,
proxy, SSR, weighted backend or per-site cache is implied.

## Routed static sites

A `static-web` HTTP trigger selects one admitted browser publication and one
canonical mount. The shared ingress authenticates the request and selects the
winning exact/prefix matcher before resolving any package path. For example,
`/docs/guide/?tab=history` under mount `/docs` has site path `/guide/`. `/docs2`
does not match that mount. Queries remain request data and do not enter asset
lookup. The resolver never decodes URLs again or probes a filesystem directory.

Resolution follows this order:

1. Exact signed client/prerender `WebRoute`.
2. Exact admitted public asset.
3. Configured directory index, when enabled.
4. Configured SPA document, for an eligible navigation only.
5. Empty 404 with `Cache-Control: no-store`.

With `directoryIndex: redirect` and `directoryIndexDocument: /index.html`,
`/docs/guide/` selects `/guide/index.html`. If those checked bytes exist,
`/docs/guide?tab=history` returns an empty 308 with root-relative
`Location: /docs/guide/?tab=history`. The redirect verifies the selected index
and its current authority too. Forwarding headers cannot set the location.
Disabling directory indexes disables this slash behavior. `entryDocument`
identifies package input; it does not create an implicit route. A CSR package
with indexes disabled should include an explicit signed `/` route to its entry
document as well as its optional navigation fallback.

If any Fetch Metadata is present, SPA fallback requires both
`Sec-Fetch-Mode: navigate` and `Sec-Fetch-Dest: document`. The existing
[same-origin browser policy](security/browser-boundary.md) still applies.
Without Fetch Metadata, fallback requires an explicit nonzero `text/html`
range in `Accept`. Missing `Accept` and `*/*` alone do not qualify. No other
HTML media type is supported. Script/style/image/font/manifest destinations
and JSON/API misses receive 404 even when fallback is enabled; filename
extensions do not decide navigation eligibility.

Static content negotiation accepts at most 16 media ranges in 2,048 bytes.
It supports exact media types, type wildcards, `*/*`, and at most eight unique
parameters per range, including one `q` parameter with up to three fractional
digits. Token and quoted parameter values are bounded and validated. A range
with media parameters does not match an unparameterized representation; valid
parameters in browser navigation headers therefore do not make the request
malformed. A more specific matching range overrides a wildcard, including
`text/html;q=0`. Duplicate ranges/headers/parameters and malformed qualities
receive 400; excess ranges/bytes receive 431. A resolved
representation excluded by `Accept` or identity encoding receives 406.

Create separate GET and HEAD trigger matchers. A missing HEAD application
matcher does not invoke its GET application. Other methods receive 405 when
an eligible static GET/HEAD matcher owns that path; a matched application
method retains its existing behavior. Static GET/HEAD bodies receive 400.

Routed HTML and assets carry `Cache-Control: private, no-cache` and the same
strong representation ETag as immutable assets. They additionally vary on
`Accept` and the four supported Fetch Metadata fields. Immutable URLs keep
their one-year private immutable policy. GET, HEAD and 304 each require current
publication authority; cached bytes grant none. A trigger update affects later
selections. An already captured request keeps its original exact publication,
while revocation of that publication denies acceptance. A stale specific
matcher never falls through to a broader one.

The resolver uses a 240-byte stack buffer for index derivation and at most
8 KiB for a canonical redirect location, within the existing 4 MiB HTTP
exchange reservation. It uses the existing node-wide asset cache and four
nonblocking read/output permits. No activation request, scheduler admission,
renderer, cell, Wasmtime store, per-site task, listener or cache is created.
Corruption/impossible checked associations produce 502; stopped/exhausted
owners produce 503. Neither becomes a fallback document. Disconnects and
deadlines retain the actual blocking read charge until that owner retires.

### Migrating a conventional static host

The supported counterpart to nginx `try_files $uri $uri/ /index.html` is an
explicit admitted asset inventory, optional checked directory indexes, and
navigation-qualified SPA fallback. A static generator normally enables
directory indexes and disables fallback; Angular CSR normally disables indexes
and enables `/index.html` fallback. Host/mount/method remain operator trigger
policy; document routing remains signed package metadata. Regex rewrites,
directory listings, arbitrary filesystem roots, reverse proxying, custom
error-page fallbacks and transparent compression are outside this profile.

The `static_tests` real-node suite covers root/non-root mounts, exact route
precedence, queries, redirects, hostile paths, missing assets, methods,
negotiation, GET/HEAD/304, cutover, rollback, delete/recreate, revocation,
concurrent cache use, corruption, read saturation, disconnect and shutdown.
It checks zero begun activations/activation observations and zero created
Wasmtime stores, then verifies drained shared ownership. These bounded checks
are runtime conformance, not a framework/browser or performance qualification.

## HTTP behavior

GET returns the verified representation with the manifest's validated `Content-Type`, its exact `Content-Length`, and `X-Content-Type-Options: nosniff`. HEAD returns the same representation metadata without a body. Neither method trusts a declared length or digest without verifying the selected bytes, including on a cache hit.

Successful responses carry:

```text
Cache-Control: private, max-age=31536000, immutable
Vary: Authorization, Accept-Encoding
Accept-Ranges: none
ETag: "identity-sha256-<representation-identity>"
```

The strong ETag is domain-separated over the identity encoding, content digest, length, and media type. `If-Match` uses strong comparison and is evaluated before `If-None-Match`, which uses weak comparison for GET and HEAD. Both support bounded tag lists and `*`. A failed `If-Match` returns 412. A matching `If-None-Match` returns 304 with no body and no `Content-Length`. HEAD never returns a body, including on an error.

Only GET and HEAD are supported; other methods receive 405 with `Allow: GET, HEAD`. Asset requests must not contain a request body. Errors use an empty response and `Cache-Control: no-store`; there is no browser error document or renderer fallback. Missing manifest entries return 404. Bad bytes or unavailable catalog content return 502; exhausted capacity or a stopped asset service returns 503. Existing authentication and canonical-target validation can reject a request before asset dispatch.

### Explicitly unsupported features

This initial profile does not implement byte ranges. It ignores `Range` and `If-Range` and serves the full representation with 200, unless an independent supported precondition determines a different status. It does not send 206 or claim range support. Multi-range input cannot create additional read/output owners.

Only the identity representation is served. There is no gzip/Brotli negotiation, on-demand compression, archive extraction, or decompression. Requesting gzip or Brotli does not prohibit identity by itself; explicit exclusion of identity (including an applicable `*;q=0`) returns 406. The bounded parser validates quality values instead of guessing. No `Content-Encoding` header is emitted. Future compressed variants require separately admitted identities and explicit compressed/decompressed byte limits; this profile must not transparently decompress package data.

Modification-date preconditions are not implemented: the service has an immutable content identity, not an authoritative Last-Modified clock. `If-Modified-Since` and `If-Unmodified-Since` are ignored, and no Last-Modified is emitted. No new anonymous/public-authentication mode, CDN cache policy, origin routing API, or mutable deployment-alias endpoint is introduced.

## Shared storage and integrity

Durable bytes remain in the catalog's existing digest-addressed shared blob store. This service does not introduce a second durable content cache. The catalog's committed publication history owns content retention; retiring an association does not let a cache become authority for another association.

At startup, the source walks the catalog's canonical directory using no-follow directory opens and retains its directory handle. Reads open the shared blob directory and the typed digest's single filename relative to that handle, again with no-follow flags. Renaming/replacing the root pathname cannot redirect the retained handle. Symlinks and special files are rejected. Regular hard links used by the catalog are supported.

A read checks the file type and exact declared length, reads only into a pre-reserved bounded buffer, rejects unexpected trailing bytes, and rechecks length. The entire representation's digest is verified before cache insertion or any successful response. Cache hits recheck their length and digest. A corrupt cached buffer is evicted and the same authorized digest is refetched once; a corrupt source fails closed. Cache repair does not re-admit, select a substitute package, or bypass the fresh selection's acceptance check.

## Ownership and limits

The asset service's limits are node-wide, not multiplied by the number of deployed applications:

| Owner | Limit |
| --- | --- |
| Concurrent read/output owners | 4 |
| Live shared asset payload and entry reservations | 32 MiB |
| Cached entries | 128 |
| Individual representation | Existing web manifest ceiling, 8 MiB |
| Cache entry accounting charge | 512 bytes, in addition to payload |
| Individual socket write chunk | 16 KiB |
| Each supported conditional/encoding header | 2,048 bytes |
| Entity tags / encoding entries per header | 16 |

These asset reservations are **additional to** the configured ingress connection, exchange, header, body, TLS, and kernel socket limits. A request retains its existing ingress exchange owner while the asset path runs. `http.assets` in the existing HTTP snapshot reports the separate asset ceilings, active owners, retained bytes, cache entries, hits, misses, corruption detections, and capacity rejections. The parent HTTP buffer fields continue to describe transport buffers, not an aggregate of all node memory.

The shared read gate is nonblocking: no asset wait queue or per-publication worker is created. A work permit is acquired before a blocking file-read/hash task is submitted. The permit remains with the actual task, then with the prepared response, until owned buffers and selection references have been released. Output uses the existing absolute request/connection deadlines and write timeout, including bounded flush/shutdown handling. EOF, write-half-close, premature pipelining, deadline expiry, and forced connection cancellation stop delivery.

Canceling a browser connection cannot cancel an already running blocking filesystem call. Such work remains charged until it actually completes, even after its join handle has been dropped. Shutdown stops new asset work, waits for actual work/output owners, then clears the cache. A deadline-expired join reports failure rather than pretending its resources were freed.

Payload reservations live with reference-counted buffers, not cache slots. Eviction or cache clear cannot release bytes still pinned by a writer. Reservation failure happens before allocation/read; pinned-buffer pressure yields bounded 503 rejection. Cached buffers carry no tenant grants, `WebSelection`, renderer state, or long-lived publication workers.

Cache bookkeeping contention bypasses lookup and optional residency. The request
still reserves its complete payload charge before reading and verifying the
captured source. It neither waits for the cache lock nor acquires extra capacity;
read-gate or memory exhaustion still returns 503 before unowned work begins.

Mandatory catalog admission remains nonqueueing: concurrent selection may
return a bounded 503 before asset dispatch. This response has an empty body and
`Cache-Control: no-store`; it never becomes an SPA document. A subsequent
explicit GET can succeed after the owner releases its reservation.

## Regression coverage and validation

Run the targeted checks with the repository's pinned toolchain:

```sh
cargo fmt --all --check
cargo check -p latentd --all-targets --all-features --locked
cargo test -p latentd --lib --all-features --locked standalone::http::assets
cargo test -p latentd --lib --all-features --locked standalone::http
cargo clippy -p latentd --all-targets --all-features --locked --no-deps -- -D warnings
```

The asset tests cover exact URL parsing, bounded preconditions/encoding negotiation, eviction with pinned bytes, cache corruption/refetch, source corruption, symlink and root substitution, release replacement, GET/HEAD/304/error framing, current policy/revocation checks, tenant isolation, capacity rejection, and disconnect while a blocking owner is deterministically held. Real socket tests use a node with no capsule, renderer, deployment, or HTTP trigger, and verify zero active activations and live Wasmtime stores alongside drained transport/read ownership.

The storage tests inject an explicitly non-cryptographic test authority; they do not stand in for signature verification. Signed browser/SSR admission and cryptographic policy recovery remain independently covered by the existing package and policy tests. All asset tests are registered in the ordinary `latentd` test suite; no permanent issue-specific CI workflow is required.

## Integration with the shared response cache

The September 19 integration merges development at
`420bb0d451d6b9de26ef3207aa93deb7681c75ec` (PR #335 / issue #232) into
the original asset branch. The two caches remain independent node-wide owners:
immutable asset bytes do not become rendered response entries, and neither
cache holds an admission grant. HTTP snapshots expose both sets of accounting;
drain stops both admissions, and a clean shutdown requires both to be empty.

The added real-socket coexistence regression enables the existing public-origin
response-cache profile, serves a verified asset without any renderer or route,
checks that only the asset cache retains bytes, then verifies both owners stop
and report clean shutdown. The existing response-cache tests remain responsible
for fill, revocation and personalized-request bypass behavior.

The overlapping resource-fixture CI repair uses development's single maintained
`objcopy`/identity/launch block and its real-ELF regression tests unchanged. The
superseded asset-branch helper and duplicate documentation are removed; there is
no second staging pipeline or resource-profile limit change.

Focused integration validation on September 19 used Rust 1.97.1 and Linux
x86-64 in an isolated 2-CPU, 8-GiB validation container (debug information off):

| Check | Observed result |
| --- | --- |
| `cargo fmt --all --check` | Passed on the Windows worktree |
| `cargo test -p latentd --lib --all-features --locked standalone::http` | 24 passed, 6 explicitly component-gated tests ignored |
| `LSF_WEB_COMPONENT=... cargo test -p latentd --lib --all-features --locked actual_http_component -- --ignored --test-threads=1` | All 5 passed against a freshly built and validated public web component |
| `cargo clippy -p latentd --all-targets --all-features --locked --no-deps -- -D warnings` | Passed |
| Resource binary, resource gate/clock and Cargo-artifact Python regressions | All 42 passed, including real ELF preparation |

The Angular-component-specific ignored test was not rerun for this narrow
integration. These observations do not replace exact-head PR CI or constitute
a production browser/SSR qualification; issue #235 covers the browser boundary.
