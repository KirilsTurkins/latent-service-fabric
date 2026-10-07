# Browser and hydration boundary: same-origin-v1

Issue #235 adds a deliberately narrow browser policy to the existing shared
standalone HTTP owner. It does not add an application listener, renderer pool,
cookie authenticator, HTML sanitizer, or stronger guest execution profile.
Linux x86-64 remains the qualified standalone serving profile. The HTTP WIT
contract and the Angular T0/T1 admission gate are unchanged.

## Origin, tenant and principal

The transport fixes the scheme: `http` for the loopback development profile,
`https` for direct TLS or the explicitly allowlisted TLS-terminating proxy
profile. The canonical Host authority and host-authenticated principal select
the tenant. Forwarded headers cannot supply scheme, host, base URL or identity.
Outside the proxy profile, `Forwarded` and `X-Forwarded-*` are rejected. Inside
it they are discarded, not trusted. Authorization, proxy authorization, trace
context, `X-Real-IP`, remote-user, original/rewrite-URL, `X-Auth-Request-*` and
`X-Authenticated-*` fields are not application identity channels. The existing
`X-Lsf-*` prohibition remains. Other application-visible headers are untrusted
data; only the host context is identity authority.

`public-origins` continues to map anonymous requests to its configured low-
privilege tenant principal, not to an authenticated end user. Its existing
authority/tenant bindings are also its browser bindings; a separate nonempty
`browserOrigins` setting is rejected. Bearer ingress is native-only by default:
requests containing Origin or Fetch Metadata require an explicit binding inside
`httpIngress`:

```json
{
  "browserOrigins": [{"authority": "web.example.test", "tenant": "example"}]
}
```

This optional closed array contains at most 32 distinct canonical authorities,
each associated with an existing invoke-credential tenant. It does not contain
a scheme or a credential. Once configured, every request must match its Host
and authenticated tenant, including native calls and immutable asset requests.
Administrator/RPC credentials are not browser authority. Browser metadata is
not authentication; a native client can fabricate it and must still authenticate.

An origin is a browser security boundary, not a URL path. Do not place mutually
untrusted tenants, applications, uploads or executable assets on one origin.
Different paths and immutable publication digests do not isolate their DOM,
cookies, same-origin scripts or browser storage. Avoid sharing an origin between
untrusted applications even when they share an LSF tenant.

## Requests, CORS and CSRF

An opt-in asset extension is specified in
[ADR-0049](../../adr/0049-scope-cross-origin-assets-to-publications.md). Its browser
experiment establishes feasibility only; native CORS support remains pending.
The current rules below continue to apply to running nodes.

- An Origin must equal the exact serialized configured origin. `null`, lists,
  alternative/default-port spellings, trailing slashes and foreign origins are
  rejected. Duplicate Origin or supported Fetch Metadata fields are rejected.
- By default, `Sec-Fetch-Site` permits only `same-origin` and `none`.
  Supported modes are `navigate`, `same-origin`, `cors` and `no-cors`; supported
  destinations are document, empty, script, style, image, font and manifest.
  `Sec-Fetch-User`, when present, must be `?1`.
- CORS is not supported. Preflight request fields are rejected, no access-control
  response headers are emitted, and guests cannot opt back in. This also means
  external-site links/subresources with cross-site Fetch Metadata are rejected
  unless a static document navigation is explicitly enabled below. A safe
  address-bar/new-tab navigation with `none` is supported.
- Public or browser unsafe methods require a matching Origin. `none` is not
  accepted for unsafe methods. GET, HEAD and OPTIONS must remain free of state
  changes in application code. Cookie values never authenticate a platform call.
  Native bearer requests without browser metadata retain their existing API use.

