# ADR-0042: Bound Angular render data through the capability broker

- Status: Proposed; implementation and actual integrated qualification are required before acceptance.
- Scope: Phase 3 Angular reference delivery, #236 and the preserved #44 criteria.
- Builds on: [ADR-0040](0040-run-the-closed-angular-adapter-in-fresh-generic-stores.md)
  and [ADR-0038](0038-admit-web-packages-with-componentless-publication-authority.md).

## Context

The existing Angular component renders real hydratable HTML in a fresh generic
Store, but its projected manifest requests only sealed context and zero outbound
operations. A browser calling another API does not prove a capability call during
SSR. Enabling ambient JavaScript fetch, a persistent Node server, or a privileged
host-side HTTP proxy would violate the selected execution and authority model.

## Decision

Add one optional, closed `scoped-http-get-v1` backend-data profile. Its presence
in the signed web renderer metadata requests the existing
`latent:http/client@0.2.0` contract and a ceiling of one outbound request. Absence
keeps the existing context-only renderer. The public web response contract does
not change. The backend-enabled source world is separately named and structurally
checked against pinned context, HTTP and web WIT before compilation or native use.

The application may synchronously prepare either no backend request or one URL
in a small private JSON frame. The fixed async Rust adapter performs one GET
through the existing activation-scoped broker/provider and then passes a bounded
UTF-8 response or closed error category to the Angular render function. It sends
no application-provided headers, cookie, bearer credential, body or retry. The
provider alone obtains any configured credential through its protected binding.
Destination and operation policy remain the intersection of actual imports,
requested and deployed capability, principal, current publication and grant.

The adapter caps URL/plan bytes, result bytes and the relative call timeout; the
existing activation's remaining deadline and conserved budget can only narrow
those limits. Cancellation/disconnect retains the real host operation's ownership
until physical cleanup, and status/recovery uses the original activation ID.
An HTTP response is an immediate external observation, not a transactional effect
or proof that cancellation undid it. No automatic retry is introduced.

The private preparation/render bridge permits one ordered render per fresh Store.
It is not a general async JavaScript host API, arbitrary Node compatibility,
streaming request engine or multi-round application scheduler. Browser code gets
neither the preparation function nor sealed server context. Applications explicitly
select the finite public strings they transfer, with existing hydration, CSP,
origin, immutable asset and response-cache policy still enforced independently.

## Consequences and qualification

The fixed adapter source participates in the renderer profile digest. Changes
invalidate incompatible prepared/native identities; no old profile bytes are
silently relabelled. The package, application source, builder observation and
SBOM continue to bind the complete output and public asset tree separately.

Qualification must build the actual maintained Angular source, sign and verify
the package, publish/deploy via public APIs, render before browser JavaScript,
hydrate and navigate in Chromium, and exercise public/authenticated, application
failure, allowed/denied backend and cancellation/recovery paths. Tests must show
no broker/provider credential in HTML, hydration or client assets, exact revision
pinning across canary/rollback, and zero render cells for immutable assets.
The #239/#240 campaigns retain actual cold/warm and ownership evidence; this ADR
does not itself satisfy those gates or claim T2/T3/hostile-multitenant containment.
