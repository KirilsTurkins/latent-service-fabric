# Compiler-owned buffered fetch candidate

The source candidate `lsf-fetch-buffered-v1` installs `fetch`, `Request`,
`Response` and `Headers` before application and dependency module initialization.
It is selected automatically when the project explicitly selects
`spidermonkey-activation-promises-clocks-imports-v1` and its WIT world imports
`latent:http/streaming@0.3.0`. Dependency coordinates and catalogue entries do not
select the backend. The ordinary synchronous profile is unchanged.

This is implementation and native JavaScript semantic evidence for
[#691](https://github.com/KirilsTurkins/latent-service-fabric/issues/691), not a
qualified release or completed ticket. Actual compilation with the exact native
engine/source-built splicer, signed provider execution, unchanged published and
private client libraries, and physical cost/cleanup measurements remain required.
The engine selection continues to say `unknown` and `not-evaluated`.

Use the existing [captured npm workflow](typescript-dependencies.md) and
[source-owned runtime inputs](typescript-import-runtime-candidate.md). Declare
the typed capability in the application's ordinary WIT world:

```wit
import latent:http/streaming@0.3.0;
```

Application and dependency code then use the global APIs directly:

```ts
const response = await fetch('https://api.example.test/items');
if (response.ok) return await response.json();
throw new Error('HTTP status ' + response.status);
```

The operator must separately install streaming HTTP and grant the exact
destination, method and path. Runtime selection, declarations and generated
requirements grant no authority. No application transport, executor or polyfill
is required by this source path. A missing grant/provider remains an actual
typed provider failure, with no socket fallback.

## Finite API boundary

| Surface | Candidate behavior |
| --- | --- |
| `fetch` | Real Promise over async typed open/write/finish/read calls. Resolves after the complete bounded body, including for HTTP 4xx/5xx. |
| `Request` | Absolute HTTP(S) URLs without embedded credentials; fragments removed; GET, HEAD, POST, PUT, PATCH, DELETE and OPTIONS. A body is forbidden on GET/HEAD. |
| Bodies | Null, UTF-8 strings, ArrayBuffer and ArrayBuffer views; input bytes copied, including view offsets. Null bodies stay unused; non-null bodies are one-shot. |
| Consumption | Buffered `text`, `json`, `arrayBuffer` and independent buffered clones. JSON parsing errors stay parsing errors. |
| `Headers` | Records or iterable pairs, case normalization, validated names/values, duplicate combination, sorted iteration, get/set/append/delete/forEach. Fetched response headers are immutable. |
| Media/idempotency | Content-Type and Idempotency-Key map to the existing dedicated typed metadata. An idempotency key grants no retry. |
| HTTP failures | HTTP status remains a response; transport rejection retains the original error as `cause`, and `uncertain` remains explicit. |
| Redirects | At most five GET/HEAD follow-ups, each a new authorized/charged call; cross-origin follow-ups remove every guest header. No mutation redirect/replay. |
| Abort | Each Request and clone owns a native dependent signal, preserving the original reason without sharing signal identity. An already-aborted signal makes zero calls. Later abort rejects and prevents further transfers after the pending call settles; accepted work retains capacity until cleanup. |

Request body replacement follows the [Fetch Standard's constructor order](https://fetch.spec.whatwg.org/#dom-request): an explicit non-null body supplies fresh bytes even when the input Request was consumed. It leaves the input body unchanged. Without a replacement, a successful construction transfers the unused input body exactly once. Rejected construction, including a GET/HEAD body, does not consume an otherwise unused input. A null or omitted replacement cannot revive a consumed body. Cloning still rejects a used body.

`Headers` accepts two-item iterable pairs as well as arrays and records. Omitted
or undefined initialization creates empty headers; null and other primitive
initializers reject. A pair must contain exactly two items: the candidate stops
at a third item and closes the active iterators instead of consuming an unbounded
malformed pair. Iterator errors retain their identity, and profile-limit failures
also close the outer iterator. Focused Node reference and typed-adapter controls
cover this constructor boundary; signed component qualification remains separate.

The source profile caps each buffered body at 1 MiB, each transferred chunk at
64 KiB, headers at 64 entries/32 KiB, URLs at 2048 characters, and outstanding
operations at 16 per fresh activation. The guest heap, original deadline and
provider limits remain additional bounds; these constants are not measured
native/kernel memory reservations. Response buffering retains the incoming
parts and combined/copied buffers inside the charged guest heap.

The typed streaming provider never redirects automatically. The fetch layer
does not retry connection or mutation failures. A library may issue additional
calls; each is independently authorized and charged. Cancellation, a read error
or local close cannot establish remote rollback. Abort rejection keeps the
original reason identity and must not be interpreted as proof of no dispatch.

The wrapper copies materialized chunks into independent guest-owned buffers
before dropping their canonical owner, and drops the body after
EOF/error and an unconsumed upload after failure. Finish consumes an upload
before its possibly failing call; it is never dropped again. Cancellation does
not drop a resource during an outstanding borrow. Aborted operations continue
their registered cleanup after public Promise rejection, retain their place in
the 16-operation bound, and cannot create new transfers or redirects.
Terminal traps and expired roots still require the runtime/provider's actual
Store-destruction and quarantine mechanisms; native wrapper tests cannot qualify
those mechanisms.

## Explicit unavailable behavior

This buffered candidate is not a browser or Node environment. Non-null `.body`
stream access, Blob/FormData bodies, stream readers, tee, streaming uploads,
`getSetCookie`, `Response.error` and `Response.redirect` reject explicitly.
Fetch resolves after complete buffering, so it does not expose header-first
resolution or network backpressure to application readers. The typed contract
has no HTTP reason phrase: fetched `statusText` throws a technical unsupported
error rather than inventing one. Constructed responses preserve their supplied
status text.

Only the default `cors` mode is accepted; it supplies no browser-origin/CORS
enforcement. There is no ambient cookie jar, authorization, proxy, cache or
connection state. `credentials: 'omit'` and the default `'same-origin'` therefore
send no guest ambient credentials. Explicit protected provider credentials remain
operator-owned at each separately authorized destination. Credential/framing
headers, including Authorization, Cookie, Host and Content-Length, are rejected
before contact instead of being silently removed or forwarded.

Non-default cache/referrer/integrity/keepalive/duplex settings, credentials
`include`, other modes and unknown RequestInit fields reject explicitly.
`redirect: 'manual'` can produce an ordinary non-redirect response, but encountering
a redirect rejects because the typed API cannot express an opaque-redirect
response. `redirect: 'error'` rejects at a redirect too. Mutation redirects reject
after the original response, preserving the fact that the original mutation may
already have occurred.

Snapshot-time network use fails before Promise or provider work is admitted.
Ordinary construction/lookup is available for library initialization, but no
request, credential, active Promise or live host resource enters the initialized
component snapshot. Each invocation receives fresh mutable module/client state.

## Checks and remaining qualification

`python -m unittest tools.tests.test_typescript_fetch` exercises actual native
JavaScript Promise and body semantics against deterministic typed-transport
controls. The controls test pending work, before/after-dispatch abort, retained
capacity, chunk/body destruction, HTTP errors, uncertain failures without replay,
redirect isolation and oversized/truncated bodies. They intentionally do not
claim to execute an LSF provider or emitted component.

The compiler captures the backend/declarations as recipe inputs, checks vendored
declaration identity, records the selected backend and bootstrap digest, and
installs it before dependency code. That records actual selected source rather
than runtime support. #691 remains open for actual engine/component/provider,
two unchanged clients/private-dependency controls, broader lifecycle/exhaustion
and measured ownership evidence. The independent approved socket profile remains
owned by #737–#740.
