# ADR-0049: Scope cross-origin assets to explicit publications

- Status: Accepted design; native implementation pending
- Context: first integration feedback #627

## Decision and availability

Introduce a separate opt-in `cross-origin-assets-v1` profile for admitted static
assets. The current `same-origin-v1` profile remains the default. This ADR and
the executable browser experiment establish feasibility; they do **not** enable
CORS in released or development nodes. The [native implementation follow-up](https://github.com/KirilsTurkins/latent-service-fabric/issues/660) must pass
the same cases against actual signed publications and native ingress.

An operator grant binds one canonical HTTPS serving authority, an existing
tenant, an exact immutable publication ID, an exact HTTPS caller-origin list and
a credentials mode. Route selection supplies the tenant and publication; Origin,
URL query parameters, path labels and forwarded headers cannot supply identity.
Renewed evidence must keep that exact publication eligible. A new publication
needs a new reviewed grant; a grant is never inherited by another package or
another publication of the same component bytes.

The proposal fits an application that deliberately shares its public scripts,
styles and fonts with an approved external origin. It does not fit confidential
static content whose authorization depends on the asserted Origin: native
clients can forge that header. CORS controls browser reading, not caller identity.
There are no new listeners, guest policy overrides or background proxy processes.

## Bounds and normalization

- Configuration defaults to an empty list and is a closed document of at most
  64 KiB. At most 32 grants contain at most 16 distinct origins each. Duplicate
  authority/tenant/publication grants fail configuration validation.
- Origins must be the exact ASCII serialization of a normalized HTTPS origin,
  at most 512 bytes: no user information, path, query, fragment, whitespace,
  wildcard, suffix matching, `null`, lists or alternate default-port spellings.
  Unicode domains must be supplied in their canonical ASCII form.
- Existing authority ownership and public-origin bindings still apply. A grant
  cannot assign one hostname to two tenants. The native parser rejects duplicate
  singleton Origin/Fetch Metadata fields before lookup. Lookup examines at most
  32 grants and 16 origins for the selected grant, with no unbounded cache.
- Preflight permits at most two distinct lower-case requested header names in
  64 bytes. Existing listener header/body/connection/deadline bounds still apply.
  The profile does not increase any package, read-owner or serving byte ceiling.

Paths are routing scope, not browser isolation. Publishing mutually untrusted
applications under one origin gives them shared DOM/storage/cookie authority.
Allowing one caller origin grants its scripts browser access to the selected
publication; it cannot distinguish customers that share that caller origin.
Use distinct origins when that separation is required.

## One request and response contract

The exception applies only after selecting an eligible static publication and
an admitted non-document asset. Application handlers, HTML documents, SPA
fallbacks and arbitrary filesystem paths cannot use it. Unknown assets within
an already authorized publication may return a bounded 404; unknown publication
or tenant authority gets a generic denial without CORS permission.

| Input | Result |
| --- | --- |
| GET/HEAD, exact allowed Origin, `Sec-Fetch-Mode: cors`, `Sec-Fetch-Site: same-site` or `cross-site` | Continue with selected asset and its current admission |
| `Sec-Fetch-Dest` is empty, script, style, font, image or manifest | Eligible subresource destination |
| No Origin, null/list/malformed Origin, missing/contradictory Fetch Metadata, `no-cors`, document navigation or `Sec-Fetch-User` | Deny the cross-origin exception |
| POST/PUT/PATCH/DELETE or any body | Deny; no activation or remote effect |
| OPTIONS with exact allowed Origin and requested method GET or HEAD | Bounded host-owned preflight, without invoking a capsule |
| Requested headers `if-none-match` and/or `if-modified-since` | Permit conditional-read preflight |
| Authorization, proxy authorization, tenant selectors or any other requested header | Deny preflight and do not dispatch the actual request |

Script/link users must request CORS explicitly, for example
`crossorigin="anonymous"`; a classic opaque `no-cors` embedding is not an
implicit grant. The embedding application's CSP must also allow its asset
origin. LSF does not rewrite that application's CSP or strip Origin evidence.

All authorized responses, including HEAD, 304 and scoped 404, carry the exact
approved `Access-Control-Allow-Origin`, never `*`; `Cross-Origin-Resource-Policy:
cross-origin`; `Access-Control-Expose-Headers: ETag`; and `nosniff`. Preflight
adds `Access-Control-Allow-Methods: GET, HEAD`, only the approved requested
conditional header names, and `Access-Control-Max-Age: 0`. It receives no cookies
or authorization and never creates a publication/read capability that survives
the subsequent request's currentness check.

Use `Cache-Control: private, no-cache` even for immutable cross-origin URLs;
errors and denials use `no-store`. Every response varies on Origin,
Sec-Fetch-Site, Sec-Fetch-Mode, Sec-Fetch-Dest, Access-Control-Request-Method and
Access-Control-Request-Headers. A cached body cannot bypass a changed grant or
retired publication. Conditional responses repeat the current CORS/security
headers. Denial responses carry no CORS authorization and keep `CORP:
same-origin`; no reflected arbitrary origin or configuration data is returned.
Existing CSP, HSTS, MIME checks and host-owned security headers otherwise remain.

## Credentials and existing adapters

The profile initially belongs only to `public-origins`. That adapter supplies
its configured low-privilege principal. A browser cookie is never a platform
principal. The bearer adapter and its explicit browser bindings keep their
current same-origin behavior; operator/invocation bearer tokens cannot be used
through this exception, including in preflight or URLs.

`credentials: omit` is the default and emits no
`Access-Control-Allow-Credentials`; requests carrying cookies are rejected.
`credentials: include` is a separate explicit operator choice and emits the
literal `true`. Both modes still require the same exact origin/publication
grant. This flag allows a credentialed browser response to be read; it neither
authenticates a session nor instructs the browser to send cookies.

Keep the existing bounded, host-only Secure/HttpOnly cookie rules and
SameSite=Lax/Strict restriction. Static responses cannot set cookies and never
forward received cookies to a capsule or upstream. Same-site subdomains can send
eligible target-origin cookies; true cross-site fetches do not gain Lax/Strict
cookies simply because ACAC is present. Third-party-cookie restrictions remain
browser policy. Cookies for the external application's origin do not become
cookies for LSF. An integration requiring cross-site session cookies or
application-specific authorization needs a separate reviewed authentication
design; this asset profile does not silently add SameSite=None.

## Feasibility and implementation gate

`tools/cross-origin/contract.mjs` is a small executable contract, intentionally
separate from native ingress. Its unit cases cover closed bounded configuration,
origin normalization, current publication selection, credentials and preflight
rejection. `browser.mjs` runs actual Chromium against disposable HTTPS loopback
peers and records the received metadata, status and response policy. It checks
script execution, stylesheet application and loading a real WOFF2 font, then
allowed cross-site reads, unrelated origin/publication denials, credential modes,
SameSite behavior, conditional preflight, HEAD/304/errors, unsafe/header preflight
denial, null Origin and `no-cors`. It also confirms that Fetch ignores a script's
attempt to supply malformed Origin. A separately labelled HTTPS wire client
checks malformed header rejection: ordinary browser JavaScript cannot emit
that forbidden header. The receipt distinguishes those transport observations.

The experiment bypasses certificate trust only for its disposable loopback
certificate. It qualifies browser policy feasibility, not production TLS, native
LSF admission or any cloud platform. Its receipt explicitly sets
`nativeRuntimeQualified` and `productionTlsQualified` to false. It owns finite
90-second browser/listener lifetimes, at most 16 connections per listener and
128 request observations; cleanup closes the browser and all owned sockets.

Native implementation must integrate provisional browser admission, exact route
and publication selection, final lifecycle checks, per-response headers and
private cache revalidation as one change. Real-node tests must show unchanged
strict defaults, cross-tenant/publication rejection, grant removal, revocation,
restart behavior, errors/HEAD/304, disconnect ownership and bounded capacity.
The current supported alternative is same-origin static hosting and a separately
authorized application API, not a header-stripping CORS proxy.

The design follows the [Fetch CORS and credentials model](https://fetch.spec.whatwg.org/#cors-protocol-and-credentials)
and [Fetch Metadata request fields](https://www.w3.org/TR/fetch-metadata/).
