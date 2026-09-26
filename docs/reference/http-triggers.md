# Scoped HTTP trigger routes

Phase 3 HTTP trigger management exposes `TriggerService` Apply/Get/List/Delete
and `GetTriggerOperation` over the standalone node's management listener.
The same route catalog is selected by the shared ingress for executable
application routes and componentless static browser publication routes.

## Application profile

`HttpTrigger` supports the closed `buffered-v1` configuration: exactly `profile`,
`scheme`, `host`, `path`, `pathMatch`, and `method`, all strings. Scheme is `http`
or `https`; path matching is `exact` or `prefix`. Methods are explicit GET, HEAD,
POST, PUT, PATCH, DELETE, or OPTIONS. Each record selects one method. HEAD never
implicitly falls back to GET.

Host and path use the [HTTP application's canonicalization](../protocol/http-applications.md):
case/default-port aliases normalize before conflict detection. Routes cannot
contain queries, wildcard hosts, encoded path separators, or regexes. A prefix
matches a complete path segment (`/api` also matches `/api/x`, but not `/apis`).
Non-root prefixes cannot end in `/`. The longest matching path wins; an exact
match wins over a prefix at the same path. A stale winning route denies the
request instead of falling back to a broader route.

The target must name a deployment route, its explicit tenant publication ID,
content revision, and positive deployment object generation. `default` weighted
routes are not supported. Only the `latent:web/application@0.1.0` contract's
`handle` function is accepted. Publication metadata, the compiled callable and
current release eligibility must agree with this target and the trigger tenant.
Tenant capsules may export this exact shared application interface; their
capsule world and other owned exports still belong to their tenant namespace.
Exporting the interface grants no host capability or execution permission.

## Static browser publication profile

A `static-web` target is a separate authority variant:

```yaml
apiVersion: latent.dev/v1alpha1
kind: HttpTrigger
metadata:
  name: customer-a-web
  tenant: customer-a
spec:
  target:
    kind: static-web
    publication: publication:sha256:<digest>
  configuration:
    profile: static-site-v1
    scheme: https
    host: customer-a.example.com
    path: /docs
    pathMatch: prefix
    method: GET
```

Static targets carry no service, contract, function, deployment, component,
revision, deployment generation or renderer identity. Supplying any application
target field together with `kind: static-web` is rejected. GET and HEAD are the
only accepted methods.

The referenced publication must be an admitted BrowserAssets package whose
signed web manifest contains a valid `staticRouting` record with profile
`static-site-v1`. That record names only site-local public HTML documents and
contains the entry-document, directory-index and fallback policy. Host/path
ownership remains in the trigger rather than the signed package, so the same
immutable publication may be mounted at different canonical external prefixes
without changing its package identity.

Application and static targets occupy the same matcher table. Longest
segment-bounded prefix and exact-over-prefix precedence are unchanged. After one
winner is selected, a stale/revoked target denies rather than falling back to a
broader row.

The external mount is stripped directly from the already canonical request path:
`/` + `/orders/123` yields `/orders/123`; `/docs` + `/docs` yields
`/`; and `/docs` + `/docs/guide/` yields `/guide/`. The node-reserved
`/_lsf` namespace can never be captured by a static fallback.

A selected static route retains the exact tenant-scoped publication, web-manifest
digest, asset-tree digest, web publication generation and a bounded
`WebSelection` current-admission lease. It does not synthesize a
`ResolvedRevision`. Publication currentness is checked again at the response
acceptance boundary. Deleting the route does not revoke an already selected
publication; revoking the publication does.

The control/selection contract in #495 intentionally stops before static
response delivery. The dependent runtime work consumes this selected authority
through the existing node-wide ingress and immutable asset store rather than
creating a per-site listener, renderer or cache.

See the [example template](../../examples/http-application/trigger.json).
Replace its illustrative publication, revision and generation with values from
the intended deployment. The older echo HTTP example remains a structural
Phase 1 declaration. It has no executable profile or application target and is
rejected by this route management API. Other trigger kinds remain declarations.

## Scope, changes and receipts

All RPCs authenticate through the trusted transport context and require the
existing tenant administrator policy. Manifest tenant and publication tenant
must match that principal. Payload annotations and metadata cannot supply an
actor or authorize another tenant. Get returns an absent record for a missing
or foreign ID; Delete cannot remove another tenant's record. Trigger IDs are
unique within a tenant. One canonical authority can be reserved by only one
tenant across HTTP/HTTPS and methods; duplicate method/path/match-kind routes
within that authority conflict. This is catalog ownership, not proof of DNS
ownership. Public exposure still requires the ingress host/TLS policy in #229.

Apply/Delete require `operation.operation_id`, a present
`operation.expected_state_version`, and a present `expected_generation`.
Creation requires generation zero; update/delete require the current trigger
generation. State version comes from Get/List or a committed receipt and is
global to this catalog. Deployment, rollout and binding changes also advance
that fence. The output-only `Trigger.generation` is not a precondition.

The catalog commits the canonical trigger, exact target identity and receipt in
one file replacement. A trigger generation is its creation/update state version.
Application identities retain publication, component, deployment, deployment
generation and immutable revision. Static identities retain publication,
web-manifest digest, asset-tree digest and web publication generation, with no
placeholder execution fields.

Each accepted application request retains its original resolved revision,
component, publication and route generation. Each accepted static request retains
its exact web-publication authority and mount metadata. Later selection captures
the new complete catalog. Already selected work still undergoes the target's
normal current-eligibility check; deleting a trigger does not revoke its
publication. Independent publications or tenants never share grants.

The most recent 64 operation receipts are retained across all trigger scopes.
Within this window, exact replay returns the original receipt and Apply result
without reactivating a deleted route. Reusing an operation ID with different
normalized input, actor or CAS conflicts. Historical lookup is scoped by the
authenticated tenant. `UNKNOWN` includes evicted receipts and is not proof that
an operation never ran. An evicted request's old state CAS prevents silent
reapplication. Do not resubmit an uncertain operation with new preconditions
without inspecting current state. The global receipt window and version
numbers do not grant node-wide inventory access.

Mutations require a configured durable audit owner. Success/error response
capacity and the exact audit attempt are prepared before synchronous commit.
The response reports catalog durability separately from the audit acknowledgement.
Delete retains its original Empty response and adds bounded
`latent-trigger-operation-bin`, `latent-trigger-receipt`,
`latent-trigger-state`, `latent-trigger-generation`, `latent-trigger-replayed`,
and `latent-trigger-durability` metadata, alongside audit metadata. Use the
operation lookup RPC for the full receipt.

## Recovery and resource ownership

Catalog format 7 adds the optional HTTP table. Catalogs without HTTP state retain
their existing format 5/6 encoding. All deployment, rollout and capability-binding
writers preserve the HTTP table under the same catalog transaction fence.
Interrupted staging leaves the previous complete state. After a rename with
uncertain directory sync, memory reflects the same new complete state, but new
HTTP selections and mutations deny until successful recovery. Recovery verifies canonical manifests, target-variant receipt associations and
checksums; it never treats an old receipt as current permission. HTTP table
and receipt format v2 are required. Obsolete v1 tables, receipts and flat
execution fields are rejected without rewriting the stored catalog. Restore a
current-format snapshot or explicitly recreate state using the
[fresh-state procedure](publication-catalog.md#supported-storage-and-fresh-state).
Mixed/corrupt variant records fail closed. Stale or revoked targets remain inspectable and
deletable. Pending trigger audit attempts reconcile through retained receipts;
terminal Unknown audit records are not rewritten.

| Resource | Profile ceiling |
| --- | --- |
| Trigger records | 256, also subject to the byte ceiling |
| Canonical definition | 16 KiB; identifiers 128 bytes |
| Configuration | 6 strings; authority 255 bytes, path 8,192 bytes |
| Labels/annotations | 16 each; keys 128 bytes, values 256 bytes |
| One retained HTTP table | 2 MiB, including conservative decoded/index overhead |
| Current/candidate/retired HTTP metadata and read ownership | 8 MiB shared budget |
| Historical receipts | 64; 4 KiB per canonical receipt |
| List page | Up to 32 records and 128 KiB conservative payload allowance |
| Concurrent read owners | 64, also subject to the shared byte budget |
| Selected deployment attributes | 64 KiB before copying an application target |
| Selected static publication | Existing bounded web-read/current-admission lease; no per-site owner while dormant |

Management settings may impose smaller limits. Page tokens bind tenant, service
filter, page size, catalog transaction and catalog owner. Edits or reopening
invalidate them. Output owners retain charges through deferred encoding and
delayed transport frames. A selected target retains a bounded read lease, and a
prepared update reserves capacity before cloning the table. The existing
catalog's configured state-file/compilation limits separately bound the combined
serialized transaction; these numbers are not process RSS limits.

Dormant triggers retain bounded metadata only. There is no per-trigger listener,
thread, task, execution cell, or guest instance. No bulk/load benchmark is needed
for this metadata and authority contract.
