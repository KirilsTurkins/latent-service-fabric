# Share static assets with an approved browser origin

Use `httpIngress.crossOriginAssets` to let an external application read scripts,
styles, fonts and other non-document assets from one exact signed publication.
This is the native `cross-origin-assets-v1` behavior specified by
[ADR-0049](../../adr/0049-scope-cross-origin-assets-to-publications.md), not a
separate listener or a `profile` configuration field. Omission or `[]` retains
[strict same-origin defaults](../security/browser-boundary.md).

**Version boundary:** this guide requires matching development node/CLI source
that includes #660; it is not a configuration for the published alpha.5 toolkit.
The [native qualification record](../testing/cross-origin-static-assets.md)
covers signed publications served directly by LSF over test TLS, including
actual Chromium and publication lifecycle changes. It is not production
certificate, cloud-deployment or end-user authentication qualification.

## Prepare the publication and listener

First [publish a signed static site](static-release-workflow.md) under an existing
tenant and retain the immutable `publication:sha256:...` ID returned by
`latent web publish`. A package digest, release name or content hash is not a
substitute for that publication ID. Keep its evidence current. Configure the
[shared HTTP listener](../reference/http-ingress.md) with direct TLS, a certificate
for the serving hostname, and the existing `public-origins` adapter. The tenant
must already exist in the node's credential configuration. No browser bearer
token or end-user session is installed by this adapter.

For routed URLs, apply both GET and HEAD using the
[static route-set workflow](static-route-sets.md), selecting this exact
publication, HTTPS authority and intended mount. A GET trigger does not imply a
HEAD trigger. OPTIONS uses its requested GET/HEAD selection; do not add an
OPTIONS capsule or an application-owned CORS handler. The immutable
`/_lsf/assets/<publication-id>/<asset-path>` locator still selects that same
publication under the authenticated authority's tenant.

## Configure one exact grant

The [schema-checked example](../../examples/cross-origin-assets/http-ingress.json)
is the **value of `httpIngress`**, not a complete standalone node configuration.
Replace its example hostname, tenant, TLS paths and all-`a` publication ID with
your admitted publication and protected deployment inputs. Its grant is:

<!-- native-cors-grant:begin -->
```json
{
  "authority": "assets.example.test:8443",
  "tenant": "example",
  "publication": "publication:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "origins": ["https://portal.example.test"],
  "credentials": "omit"
}
```
<!-- native-cors-grant:end -->

`authority` is the serving Host authority without a scheme or path and must match
`authentication.origins` for the same tenant. `origins` contains caller origins,
not asset URLs. HTTPS default port 443 is omitted; a nondefault port must match
exactly. Use normalized ASCII hostnames, including canonical ASCII domain names
for internationalized domains. Do not use wildcards, suffix patterns, `null`,
origin lists in one string, user information, paths, queries or fragments.

The grant covers eligible non-document assets in the **whole publication**;
it is not a per-path permission. Limits are 32 distinct
`authority`/`tenant`/`publication` tuples, 16 distinct origins per tuple, 512 bytes
per origin, and 64 KiB for the compact effective grant array, including defaulted
credential fields. The normal node-configuration bound also applies. Unknown
fields, duplicate grants/origins, aliases and foreign authority ownership fail
validation. The [JSON schema](../../schemas/node-http-ingress.schema.json) checks
shape; native validation additionally checks canonical identity, ownership and
aggregate bounds.

Nonempty grants require HTTPS and `public-origins`; bearer ingress and cleartext
loopback mode cannot enable them. An already secured `trusted-proxy` transport
can supply its fixed HTTPS scheme under its existing peer/Host contract, but the
qualification uses direct native TLS. Do not strip Origin or Fetch Metadata at
a proxy, inject CORS headers there, or use forwarded fields as tenant authority.

Keep node-wide `limits.maximumPayloadBytes` at the listener-required 2097152.
Retain the rest of your existing node configuration, protected credentials,
execution profile, storage and audit settings. The sample's two exchanges must
fit the node's configured reservation capacity; its buffer allowance is not
permission to raise node quotas. TLS file/ancestor protection and the existing
connection, deadline, read-owner and shutdown limits remain mandatory.

Validate the complete protected node configuration before an orderly restart:

```sh
/opt/lsf/bin/latentd check-config --config /etc/lsf/node.json
```

