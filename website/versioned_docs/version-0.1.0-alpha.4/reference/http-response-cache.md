# Bounded HTTP response cache

Issue #232 freezes an opt-in `immutable-public-v1` profile on the shared
[HTTP listener](http-ingress.md). The cache is node-owned, volatile and bounded;
it creates no thread, task, renderer, listener or provider per deployment.
Omitting `httpIngress.responseCache` (or using `[]`) creates no response cache.

## Explicit approval, not application authority

Every application response is sent with **`Cache-Control: no-store`**. This also
applies to platform errors and cache hits: downstream caches cannot reproduce
LSF's complete key or check its current publication authority. The original
application Cache-Control and Age fields cannot override this transport policy.
Set-Cookie is still delivered normally, but makes the response ineligible for
shared storage. Immutable browser assets have a separate ownership/policy path.

To approve a route for local reuse, add an entry to `httpIngress.responseCache`:

```json
{
  "dependencyProfile": "immutable-public-v1",
  "tenant": "examples",
  "publication": "<exact publication ID from admission>",
  "release": "<exact component release digest>",
  "rendererProfile": "buffered-v1",
  "authority": "www.example.test",
  "path": "/",
  "generation": 1,
  "maximumAgeSeconds": 30,
  "vary": [{"name": "accept-language", "values": ["en", "de"]}]
}
```

The angle-bracket IDs above are placeholders, not valid admitted identities.
The closed [approval schema](../../schemas/node-http-response-cache.schema.json)
is referenced by the [ingress schema](../../schemas/node-http-ingress.schema.json).
Native validation additionally checks canonical routes, unique approvals and a
matching configured public-origin tenant/authority. Bearer authentication cannot
be combined with a nonempty cache policy. Configuration is fixed for the node
lifetime; changing/removing an approval requires restart and discards all entries.
Increment its generation when changing the approval's meaning.

The approval is an operator assertion that output depends **only** on immutable
publication content, the configured public principal, the exact URL and approved
finite header values. It must not be granted to renderers whose output depends
on secrets, session state, mutable provider data, ambient time, random values,
trace IDs or deadlines. Grant changes cannot make those dependencies safe for
this profile. A public guest response header is not such an approval. The
platform cannot infer arbitrary application data dependencies or sanitize a
malicious renderer; an incorrect operator assertion remains an application and
deployment security error. Secret-dependent caching and personalized cache
partitions are deliberately unsupported, rather than keyed by secret material.

## Key and current authority

Only bodyless GET requests without a query or Content-Type are eligible. The
host public-origin adapter must supply a Trigger principal with no service or
claims. Authorization, Proxy-Authorization and Cookie presence is recorded
**before** filtering request headers; even an empty cookie disables caching.
Raw credentials never enter the cache or its diagnostics.

The length-prefixed, bounded key contains tenant, exact publication, exact
component release, revision, HTTP renderer contract profile, trigger identity,
route generation, coherent catalog transaction, policy generation, public
principal subject, scheme, canonical authority/path and every approved Vary
field. An exact publication pins the admitted renderer and web asset association,
not merely a shared component digest. Missing and present-empty values are
distinct; repeated fields are not combined. Keys are not truncated or reduced to
a potentially ambiguous unframed concatenation.

Each approved field has at most 16 literal values, each at most 128 ASCII bytes.
Only Accept, Accept-Language and Accept-Encoding are supported. Every header
visible to the application must be in that finite domain; unknown fields,
conditions, Range, request cache directives, unapproved values and duplicates
bypass caching. Consequently ordinary browser requests with additional headers
may deliberately remain uncached. Do not broaden the key by silently ignoring
those fields. Guest Vary may only name approved fields, without duplicates or
`*`; all approved fields are keyed even when the guest omits Vary.

