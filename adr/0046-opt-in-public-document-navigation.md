# ADR-0046: Opt in to public document navigation

- Status: Accepted
- Context: first integration feedback #628

## Decision

Keep the strict browser profile as the default. Operators may enable
`httpIngress.publicDocumentNavigation` for at most 32 canonical authority,
tenant and mount bindings, exclusively under `public-origins` authentication.
Bindings select path segments, not string lookalikes. They cannot name the
reserved immutable asset namespace or assign another tenant to an authority.

The exception accepts only GET/HEAD with `Sec-Fetch-Site: cross-site` or
`same-site`, `Sec-Fetch-Mode: navigate`, `Sec-Fetch-Dest: document`, and no
Origin header. Duplicate/malformed metadata and preflight fields are rejected.
`Sec-Fetch-User` is optional to accommodate redirects and must be `?1` if present.
Address-bar and same-origin requests continue through the existing strict rule.
Missing metadata cannot activate this exception; native calls without browser
metadata retain their existing authority/tenant contract.

Header admission is provisional. Route selection must select a current eligible
`static-web` publication and metadata resolution must select `text/html`.
Application targets, non-HTML assets and immutable asset locators cannot consume
the exception, even if a native caller forges document metadata. A redirect is
allowed only after resolving a directory's admitted HTML document; its canonical
relative Location preserves the mount and query. Every redirected request is
admitted independently. Publication eligibility remains fenced at delivery.

## Consequences

Public documentation can receive ordinary links without giving the linking page
permission to read its content. This adds no CORS permission, credentials, guest
header authority, worker or response rewrite. CSP, frame denial, CORP, unsafe
method checks, cache restrictions and all exchange owners remain in force.
Dynamic application pages require a separate reviewed policy; they do not inherit
the static-document exception. Mounts are routing scope, not browser isolation.

See the [Fetch Metadata request model](https://www.w3.org/TR/fetch-metadata/)
for browser-generated mode/destination/site fields and redirect treatment.

## Verification

Unit/configuration cases cover malformed/duplicate/missing metadata, exact
authority/tenant/mount scope, bounds, strict defaults and unsafe methods.
Real socket cases cover static GET/HEAD, redirects, non-HTML assets and excluded
mounts. The existing actual-component case proves forged navigation cannot
activate an API target. The signed static-publication workflow uses real Chromium
links from an external host and a sibling hostname, root and mounted documents,
308 redirects, address-bar navigation, and denied script/frame/fetch/form loads.
Its existing observations require drained owners and zero guest activations.