`check-config` does not start serving or prove publication readiness. Grants are
fixed for a node lifetime; there is **no hot reload**. Stop/drain the old instance
and restart it through your existing supervisor with the validated configuration.
Do not change files and assume the running listener has adopted them.

## Request CORS explicitly in the consuming application

The caller's CSP must permit the asset origin in the relevant `script-src`,
`style-src`, `font-src` and/or `connect-src` directives. LSF does not rewrite the
caller's CSP. Request scripts and styles in CORS mode:

```html
<script crossorigin="anonymous" src="https://assets.example.test:8443/app.js"></script>
<link crossorigin="anonymous" rel="stylesheet" href="https://assets.example.test:8443/style.css">
```

For a readable fetch, use `fetch(assetUrl, {credentials: 'omit'})`. Do not attempt
to set Origin or Fetch Metadata in JavaScript; browsers own those headers.
Classic opaque `no-cors` embedding, document navigation, HTML/SPA fallbacks and
application capsule routes are not covered. Public document navigation is a
[separate opt-in](../security/browser-boundary.md#allow-links-to-public-static-pages).

An eligible request has one exact approved Origin, `Sec-Fetch-Mode: cors`,
`Sec-Fetch-Site: same-site` or `cross-site`, and an empty, script, style, font,
image or manifest destination. GET/HEAD have no body. Bounded host-owned OPTIONS
permits only requested GET/HEAD and optional `if-none-match`/`if-modified-since`
headers (at most two distinct names in 64 bytes). Authorization, tenant selectors,
other requested headers, unsafe methods, opaque/null origins and malformed or
duplicate metadata are rejected without activating a capsule.

## Credentials, caching and lifecycle

`credentials: "omit"` is the default: no `Access-Control-Allow-Credentials` is
emitted and requests carrying cookies are rejected. Selecting `"include"`
explicitly adds `Access-Control-Allow-Credentials: true` for the approved origin;
it does not authenticate a session. Static responses never set cookies or
forward them to a capsule. Existing Secure/HttpOnly, host-only and SameSite
Lax/Strict restrictions remain. Cross-site requests do not gain SameSite=None
cookies; third-party-cookie policy still applies.

Successful GET/HEAD and 304 responses use exact `Access-Control-Allow-Origin`,
`Cross-Origin-Resource-Policy: cross-origin`, exposed ETag and
`Cache-Control: private, no-cache`, including immutable URLs. Preflight has
`Access-Control-Max-Age: 0`. A missing asset in an already authorized publication
can return a CORS-readable, empty 404 with `no-store`; policy denials carry no
CORS permission, use `no-store`, and retain `CORP: same-origin`. Host CSP, HSTS,
`nosniff` and framing rules remain in force.

Responses vary on Origin, Sec-Fetch-Site, Sec-Fetch-Mode, Sec-Fetch-Dest,
Access-Control-Request-Method and Access-Control-Request-Headers. Each new read,
conditional response and preflight must still pass current publication authority;
output rechecks that authority during writes. Do not replace this with a shared
immutable cache or a long preflight lifetime. LSF cannot retract bytes or code
already delivered to a browser; revocation prevents subsequent authorized output,
not use of previously received bytes.

To remove a grant or caller, change the protected configuration and stop/restart
the node; verify a fresh cross-origin read, HEAD and conditional request are
denied. For a new publication, update the exact routes and explicitly review a
new grant. Publishing identical asset bytes again does not inherit permission.
An old immutable URL remains readable while its old grant and publication are
still eligible; remove that grant too when replacing it. Restart does not revive
a revoked publication.

[Evidence renewal](static-evidence-renewal.md) preserves the publication ID but
advances lifecycle generation. It is not a new grant and cannot un-revoke retired
authority. Refresh exact route lifecycle references through the supported
route-set workflow where required. Expired/stale evidence fails closed, including
cached/conditional/preflight requests, until current evidence and selection are
restored. Storage, clock or capacity failures are not permission to fall back to
an application handler. Inspect protected operator diagnostics rather than
adding permissive headers to a failure.

## Security boundary

CORS controls what a cooperating browser may read. A native client can forge
Origin and Fetch Metadata, so neither is authentication or confidential-content
authorization. Use this profile for deliberately shared public assets. Paths and
publication IDs do not isolate mutually untrusted applications sharing one
origin: they share DOM, script, storage and cookie authority. Use distinct origins
when that separation is required. An approved caller also trusts the selected
script/style bytes; review both the publication and the caller-origin list.