A hit still passes normal tenant authentication/authorization, selected inbound
admission, quotas, request deadlines and current publication eligibility. It
avoids compilation and an execution-cell lease, not admission. The key is also
bound to the sealed lifecycle/signing-policy cache digest, including eligibility
generation. Copying a hit into its exchange occurs under the current release-use
fence. Revocation, quarantine or readmission cannot reuse an old eligibility
entry. A newer observed catalog transaction clears future visibility; late old
requests cannot roll it back. Already accepted reads keep their owned bytes,
consistent with the listener's selection boundary. There is no growing map of
per-application invalidation tombstones.

## Freshness and complete delivery

Only a validated application **200** response with one explicit `public` and
positive numeric `max-age` is considered. Optional numeric `s-maxage` can only
reduce the lifetime. TTL is the minimum of these directives and the policy cap
(1–60 seconds). Unknown or duplicate directives, private/no-store/no-cache,
quoted or malformed ages and zero ages disable storage. No negative caching,
heuristic freshness, revalidation, stale-if-error or stale-while-revalidate exists.

Set-Cookie, credentials, unknown response fields and unbounded Vary disable
storage. The response metadata allowlist is Cache-Control, approved Vary,
Content-Language, ETag, Last-Modified, Content-Security-Policy,
X-Content-Type-Options and Referrer-Policy, plus the separately validated media
type. A restrictive metadata profile is intentional; arbitrary response fields
must not accidentally become retained principal data.

A monotonic Instant starts at cache-request creation. Rendering and transport
delivery consume that lifetime; a late fill is discarded. Lookup never extends
expiry. Hits emit the conservatively elapsed Age. Wall-clock changes cannot
extend TTL.

The exact validated outcome is staged privately under a reservation. Only
`Delivery::finish`, after complete header/body writes and the existing transport
flushes, publishes it. Partial writes, cancellation, timeout, malformed guest
responses, platform failures, dropped futures and shutdown discard the fill.
Completion means local transport acceptance, not proof of browser receipt.

## Resource ownership and observations

| Resource | Fixed bound |
| --- | --- |
| Operator approvals | 32 exact routes; 3 fields, 16 values/field |
| Key | 8 KiB, rejected before growth beyond the reservation |
| Live entries, including pending fills and retired reads | 32 and a 16 MiB entry-reservation ceiling |
| Entry reservation | 2 MiB wire frame + 8 KiB key + 512 bytes owner/index allowance |
| Parsed response | Existing 256 KiB body, 64 headers and 16 KiB header bytes |
| Concurrent cache request/fill/read owners | 64, each additionally charged 8 KiB + 512 bytes |
| Expiry | At most 60 seconds from request creation |

The live entry budget is conservative: even small responses reserve the maximum
entry allowance, so the byte ceiling can bind before the entry-count ceiling.
The index is preallocated. Reservations precede key/body allocation. Eviction
removes visibility but cannot refund a retained read or unpublished fill; new
fills bypass when all capacity remains owned. There is no fill wait queue or
unbounded coalescing map. Policy data and index capacity are bounded fixed node
configuration; exchange copies remain charged to the existing HTTP pool.
These are user-space ownership allowances, not a whole-process RSS guarantee.

`http_snapshot()` exposes `responseCacheEntries`, `responseCacheOwners` and
`responseCacheReservedBytes`, without per-route labels or private key contents.
Entries include unpublished and retired-but-owned data, not just index hits.
Draining closes the cache before joining owners. A clean HTTP shutdown requires
zero retained cache entries, owners and reservations in addition to existing
connection/exchange reclamation.

Run `cargo test -p latent-ingress --lib http::cache` for deterministic isolation,
finite Vary, no-store, delivery/drop, generation, expiry and churn regressions.
The tests drive the real collector/codec/delivery owners; mocked cache metadata
alone is not evidence for transport or renderer behavior. Use the ordinary
workspace and real HTTP-component checks from [VALIDATION.md](../../VALIDATION.md)
for node integration. No new always-on issue-specific workflow is required.
