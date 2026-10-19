# Compiler-owned buffered fetch candidate

The first signed-runner attempt on head `b951ef8184c4c40bef55f3d69247d58bcd71fff4`
passed enforced runtime/HTTP grant denials and its no-I/O async entry, then failed
the first JSON invocation with a known, reaped `unreachable-code` guest trap and
zero outbound/child/mutation effects. This does not identify its source cause or
qualify HTTP behavior. The runner now adds a no-HTTP Request-construction control.
Its fixture can return only fixed Request/fetch/body-stage and error-class tokens
when a JavaScript operation throws; it never serializes the exception, message,
URL or credentials. Every diagnostic value still fails the original exact signed
success assertion. A hard native trap remains a trap, and all provider, body-use,
effect, idle-owner and cleanup checks remain required.

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
| Bodies | Null, UTF-8 strings, ArrayBuffer, ArrayBuffer views and native URLSearchParams; input bytes copied, including view offsets. Null bodies stay unused; non-null bodies are one-shot. |
| Consumption | Buffered `text`, `json`, `arrayBuffer` and independent buffered clones. JSON parsing errors stay parsing errors. |
| `Headers` | Records or iterable pairs, case normalization, validated names/values, duplicate combination, sorted iteration, get/set/append/delete/forEach. Fetched response headers are immutable. |
| Media/idempotency | Content-Type and Idempotency-Key map to the existing dedicated typed metadata. An idempotency key grants no retry. |
| HTTP failures | HTTP status remains a response; transport rejection retains the original error as `cause`, and `uncertain` remains explicit. |
| Redirects | At most five GET/HEAD follow-ups, each a new authorized/charged call; cross-origin follow-ups remove every guest header. No mutation redirect/replay. |
| Abort | Each Request and clone owns a native dependent signal, preserving the original reason without sharing signal identity. An already-aborted signal makes zero calls. Later abort rejects and prevents further transfers after the pending call settles; accepted work retains capacity until cleanup. |

