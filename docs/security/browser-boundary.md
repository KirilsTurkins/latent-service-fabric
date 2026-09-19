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

- An Origin must equal the exact serialized configured origin. `null`, lists,
  alternative/default-port spellings, trailing slashes and foreign origins are
  rejected. Duplicate Origin or supported Fetch Metadata fields are rejected.
- `Sec-Fetch-Site` permits only `same-origin` and `none`, not even `same-site`.
  Supported modes are `navigate`, `same-origin`, `cors` and `no-cors`; supported
  destinations are document, empty, script, style, image, font and manifest.
  `Sec-Fetch-User`, when present, must be `?1`.
- CORS is not supported. Preflight request fields are rejected, no access-control
  response headers are emitted, and guests cannot opt back in. This also means
  external-site links/subresources with cross-site Fetch Metadata are rejected;
  a safe address-bar/new-tab navigation with `none` is supported.
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

Guests cannot override these headers, set any `Access-Control-*`, or emit
Refresh, Content-Location, Link, Clear-Site-Data, Report-To, NEL, CSP-report-only
or COEP. Invalid guest output becomes a fixed non-reflective, no-store 502 before
any bytes or pending cache fill are committed. This preserves the delivery
lease and existing cancellation/cleanup accounting.

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

The fixture uses pinned Angular 22.1.6 and Node 24.19.0 to produce controlled
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
