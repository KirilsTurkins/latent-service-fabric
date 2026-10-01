# Qualified HTTP effects

The `qualified-http-put-once-v1` adapter supports one operator-approved endpoint
contract, [latent.http-effect.put-once.v1](../../contracts/effects/http-put-once-v1.json).
An ordinary HTTP mutation or an `Idempotency-Key` header does not qualify an
endpoint. The trusted composition supplies `PutOnceContract`, the existing
configured `HttpProvider`, its protected `ProviderCredential`, and the protected
effect clock to `QualifiedHttpEffectAdapter::new`. Install the returned adapter
in the existing `EffectRuntime` / `DispatcherOwner` before readiness. Installing
this native port grants neither a guest HTTP capability nor a dispatch rule.

The exact destination profile binds the HTTP configuration digest, tenant,
provider identity, endpoint deduplication incarnation, body bound, approved
horizon and retry delay. The current `EffectRule` must select that profile,
namespace incarnation, publication, binding and `put-once` operation. It names
the protected credential reference and epoch, with finite payload, response,
attempt, age and timeout ceilings. A restored or replaced deduplication history
needs another provider incarnation; old retained intents cannot select it.
Operator approval must establish the endpoint obligations below before this
contract is installed. A declaration alone cannot establish them.

Only one exact HTTPS origin with static, explicitly approved peer addresses is
accepted. Existing TLS hostname/root checks, destination and special-address
checks, pooled connection ownership and protocol buffer accounting apply.
Dynamic DNS, redirects, extra origins, guest headers, streaming profiles and
response content encoding are outside this closed profile. The adapter uses
existing resource-only maintenance permits beneath the sealed dispatch grant;
these permits provide physical ownership and confer no guest authority.

The immutable request is an `application/octet-stream` value with no metadata,
at most 65,536 bytes. The sole mutation is `PUT /latent-effects/v1/{effect}`;
the effect is the original committed lowercase 64-digit identity. The adapter
sets `Idempotency-Key` to it and sends `X-LSF-Effect-Contract`,
`X-LSF-Effect-Body-Sha256`, `X-LSF-Effect-Provider-Incarnation` and
`X-LSF-Effect-Retain-Until`. The body hash covers the exact HTTP body, while the
existing retained payload codec independently binds its media type and bytes
to the committed authority. The original retention cutoff is the minimum of
original commit time plus the configured horizon and original effect expiry.
It never moves forward on retry or credential rotation.

Authentication is `Authorization: Bearer TOKEN`. The token is currently resolved
from the existing protected provider reference immediately before each request.
It contains 1–1,024 ASCII letters, digits or `-._~+/=`. The adapter marks the
header sensitive, retains a zeroizing bounded copy only during the physical
request, and persists no credential bytes. Same-reference secret rotation uses
the current secret generation. Pause dispatch while replacing the credential
binding/epoch and publishing the matching effect rule; mismatched epochs fail
closed. Namespace or publication revocation fences new adapter acceptance.
Already accepted physical work remains owned until retirement.

The endpoint atomically reserves effect identity, exact body hash, provider
incarnation and original cutoff with its mutation and bounded receipt. Within
that original horizon, equal-key equal-body replay returns the original receipt
without another mutation. A changed body, incarnation or cutoff returns 409
without mutation. Every request checks the cutoff before mutation, including
after an old record has been removed. A read-only `GET` at the same exact path
checks the same identifying headers and returns the retained receipt or durable
exclusive reservation; it never performs the mutation.

Receipts are closed JSON objects of at most 1,024 bytes, with exact
`Content-Type: application/json` and `Cache-Control: no-store`. They contain
`contract`, `effect`, `bodySha256`, `providerIncarnation`, canonical decimal
`retainUntilUnixMillis`, `state`, and optional `receipt`. An `applied` object
requires status 200/201 and an opaque lowercase 64-digit receipt. A `reserved`
object requires status 200/202/503 and an absent/null receipt. Reservation means
a durable exclusive reservation for these exact bytes and horizon, not an
arbitrary server retry suggestion. Unknown fields, contradictory identity,
encoding, authentication challenges, cookies and redirects cannot acknowledge
an effect. The sealed response ceiling must cover two 1,024-byte receipt buffers.

Synchronous acceptance only checks immutable metadata and reserves bounded
buffers/provider permits. It performs no DNS, credential lookup or network I/O.
The fixed dispatcher first persists its send marker in the existing protected
database, then polls the accepted operation. Both transport deadlines are
shortened to the remaining original remote horizon when it ends sooner than the
original grant deadline. The PUT gets half that remaining interval, leaving time
for at most one status lookup. Both connections physically close before the adapter
returns its bounded receipt. The worker retains its original context and state
pin; dropped callers, local claim expiry or shutdown timeout cannot release it
or authorize a concurrent resend. An unclean shutdown keeps ownership visible.

| Observation | Durable outcome | Automatic retry evidence |
| --- | --- | --- |
| Transport proves no HTTP write started | Known failure before send | None supplied by this adapter |
| Qualified endpoint returns 400/401/403/409 | Known remote failure | None |
| Exact applied receipt from PUT or GET | Provider acknowledged | None needed |
| Exact durable reserved receipt within original horizon | Known failure | Qualified same-body, same-incarnation deduplication proof; existing dispatcher enforces attempts/expiry |
| Possible write followed by timeout, lost/malformed/oversized response or 5xx | Perform one qualified GET | No retry until the lookup supplies a valid applied/reserved receipt |
| Lookup absent, expired, denied, redirected, malformed or unavailable | Uncertain; explicit reconciliation | None |

Generic HTTP remains unsupported. For uncertain work, pause its dispatch and
inspect the original effect, body hash, provider incarnation, cutoff and bounded
attempt history against the endpoint's durable receipt/counter. Absence is not
permission to issue a replacement mutation. If history cannot resolve the
outcome inside its qualified horizon, retain the unresolved effect for the
existing operator reconciliation workflow. Do not change payload, identity,
incarnation or deadline to manufacture a retry.

The maintained conformance fixture lives in
`crates/latent-http/src/tests/effects/{endpoint,proxy}.rs`. Endpoint version 1 uses
the selected atomic storage engine to flush its mutation counter and receipt
together, then reopens that actual database for inspection. Proxy version 1
forwards to one fixed TLS backend and discards exactly one response after the
remote flush, or drops one request before forwarding. These are test tools;
neither is a production server backend. The real TLS tests are registered under
`latent-http.lib.latent-http` in `tools/ci/suites.json`. They compare actual PUT/GET
attempts with the durable mutation count, including identical replay, changed
body, reservation retry, expired/absent history, late requests after expired
history removal, unsafe replies, revocation and
caller loss during send/read. Protected-owner tests cover durable send-marker
ordering and a reopened database after a crash before that marker. Test-source
identity and results must accompany qualification; a synthetic endpoint pass
does not certify arbitrary commercial APIs or production entry gate #240.