Request body replacement follows the [Fetch Standard's constructor order](https://fetch.spec.whatwg.org/#dom-request): an explicit non-null body supplies fresh bytes even when the input Request was consumed. It leaves the input body unchanged. Without a replacement, a successful construction transfers the unused input body exactly once. Rejected construction, including a GET/HEAD body, does not consume an otherwise unused input. A null or omitted replacement cannot revive a consumed body. Cloning still rejects a used body.

Native `URLSearchParams` bodies use the [Fetch Standard's body extraction](https://fetch.spec.whatwg.org/#concept-bodyinit-extract): the existing runtime's native URL-encoded serializer supplies the bytes, with duplicate/order, space/plus and UTF-8 encoding retained. Request and Response constructors copy the encoded bytes immediately; later parameter mutation cannot change a request or clone. An absent Content-Type becomes `application/x-www-form-urlencoded;charset=UTF-8`; explicit media types are preserved. The original 1-MiB ceiling applies to the encoded bytes, and upload chunks remain at most 64 KiB. GET/HEAD still reject even an empty non-null form body. Body extraction does not call an overridden per-object stringifier/iterator or accept a forged tag, and adds no method/destination authority, retry or replay. This is a finite body-type source/reference control, not emitted-component, native URL implementation or signed POST qualification. Streaming, FormData and Blob remain unsupported.

Ordinary encoding, copied-body consumption and media types have Node reference controls. The internal-list control follows the Fetch Standard separately: Node 24.19.0 calls an overridden per-object stringifier, while this profile uses the captured native serializer.

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
and `getSetCookie` reject explicitly.
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
Pure `Headers`/`Response` construction and global API lookup are available for
module initialization. Top-level `new Request(...)` remains unsupported: every
Request creates a dependent native AbortSignal, whose mutable listener/weak-link
graph requires invocation admission. The engine refuses that graph while Wizer
creates a shared snapshot; the Fetch construction fixture must not bypass or
weaken this refusal. Request construction is exercised inside the async export
instead. Arbitrary Request-constructing dependency initializers are therefore
still an unmet #691 compatibility boundary. No request, credential, active
Promise or live host resource enters the initialized component snapshot. Each
invocation receives fresh mutable module/client state.

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

The `Actual source-owned Fetch component construction` workflow job now consumes
the exact same-run source-built import engine and compiler splicer. It runs the
maintained compiler on an outside-checkout project with ordinary global lookup
in direct and transitive module initializers and a real async typed HTTP import.
The fixture includes direct/transitive `Headers`/`Response` constructor assertions
and verifies transitive `Request`/`fetch` availability without snapshot-time native
signal admission. Its report does not independently observe whether those
initializers executed inside the componentizer. A focused Node adapter control
models the native signal admission boundary: initialization admits no signal or
provider work, top-level Request construction still refuses, and invocation
constructs a real Request and consumes the typed response. That control is source
evidence, not an emitted-component/provider run. The
compiler performs generated-declaration typechecking, component validation and
decoded public-type comparison. It retains the actual component, selected backend and
bootstrap digests, exact engine/splicer inputs, and before/after source/compiler
identities. It builds no second engine or native node and preserves the existing
job deadlines and guards.

The final decoded type comparison retains the complete application HTTP,
clock and export graphs. For the authenticated source-owned import profile,
the engine-owned activation interface has two finite accepted encodings: the
complete maintained ABI, or exactly its eight used functions and three types.
Component encoding can omit only the unused `observe`, `wait-for`, `wait-until`
methods and their exclusive `phase`/`observation` types. The complete original
ABI fingerprint, engine/profile and source-splicer receipt identity are checked
before accepting that alternative. Missing mandatory members, changed retained
signatures/ownership, partial omissions, unknown imports and public-contract
changes still fail. The source/derived-world check remains complete and strict;
this representation check grants no authority or runtime qualification.

The compiler namespace and containment receipts retain a compact digest of every
field in their complete canonical JSON manifests. The namespace summary also
records file count and total content bytes. The compiler still enforces its
original 32,768-file / 1-GiB bounds and compares the full in-memory identities;
the qualifier additionally requires identical before/after summaries. This keeps
the fixture writer's 256-KiB limit unchanged even when an input manifest is larger.

The new job is a qualification attempt until its exact-head hosted result is
verified. Its report deliberately distinguishes component construction from
runtime execution: it does not invoke the async export, sign or admit a component,
contact a real provider, or run unchanged published/private clients. Those gates,
the HTTP/Abort/body/lifecycle matrix and physical cleanup remain required; engine
support stays `unknown` / `not-evaluated` after a successful build.

## Synthetic response factories

The buffered profile supplies `Response.error()` and
`Response.redirect(url, status = 302)` from the automatically installed Response
class. These are pure response constructors: they contact no provider, follow no
redirect and confer no request authority. `error()` produces status 0, type
`error`, an empty immutable header list and a null body; public `new Response`
still requires status 200 to 599. Both factory results and their clones retain the
immutable header guard. Reading a null body returns empty bytes/text without
marking it used; parsing that empty text as JSON still rejects.

`redirect()` accepts strings and objects with a string-returning `toString()`,
including a URL object supplied by a compatible selected library. It supports
absolute HTTP(S) URLs under the existing 2048-character
serialized URL bound. It preserves the serialized Location, including its
fragment, and accepts only redirect statuses 301, 302, 303, 307 and 308 after
[Web IDL unsigned-short conversion](https://webidl.spec.whatwg.org/#abstract-opdef-converttoint).
There is no ambient base URL or non-HTTP redirect profile. The object has a null
body, empty response URL, `redirected: false` and type `default`, as prescribed
by the [Fetch Response factories](https://fetch.spec.whatwg.org/#response-class).
It does not enable manual/opaque redirect responses or change fetch's existing
bounded follow policy, credential stripping, grants or uncertainty behavior.
A provider failure remains a rejected fetch Promise, never a fabricated success
or an automatic `Response.error()` return.

Focused controls compare ordinary statuses, URL serialization, null-body reads,
clones and immutable headers with pinned Node. Normative Web IDL controls are
separate: ToNumber rejects BigInt and unsigned-short modulo wraps negative
values nonnegatively. Node 24.19.0 differs on those two edge cases, so no Node
parity is claimed for them. Source/mock controls do not establish signed engine,
component/provider, unchanged-library/private-consumer or lifecycle/cleanup
qualification; those #691 requirements remain open.
## Prepared signed-provider runner

`tools/qualify_typescript_fetch_runtime.py` adds a finite execution attempt after
the actual construction gate. It uses the normal outside-checkout TypeScript
project, normal package/build observation, explicit demo signing and enforced
node admission. The hosted lane consumes the same run's source-owned engine and
splicer and the exact five native products already built by the maintained
TypeScript boundary job. It does not build another engine or node. Downloaded
native products must match that successful qualification's complete current
source capture and binary identities; the separate ordinary-tuple CLI path
retains its existing feature/ABI/version checks.

The new fixture uses ordinary automatically installed globals in both direct
and transitive modules. Pure `Headers`/`Response` initialization stays in the
snapshot; `Request` and its native signal graph are constructed during the
invocation. A real async export checks entry, GET JSON, HTTP 404 as a response,
one-shot buffered `json()` consumption and a fresh per-activation counter.
Before the first HTTP call, additional no-HTTP controls exercise a real
thenable/Promise/await chain and a copied Request's AbortSignal listener plus
that same chain. These isolate the native asynchronous/object boundary; they
do not make a failed JSON call successful. The original typed results and
physical retirement assertions remain mandatory. A separate manual same-SDK
experiment can reuse the authenticated earlier SDK engine/compiler/native
products and compile only the new application. Its receipts explicitly name
that older SDK tree and never qualify the current PR head; no private-frame
observation or aggregate diagnostic-job success supplies signed Fetch proof.
Missing runtime and HTTP grants must refuse before execution with no outbound,
child or mutation effects. The peer must observe exactly three authorized GETs,
and every completed control must leave the observed topology, cleanup slots and
all 18 physical provider counters idle before clean node/peer reaping.

The fixture keeps the existing TypeScript 1,000,000,000-fuel / 128-MiB /
120-second invocation budget and one outbound request. Its private provider
allows only the exact primary origin and GET `/conformance/json` and
`/conformance/status/404`, with 8-KiB responses, 64-KiB read/chunk capacity and two
outstanding chunks. The capacity matches the existing adapter's 65536-byte read
request and the provider profile's finite maximum; the previous 4-KiB capacity
would reject that read before polling the body. Total response bytes stay at
8 KiB, and the original I/O ledger reserves and charges capacity before
transport work. This fixes a separate runner-profile mismatch, not a proven
cause of the earlier zero-outbound first-JSON trap. Activation owner ceilings
match the maintained TypeScript local-service
experiment (16 tasks, 2 executors, 16 queued work, 8 waits/timers/results and
64 native owners). These are finite experimental limits, not new platform
defaults or native allocator/kernel upper-bound evidence.

The selected-source programme below has actual finite signed execution. Local
controls alone exercise the JavaScript adapter and peer/evidence predicates;
they do not execute a Wasm component. The recorded run uses its explicitly
historical native/engine tuple, rather than qualifying the final integration
head or every current product. A finite run does not qualify two unchanged
published clients, a private consumer, top-level `Request`, streaming/tee,
Abort/timeout races, reaction/timer/memory limits or cross-tenant reuse. The
engine metadata remains `unknown` / `not-evaluated`; #691 remains open.

The source-owned import compiler fuses its private carrier lift with the typed
binding's existing await. It rejects an unrecognized generated helper/task/finally
graph. This removes a redundant compiler Promise while preserving task entry,
canonical argument/result handling, application-realm Promise projection and
actual import retirement in the existing finally path. Local controls use an
actual retained generated `open` binding, including pending work, original native
rejection, typed `uncertain` and lift failure. These controls alone establish no signed result. The historical Task-owner
refusals remain real failures; the separate recorded candidate below succeeds
under those same owner limits.

The selected source-splicer adapter avoids an idle `await null` only when the
actual private `AsyncTask` is first in the queue. Other callers and contended
slots keep their asynchronous wait. The actual exited flag is checked before
slot admission and again after the preserved public `Task.enter` await, so
closing between these boundaries cannot grant entry. Existing task, queue,
native-owner, authority and invocation bounds are unchanged; no pending work
is settled or refunded early. Authentic generated-source controls preserve
closed first/middle refusal, entry races, live ordering and the retirement-gap
case. Node-reference allocations fall from 10 to 8 for idle entry; this count
is not LSF owner accounting or a signed Fetch qualification result.

The same finite adapter also inlines only the authenticated native task-metadata
wrapper at its existing typed import await. It retains argument validation,
real contention wait/relock, error propagation and finally-clear, while avoiding
a second private async Promise around work already awaited by the public async
binding. Framework callbacks and application-export wrappers stay unchanged. Unknown wrapper text,
call shapes and captured local names reject. Actual generated-source controls
cover pending success, native rejection, typed/lift failure and contention.
These controls alone establish no signed result. The unchanged finite
ordinary-host gate remains mandatory and has the source-bound result below.

## Actual selected-source signed result

[Run 39322249065, job 118298975151](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39322249065/job/118298975151)
passed the ordinary signed gate with candidate source
`819791f66b2d2fcbe38f2f04259af249f98cfacb`. Entry, Request readiness, the
Promise chain, Request copy, JSON, HTTP 404 and fresh-activation controls passed.
Missing runtime and HTTP grants both refused with zero guest fuel/outbound work.
The peer saw exactly three requests, every post-call retirement check passed,
and the node shut down cleanly. No private observer replay ran.

The [bounded receipt](../testing/evidence/typescript-fetch-signed-owner-slots-2026-10-19.json)
binds the actual 12,398,840-byte component, generated bindings, source overlays
and original five native products. Its SDK/native-engine source is
`0754391a20027a539f1d5b7c0426719a4bd6c3c1`; the four compiler/backend overlays
are identified separately and all original source/products were rechecked
before and after restoration. This is a real finite positive under unchanged
bounds, not a new qualification of the final development integration. The
remaining #691 criteria and engine `unknown` / `not-evaluated` metadata remain.
