# ADR-0043: Select static web publications as first-class HTTP targets

- Status: Accepted
- Date: 2026-09-22
- Issue: #495
- Phase: 3

## Context

The Phase 3 web stack already has two independent pieces of authority:

1. the HTTP trigger catalog owns canonical external host/path/method matching and its exact/prefix conflict and precedence rules; and
2. the web publication catalog owns immutable browser-package identity, signed web-manifest metadata, lifecycle/admission currentness, bounded public-asset reads and the reserved `/_lsf/*` asset namespace.

The existing `buffered-v1` HTTP trigger joins the first surface to an executable deployment. It therefore carries a service/contract/function, deployment ID, deployment generation, component release and immutable deployment revision. A browser-assets publication has none of those execution identities. Treating a static site as a synthetic deployment, renderer or capsule would create authority that does not exist and would make revocation/recovery ambiguous.

Static site hosting also must not create a second external router. Host/path ownership, exact-vs-prefix precedence, duplicate conflicts and stale-winner behavior are properties of the shared ingress route catalog, regardless of whether the selected target later invokes a guest or reads an immutable browser publication.

## Decision

### HTTP target variants

`HttpTrigger.spec.target` has two closed variants.

The application variant keeps the pre-existing JSON shape and `buffered-v1` profile. It contains service, contract, function, route, publication, immutable revision and deployment generation.

The static variant is:

```yaml
target:
  kind: static-web
  publication: publication:sha256:<digest>
```

It contains no service, contract, function, deployment route, component digest, deployment generation or deployment revision. The matching configuration is the closed `static-site-v1` profile with exactly `profile`, `scheme`, `host`, `path`, `pathMatch` and `method`. Static routes accept GET and HEAD only.

JSON uses a discriminator for the static form while retaining the old application spelling. Protobuf adds an additive target-kind discriminator after the existing application field numbers. A missing discriminator is interpreted as the legacy application variant. Supplying static-web together with application fields is invalid.

### Signed browser routing metadata

A BrowserAssets web manifest may opt into site routing with a closed `staticRouting` record:

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

The supported values are deliberately finite:

- `profile`: only `static-site-v1`;
- `directoryIndex`: `disabled` or `redirect`;
- `fallback.mode`: `none` or `spa`.

Every referenced document is a canonical public manifest path, exists in the same publication, and has media type `text/html`. `fallback.mode=none` carries no fallback document; `spa` requires one. The record is rejected on SSR packages and cannot contain a host, tenant, credential, filesystem root, proxy destination or mutable external URL.

The record is serialized inside the web manifest. Its bytes therefore participate in the existing manifest/package identity and admission proof. It is not mutable route-table metadata.

Existing exact `WebRoute` client/prerender declarations remain valid. Their runtime relationship to static-site fallback is assigned to the dependent static-serving runtime work; this ADR only fixes the publication metadata and external mount authority.

### Shared external matcher and mounts

Application and static targets are rows in the same HTTP matcher table.

The existing rules remain authoritative:

- one canonical authority cannot be claimed by different tenants;
- duplicate method/path/match-kind routes conflict;
- prefix matching is segment bounded;
- the longest matching path wins;
- exact wins over prefix at the same path;
- after a single winner is selected, stale or revoked target authority fails closed and does not retry a broader route.

The external mount path belongs to the trigger. A selected static request derives its site-local path directly from the already canonical request path, without reparsing or renormalizing:

- mount `/`, request `/orders/123` -> site path `/orders/123`;
- mount `/docs`, request `/docs` -> site path `/`;
- mount `/docs`, request `/docs/guide/` -> site path `/guide/`.

`/_lsf` and `/_lsf/*` remain node-reserved. A static-site fallback can never capture that namespace.

### Static selection authority

A static route selection returns an explicit static authority variant, not a fake invocation revision. It retains:

- trigger ID and trigger generation;
- catalog state version and the bounded HTTP read lease;
- exact tenant-scoped `PublicationRef`;
- the exact admitted web manifest digest, asset-tree digest and web publication generation recorded by the route;
- a sealed `WebSelection` owner from the existing artifact catalog;
- canonical mount path and derived site-local path.