This is an origin-based CSRF profile, not a synchronizer-token or login/session
framework. Legacy clients lacking an Origin on unsafe public calls fail closed.
The host emits `Referrer-Policy: same-origin`: cross-origin referrers are withheld
without making same-origin non-CORS POST Origin become `null`, as the
[Fetch Origin-header algorithm](https://fetch.spec.whatwg.org/#origin-header)
would do for `no-referrer`. Browser tests exercise an actual same-origin POST.

## Host-owned response policy

### Allow links to public static pages

To let readers follow links from other websites, add a
`publicDocumentNavigation` array inside `httpIngress`. Each entry supplies an
existing public `authority`, its `tenant`, and a `mount`, such as `/docs` or `/`.
The authority and tenant must match `authentication.origins` under the
`public-origins` adapter. A maximum of 32 distinct authority/mount pairs is
allowed. Omission or an empty array keeps the strict policy.

Only top-level GET/HEAD document navigations to admitted static HTML qualify.
Both `same-site` and `cross-site` require `navigate` mode, `document` destination
and no Origin header. Duplicate or malformed fields are rejected; incomplete
metadata does not qualify for the exception. Directory redirects are checked
again at their destination. `/docs` includes `/docs/guide`, not `/docs-other`.

This lets the reader open a public page. It does not let the linking website
fetch its scripts, read its API, embed it in a frame, or submit cross-origin
forms. Application capsule routes and immutable asset URLs remain outside the
exception. A native caller can forge browser metadata but cannot bypass tenant,
route, media or current publication eligibility checks. See
[ADR-0046](../../adr/0046-opt-in-public-document-navigation.md).

### Response headers

Static HTML can additionally use the bounded, signed style identities described
in [ADR-0052](../../adr/0052-authorize-exact-static-style-identities.md) when the
host explicitly enables `httpIngress.allowStaticStyleHashes`. The host adds only
those SHA-256 sources to `style-src`. Script policy, style-attribute restrictions
and every other directive remain unchanged. The same selected publication policy
appears on HTML HEAD, 304 and directory redirects; errors keep the strict policy.
No nonce or HTML rewrite is involved. See the
[framework guide](../how-to/serve-angular-and-docusaurus.md) for application changes.

All writable dynamic, error and immutable-asset responses, including HEAD and
304, receive these headers. A failed/expired transport may close without a
response; it does not promise to write headers after losing ownership.

```text
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; worker-src 'none'; manifest-src 'self'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: same-origin
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
```

HTTPS responses additionally carry `Strict-Transport-Security: max-age=31536000`,
without includeSubDomains or preload. Deploy HTTPS before using browser cookies.
No executable inline script, inline style, eval, blob/data script, remote script,
worker, iframe embedding or base-element override is allowed by this profile.
Use AOT Angular, external same-origin bootstrap/CSS and URLs derived from the
admitted publication. The controlled fixture uses no inline component styles.
This work does not rewrite Angular output to fit that policy.

The complete development discovery contract is
`latent.browser.response-ownership.v1`, in
[the machine-readable ownership table](../../contracts/http/browser-response-ownership-v1.json).
It describes the existing alpha.4 `buffered-v1`/`same-origin-v1` response policy;
development adds early helpers and bounded operator reasons, without granting
new guest header authority. Native classification, Java authoring tests and this
table are checked together. Names/prefixes collide case-insensitively; actual
guest fields must already be canonical lowercase HTTP tokens.

<!-- response-ownership-v1:begin -->
| Class | Names and prefixes | Behavior |
| --- | --- | --- |
| Host security | `content-security-policy`, `x-content-type-options`, `x-frame-options`, `referrer-policy`, `cross-origin-opener-policy`, `cross-origin-resource-policy`, `permissions-policy`, `strict-transport-security` | Reserved on HTTP and HTTPS; host emits fixed policy (HSTS on HTTPS only). Guest conflict returns empty no-store 502. |
| Host transport/framing | `host`, `content-length`, `content-type`, `server`, `date`, `via`, `alt-svc` | Guest fields forbidden. Use typed media-type/representation-length/body; transport owns framing. Invalid output returns empty no-store 502. |
| Hop-by-hop | `connection`, `keep-alive`, `proxy-connection`, `te`, `trailer`, `transfer-encoding`, `upgrade` | Forbidden in the buffered profile; no chunking, trailers, upgrades or guest connection control. Invalid output returns empty no-store 502. |
| Identity/credential forwarding | `authorization`, `proxy-authorization`, `forwarded`, `traceparent`, `tracestate`, `baggage`, `x-real-ip`, `remote-user`, `x-remote-user`, `x-original-url`, `x-rewrite-url`, `x-forwarded-*`, `x-auth-request-*`, `x-authenticated-*` | Forbidden guest output; request identity fields are stripped by host mapping. Never an application principal channel; conflict returns empty no-store 502. |
| Platform namespace | `x-lsf-*` | Reserved platform namespace. Guest output returns empty no-store 502. |
| Unsupported browser policy | `refresh`, `content-location`, `link`, `clear-site-data`, `report-to`, `nel`, `content-security-policy-report-only`, `cross-origin-embedder-policy`, `access-control-*` | Forbidden; guests cannot add CORS, alternate navigation, reporting or embedding policy. Conflict returns empty no-store 502. |
| Conditional application fields | `location`, `content-encoding`, `set-cookie`, `vary` | Location: singleton canonical root-relative redirect (or 201). Encoding: singleton identity. Set-Cookie: bounded unique HTTPS __Host- cookies with exact attributes. Vary: application field; private host caching needs approved dimensions. Failed value rules return empty no-store 502. |
| Application cache input | `cache-control`, `age` | Accepted bounded input. Host strips supplied Cache-Control/Age from dynamic wire output and emits no-store plus its own local-hit Age. Duplicate/unsafe cache directives bypass host caching; they do not authorize shared browser/proxy caching. |
| Credential-sensitive application data | `cookie`, `www-authenticate`, `proxy-authenticate`, `authentication-info`, `proxy-authentication-info` | Accepted as bounded application response fields; never platform authentication. Authors must classify their data and avoid disclosing credentials. Set-Cookie uses the separate strict conditional profile. |
| Other application fields | Other valid names | Other canonical lowercase HTTP-token names are accepted (for example etag, last-modified, expires, content-language and x-app-*). Ordinary duplicate fields are retained; applications define their semantics. All fields obey the shared grammar and finite budgets. |
<!-- response-ownership-v1:end -->

Guests cannot override these headers, set any `Access-Control-*`, or emit
Refresh, Content-Location, Link, Clear-Site-Data, Report-To, NEL, CSP-report-only
or COEP. Invalid guest output becomes a fixed non-reflective, no-store 502 before
any bytes or pending cache fill are committed. This preserves the delivery
lease and existing cancellation/cleanup accounting.

### Validate before returning traffic

New development Java projects include
[`BufferedWebResponseValidator`](../../sdk/java-guest/runtime/dev/latent/guest/BufferedWebResponseValidator.java).
It is a pure SDK helper, independent of application-specific generated Bindings.
Pass the actual method/scheme, status, typed header list, optional media,
decoded body bytes and optional unsigned representation length immediately before
constructing/returning the generated response. `validate` returns a closed
`Reason`; `requireValid` throws only `buffered-web-response-<REASON>`. Neither
returns or formats an arbitrary header name/value, token or body. The shared
[inspection helper](../../tools/browser_response_ownership.py) catches declared
header-name conflicts for tooling; dynamically computed fields are explicitly
marked as requiring execution, and values/body always require full validation.

Early helpers are authoring feedback, not admission or browser qualification.
Mutating a response after validation cannot bypass the host's current validation,
authorization or cleanup. Existing projects retain their pinned SDK snapshot;
adopt the new SDK through the normal project/source snapshot and rebuild/sign
workflow. There is no automatic rewrite of signed bytes or saved responses.

The runtime records only the bounded typed operator reason
`OutputValidation / HttpResponseRejected` for a rejected application response,
under the actual admitted tenant/activation scope and current diagnostic-read
authorization. Execution success is distinct from accepted HTTP output. This
does not expose a raw internal diagnostic in HTTP: public output remains the
fixed empty 502 with host security headers and `no-store`. Use the local SDK
reason and this ownership table to correct output rather than copying raw
application values into error messages.

### Referrer decision and application-side mitigation

The reviewed development decision for #713 is to defer an operator-selectable
`no-referrer` response profile. Alpha.4 and current development both ship the
fixed `Referrer-Policy: same-origin`; there is no node configuration or web
manifest field for choosing another value. A future choice needs a closed
versioned identity, cache-policy association and actual unsafe-method/browser
qualification. Referrer suppression also interacts with the
[Fetch Origin-header algorithm](https://fetch.spec.whatwg.org/#origin-header):
an unsafe non-CORS request using `no-referrer` can acquire `Origin: null`, which
this existing CSRF boundary rejects. The response policy cannot be changed
independently of those semantics.

Applications that carry sensitive URL data can include a build-time
`<meta name="referrer" content="no-referrer">` **before** any resources in their
owned HTML, use `referrerpolicy="no-referrer"`/`rel="noreferrer"` on appropriate
links, and set the Fetch `referrerPolicy` on individual calls. These are browser
application choices, not permission to return a guest `Referrer-Policy` header.
Remove a consumed token from the visible URL using `history.replaceState`
before subsequent requests. Keep trusted data classification and explicit
same-origin unsafe-method Origin behavior in the application; the maintained
POST helper uses an explicit `same-origin` policy after URL cleanup.

The maintained controlled Angular/browser example includes the meta policy
before its external bootstrap, exercises synthetic token-bearing document/fetch
URLs, and verifies no token reaches unintended referrers or reused output.
Its actual host responses still report `same-origin`, strict CSP and `no-store`
on application traffic. A meta element inserted after initial resource fetching
cannot retroactively protect those requests. LSF never inserts it at runtime or
mutates immutable HTML. This is not a login/session/token product or secret scanner.

This decision uses the [Referrer Policy editors' draft](https://w3c.github.io/webappsec-referrer-policy/)
(20 March 2026, work in progress), the [HTML referrer-policy attributes](https://html.spec.whatwg.org/multipage/urls-and-fetching.html#referrer-policy-attribute)
and the Fetch living standard, reviewed on 30 September 2026. Actual maintained
Chromium receipts establish the implemented examples on the recorded source;
the standards links do not replace that execution evidence.

Redirects 301/302/303/307/308 require exactly one canonical root-relative Location;
201 may have one. Other statuses may not have one. Absolute URLs, protocol-relative
URLs, fragments, dot/encoded-separator aliases, backslashes and CR/LF fail closed.
The browser's actual origin supplies the base, never guest or proxy metadata.

Dynamic HTML must declare exactly `text/html; charset=utf-8` (case-insensitive)
and contain valid UTF-8. Other declared media remain subject to the existing
bounded MIME grammar. A missing dynamic media type becomes application/octet-stream.
Immutable assets retain their admitted manifest MIME and exact bytes; HTML
authors must declare UTF-8 in their document, as the fixture does. Assets are
not rewritten, extension-sniffed by the HTTP owner or served from unlisted paths.

## Cookies, framing and encoded bodies

The request cookie profile is at most 16 distinct names and 4,096 aggregate
header-field-value bytes across Cookie fields. Names are 1-64 HTTP token bytes; values are at most
1,024 RFC cookie-octets, without quoting, whitespace or control characters.
Duplicate names and malformed pairs are rejected, not resolved by precedence.
Count/aggregate overflow returns 431; malformed pairs return 400.

Response cookies are HTTPS-only, unique `__Host-` names with nonempty suffixes.
Every cookie requires the exact attributes `Secure; HttpOnly; SameSite=Strict;
Path=/`, in any order and without duplicates. Only `Max-Age=0` deletion is an
optional additional attribute. Domain, Expires, persistent positive lifetimes,
other SameSite modes and script-readable cookies are unsupported. The same
name/value/count/aggregate limits apply. Cookies still belong to application
session logic and never change the platform principal.

The existing 64-field/16-KiB header budget, 32-KiB raw head, strict CRLF framing,
64-KiB request body and 256-KiB dynamic response body remain. Host security
headers have fixed additional output overhead; the asset head allowance is
2 KiB inside the existing exchange/connection reservation. Duplicate framing,
transfer-encoding, header controls, ambiguous Host/Content-Length and canonical
path violations fail before application execution.

Only absent or one identity Content-Encoding is supported. Encoded requests
return 415; duplicate encoding fields return 400. Encoded/duplicate-encoding
guest responses return 502. There is no decompression, expansion allowance,
compression worker or implicit gzip/Brotli fallback. Immutable assets retain
their [identity-only negotiation and range profile](../immutable-browser-assets.md).

## Hydration and application responsibilities

The executable reference implementation is
`examples/browser-boundary/shared/hydration.ts`, used by the paired controlled
server/client fixture. It transfers only an explicitly selected flat DTO:

| Limit or rule | Supported profile |
| --- | --- |
| Fields | At most 64 unique, closed ASCII names, 1-64 characters |
| Values | String, finite number other than negative zero, boolean or null |
| Individual string | At most 8,192 UTF-16 code units |
| Complete serialized data | At most 32,768 UTF-8 bytes, including escaping |
| Raw-text escaping | `<`, `>`, `&`, U+2028 and U+2029 become JSON Unicode escapes |
| Objects/hooks | No nested objects/arrays, accessors, symbols, toJSON or prototype keys |
| Client parse | Bounded input and exact canonical re-encoding, rejecting duplicates/aliases |

Explicit projection reads only selected own data properties, not secret getters,
and produces a frozen null-prototype DTO. Sorted JSON lives in an inert
`script[type=application/json]`; an external bootstrap reads it and Angular
interpolates text without innerHTML or trust-bypass APIs. Both ends disable
Angular's automatic HTTP transfer cache with `withNoHttpTransferCache()`.
Angular's own hydration metadata is separate from the application DTO ceiling
and remains covered by the renderer's complete output bound.

This is not automatic secret recognition or a JavaScript sandbox. Trusted
application code must explicitly decide which scalar values are public; selecting
a secret string would disclose it. Do not pass arbitrary server contexts,
credentials, provider responses or malicious Proxy objects to serialization.
Source-role separation and this fixture's public projection demonstrate exclusion
of synthetic bearer/secret/server-object values, not universal information-flow
enforcement on arbitrary guest programs. Never enable broad HTTP transfer caching
for personalized/provider responses or import server modules into a client bundle.

The platform cannot sanitize arbitrary application HTML or make a deliberately
malicious same-origin script safe. Such a script already has that origin's
authority. Application authors own template correctness, disclosure decisions,
session authentication/rotation, unsafe-method semantics and any URL choices
inside their HTML. Operators own TLS, separate tenant origins, proxy-peer
isolation, credentials, publication policy and upstream abuse controls.

## Cache and authority separation

The [bounded response cache](../reference/http-response-cache.md) remains an
operator-approved immutable-public optimization, not a browser/session cache.
It is off by default. Credential-bearing, Cookie, query, conditional and other
unapproved application-visible headers bypass it; Origin/Fetch Metadata are not
new approved Vary fields. Typical browser requests therefore conservatively
bypass that cache. This change neither broadens cache eligibility nor introduces
an unbounded tenant/origin map. Dynamic wire responses remain no-store.

The real component regression fills a public entry, returns distinct Alice/Bob
cookie-personalized bytes without Age/cache reuse even when the guest asks for
public caching, then retrieves the untouched public entry. Cross-tenant origin
bindings and credential rejection run before route/asset lookup. A separate
regression rejects unsafe HTML before a staged response-cache fill can publish.

Immutable asset caching remains private, immutable and varied on Authorization
and Accept-Encoding. Current publication/policy authority is checked on every
origin request, including hits/HEAD/304. Browser-cached immutable bytes cannot
be recalled by revocation. Neither kind of cached byte buffer grants admission.

## Finite abuse evidence and qualification limits

The real-socket abuse tests keep two incomplete peers within a two-connection
profile, serve an eligible asset while one slot is free, reject excess residency,
reclaim trickling/silent peers at the original deadline, and then serve another
eligible request. No renderer activation is created. Existing TLS handshake,
body, idle, write, connection-age and cleanup deadlines remain independently
tested. These observations do not prove fairness against a continuous reconnect
flood, whole-process RSS isolation or protection from a hostile host/kernel.
Loopback RPC bearer authentication and browser HTTP origin/CSRF policy are
different boundaries; locality is not tenant identity.

The maintained browser test launches real Chromium against the actual shared
HTTP owner and verified immutable asset path, with no network response mocking.
It checks original DOM identity, a working Angular click binding, full-document
navigation and rehydration, malicious-string round-trip, actual inline/remote
CSP violations, base-override rejection, wrong-script-MIME rejection and a
same-origin POST reaching the asset method policy. Build/browser receipts are
small version/hash/boolean observations and contain no real credentials.

The fixture uses pinned Angular 22.2.0 and Node 24.19.0 to produce controlled
Node SSR HTML; it does **not** claim Wasm-component SSR execution, browser login,
production deployment or malicious-application isolation. The asset test authority
is explicitly non-cryptographic; existing signature/admission tests own that
boundary. Container-root Chromium uses `--no-sandbox` only in the test harness,
so this is not evidence of Chromium's OS sandbox. Parent #236 owns the complete
application/SSR release integration after the #226 management/T1 work.

### Reproduce the focused checks

Use the repository's pinned toolchains and a Linux Chromium executable:

```sh
cargo test -p latent-ingress --locked
cargo test -p latentd --lib --locked standalone::http
node --test tools/tests/browser_hydration.test.mjs
npm ci --prefix examples/renderer-profile --ignore-scripts --no-audit --no-fund
node tools/browser-boundary/build.mjs examples/renderer-profile /tmp/browser-boundary
LSF_BROWSER_BUILD=/tmp/browser-boundary LSF_BROWSER_NODE="$(command -v node)" LSF_BROWSER_CHROME="$(command -v chromium)" LSF_BROWSER_TOOLCHAIN="$PWD/examples/renderer-profile" cargo test -p latentd --lib --locked actual_browser_boundary -- --ignored --nocapture --test-threads=1
```

`tools/validate_contracts.sh` builds the public web component and explicitly runs
the `actual_http_component` tests, including personalized cache and unsafe-output
coverage. Ordinary test output marks missing component/browser prerequisites as
ignored, not successful execution. CI runs the browser probe from its current
Cargo artifact inventory and retains the compact observations; a missing test,
browser, fixture or receipt is a failure, not substituted security evidence.

See the [bounded local validation observations](../testing/browser-boundary.md)
for exact tested code, dependency heads, counts and redacted artifact identities.
