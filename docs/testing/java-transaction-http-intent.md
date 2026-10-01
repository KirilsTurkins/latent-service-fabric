# Java aggregate with a deferred HTTP intent

The maintained `tools/java_transaction_schema.py --effect put-once` variant
stages one actual `Intent` through `latent:intents/staging@0.1.0` after staging
its aggregate write. Use it with each of `legacy-v1`, `compatible-v2` and
`writer-v2`. The host commits state, intent and original result together; a
declared rejection after staging must retain the rejection and discard both
business writes and intent. Neither staging nor commitment is remote delivery.

The effect requests logical binding `qualified-http`, operation `put-once`, and
these exact 27 bytes: `java-aggregate-put-once-v1` followed by one NUL byte. Media
is `application/octet-stream`, metadata is empty, and requested expiry is absent.
The captured application budget permits one intent and retains zero outbound
HTTP and child calls. The same original read supplies the opaque NV2 view and
optional SV2 key observation; none of these fields describe a committed token.

The creator captures `deferred-http-requirements.json`. Normal source packaging
includes those exact bytes as an `application/json` Asset beside the unchanged
`transaction-binding.json` Asset. Its `companionDigest` binds the original raw
companion bytes. Existing source, component, package and signing observations
must cover the new variant; an older event-variant receipt cannot qualify it.
The requirements describe application expectations and authorize no rule,
provider, credential, namespace or deployment.

The trusted node composition must install the shared
[`QualifiedHttpEffectAdapter` and `PutOnceContract`](https://github.com/KirilsTurkins/latent-service-fabric/blob/cc797f977d67ae939cba7997d0dc9eabfd56909e/crates/latent-http/src/effects.rs).
Use the existing `HttpProvider`, protected `ProviderCredential` and original
`EffectTimeSource`. The contract accepts one approved HTTPS origin, static
resolution, no guest headers and no redirects. The operator supplies the actual
tenant, provider ID, endpoint incarnation and qualified TLS/deduplication peer;
the guest never selects an address. Derive the `DispatchProfile` from the
installed adapter, including its actual public configuration and endpoint
incarnation. Do not reconstruct its destination digest in authoring tools.

| Native installation field | Required value |
| --- | --- |
| Adapter / operation | `qualified-http-put-once-v1` / `put-once` |
| Intent / payload / idempotency format | `1` / `http-put-once-bytes-v1` / `retained-put-once-v1` |
| Contract retention horizon | 600000 ms |
| Contract body / retry delay | 27 bytes / 10 ms |
| Dispatch payload / response ceiling | 27 bytes / 2048 bytes |
| Dispatch attempts / original age ceiling | 3 / 600000 ms |
| Individual attempt timeout | 2000 ms |

Publish an authenticated `EffectRule` for the original admitted tenant,
`transactional-aggregate` namespace and incarnation, exact publication, logical
binding and operation. Its profile comes from that same adapter. Policy
revision, credential epoch and protected credential reference come from current
native owners, and every actual attempt intersects the captured ceiling with
current authority. The original horizon survives lost waiters and restart;
invocation deadlines and new publications cannot extend it. Missing installation
or authority fails concretely. A requirement Asset alone cannot enable dispatch.

The shared protected dispatcher owns the effect after the atomic coordinator
accepts it. Use its retained send marker, bounded receipt/status lookup,
deduplication contract, physical owner retirement and reopened store fixtures
for response loss and crash cases. Inspect the peer's durable counter and exact
effect identity to distinguish attempts from mutations. Do not retry an unknown
command, infer remote nonexecution from a timeout, or keep a Java Store or cell
for pending work. Signed Java atomic execution and the actual two-version
recovery campaign remain separate evidence from these captured source inputs.