The selected `WebSelection` owns the existing bounded web-read/current-admission lease. Selection verifies that the publication remains admitted, the static routing record still exists, and the manifest/assets/generation identities match the committed route. If any check fails, the winning route fails; broader routes are not considered.

Delivery must call the existing web currentness boundary immediately before accepting a representation for output. A route deletion does not revoke an already selected publication, but selected work still fails if the publication itself is revoked or replaced before delivery.

This ticket intentionally does not add the static response renderer/asset mapping to standalone ingress. The dependent runtime issue consumes this authority variant. Until that runtime is installed, standalone dispatch does not reinterpret a static target as an application activation.

### Durable state and receipts

HTTP table format v2 stores a tagged target identity per row.

Application target identity stores the exact publication, component digest, deployment ID, deployment generation and immutable revision.

Static target identity stores the exact publication, admitted web-manifest digest, asset-tree digest and web publication generation.

Format-v2 operation receipts carry the same tagged identity. Static receipts contain no component/deployment/revision placeholders.

Format-v1 HTTP tables and receipts remain readable as application-only state. Their original flat fields are retained in the data model solely for compatibility. Recovery reconstructs and validates the equivalent application target identity. The table is migrated to v2 only when an HTTP mutation is already being committed; read-only restart does not rewrite state. New writes use v2 exclusively and reject mixed v1/v2 record shapes as corruption.

Replay is keyed by the existing normalized request digest, actor, operation ID and CAS preconditions. Replaying an accepted static mutation returns the retained exact receipt and does not reselect a different publication. Delete/recreate receives a new trigger generation. Corrupt target/receipt associations fail recovery.

### Currentness and concurrent edits

Preparing a static apply selects the exact web publication and retains its web admission lease through commit. Commit runs under the existing web currentness fence while the HTTP table replacement is accepted. Publication revocation between prepare and commit therefore rejects the mutation.

The HTTP catalog transaction fence still rejects mixed concurrent route/deployment state. Selection captures one published HTTP table and only then resolves the chosen target authority. A concurrent trigger edit either appears entirely in the captured state or not at all.

Deleting a stale or revoked trigger remains allowed because deletion grants no publication use.

### Resource ownership

Dormant static routes retain bounded catalog metadata only. They do not allocate:

- execution cells or Wasmtime Stores;
- renderers or JavaScript heaps;
- tasks, timers, listeners or socket owners;
- provider pools;
- per-site asset caches or filesystem watchers.

The only static-specific live owner introduced by control selection is the existing bounded `WebSelection` read/currentness owner for an accepted operation or request. Immutable bytes continue to use the node-wide web blob store and node-wide asset service/caches defined by ADR-0038 and the immutable-browser-assets profile.

## Compatibility

Existing `buffered-v1` application JSON remains in its prior canonical shape and preserves the same target pins and execution semantics.

Existing Protobuf field numbers 1-7 on `TriggerTarget` and receipt fields 14-18 remain reserved for legacy application compatibility. New variant metadata is additive.

Existing format-v1 persisted HTTP state is accepted only when it satisfies the old application invariants. New format-v2 state must be internally variant-consistent.

No compatibility path may infer a component, deployment or renderer for a static publication.

## Consequences

Static hosting gains a first-class authority path that can be consumed by the shared HTTP runtime without weakening publication admission or duplicating route policy. Application invocation continues to receive a `ResolvedRevision`; static delivery receives web-publication authority instead.

Operationally, revocation stays on the publication lifecycle surface, while external host/path changes stay on the trigger surface. These controls are intentionally separate.

## Explicit exclusions

This decision does not add regex routes, arbitrary rewrites, filesystem roots, directory listing, arbitrary redirects, proxying, SSR through the static target, weighted static backends, mutable deployment aliases, CDN control, custom per-site listeners, or per-site caches.

Those features require separate authority, ownership and compatibility decisions rather than extension fields on `static-site-v1`.
