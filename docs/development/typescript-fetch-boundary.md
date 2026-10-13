# TypeScript fetch boundary work

The follow-up to the signed runtime delivery in PR #923 implements #691 over the
current typed HTTP capability. Its source branch is separate while that PR's exact
head is being checked. No standard fetch profile is installed or qualified by this
source branch.

The bounded header module implements ordinary construction, ByteString and token
validation, HTTP whitespace normalization, duplicate values, sorted iteration,
mutation and separate Set-Cookie values. Native Node reference comparisons pass.
Response headers can be made immutable. The source profile limits a header list
to 128 entries and 32 KiB; failed changes retain the original list. Header
construction grants no network authority and never invents cookies or credentials.

The next source milestone adds finite Request/Response bodies (strings, copied
BufferSource bytes, URLSearchParams and available Blob objects), a 16 MiB body
ceiling, single-use/locking behavior, finite-body transfer and cloning, standard
response/status helpers, and immutable native response headers. HTTP 4xx/5xx
header success remains a Response. Native bodies use 16 KiB pulls with zero
prefetch, retain chunks until materialization returns, and close the real body
after verified EOF. Invalid metadata and bodyless statuses still discharge their
accepted body owner. Stream request bodies, FormData encoding/decoding and native
body cloning remain explicit unsupported operations in these uninstalled sources.

The internal body seam requires each canonical operation's result, cancellation
handle and separate physical retirement completion. Logical rejection permits no
chunk/body drop. It retains the original failure and cleanup failure separately,
refuses resource drops after failed retirement, and does not silently retry a
failed destructor. The reference and controlled callback tests check this source
ordering only; their callback completions are not native/provider evidence.

The semantics follow the [Fetch standard](https://fetch.spec.whatwg.org/#headers-class).
These reference controls establish the header source behavior only. They do not
replace actual signed component, provider or unchanged-library qualification.

The remaining integration must install SDK-owned fetch/Request/Response/Headers
before dependency initialization and lower operations through canonical typed HTTP.
It must preserve the original application contract and ordinary synchronous path,
capture the precise runtime/global/patch identities and leave grant/provider
decisions with the existing host owners.

Canonical streaming HTTP 0.3 is required for actual response-body ownership and
backpressure. Buffering the complete response before fetch resolves would not
establish the required headers/body timing. Cancelling an AbortSignal while a body
read holds a canonical borrow also requires native import cancellation and genuine
physical terminal/drop acknowledgement. A Promise race does not discharge that
borrow, provider or body owner. Unsupported clone/tee/browser features must fail
explicitly until their supported behavior is implemented and qualified.

Concrete authority boundaries also remain in the current provider. Its header
validator reserves Authorization/Cookie and transport-controlled names, requires
each application header to be destination-approved, rejects duplicate names,
and bounds capacity. The eventual adapter must combine ordinary duplicate values
and map Content-Type/idempotency metadata to their existing typed fields; it must
not remove a denied credential header to conceal rejection. Typed header values
are UTF-8 strings, while standard Headers uses ByteString values, so non-ASCII
wire encoding needs an explicit supported mapping or rejection. Header objects
do not bypass these provider decisions.

Acceptance still includes two unchanged independently maintained default-fetch
consumers, an outside-checkout private/local package and identity/catalogue
changes, plus the real #680 provider and cancellation/ownership matrix. The
successful original 26-case runtime tuple and all earlier failures remain retained
under the PR #923 worktree; this follow-up does not amend those receipts or close
#691, #745 or #685.

The private C++ bridge now stages `retired(id)` as a lazy intrinsic Promise for
the accepted import record. It resolves only after the record, JS captures and
lowered buffers are destroyed and both native retirement acknowledgements
succeed. Ordinary imports allocate no additional Promise. Cancellation with the
captured retirement identity preserves logical rejection separately from this
completion; the idempotent retired path also verifies native issued-id and
failed-acknowledgement state instead of trusting a fulfilled JS value alone.
The original 64-object/resource ceilings and original one-argument cancellation
path remain intact.

The new native fixture cases cover typed-lift retirement, cancellation with a
physically pending borrow, identity/unissued-id rejection and actual JS bridge
arity. The 19 existing import-source controls passed; all 31 native selectors now
pass in the exact pinned SpiderMonkey/WASI fixture below. The compiler's explicit
fetch source selection binds the operation ID/result/retirement handle and
separate fetch world. A fresh ordinary import core and source splicer have built,
while installed fetch still requires its additional URL owner and genuine
ordinary/signed borrowed-read/cancel/drop/reuse controls. Earlier signed runtime
receipts remain evidence for their original bytes.

The compiler source now observes the exact reserved ID inside the generated
import's original `try/finally`, before typed lowering. The explicit fetch
initializer can capture that ID, application-realm result Promise and lazy native
retirement Promise together. Its cancel callback retains the exact native
retirement identity. Missing capture produces a separate cleanup failure rather
than fabricating an acknowledgement. Ordinary calls take no capture or retirement
allocation. The source controls cover the real initializer realm transform,
typed-finish ordering and rejection while physical retirement is still pending.
This hook remains uninstalled until the fetch profile and a fresh engine/splicer
tuple are built and qualified; these controlled callbacks are source evidence.

The JS-facing cancellation bridge accepts exactly one argument for the existing
form or two arguments for the captured retirement form. Its ID validator no
longer rejects the second argument before checking that identity. The native
fixture now includes the actual bridge implementation and tests wrong live
retirement identities, deferred physical completion, idempotent completion and
invalid arity through JS calls. Strict pinned WASI syntax compilation passes.
The source checkpoint preceded native execution; the actual results are below.

The explicit `spidermonkey-activation-promises-clocks-fetch-v1` compiler selection
now stages the SDK startup and its closed source set separately from application
resolution. Its binding world adds only `latent:http/streaming@0.3.0`; activation
and clocks remain native engine imports. Actual wasm-tools 1.254.0 parser graphs
prove the complete original imports/exports and resource ownership types survive.
Seven source controls reject synchronous/shadowed HTTP signatures and changed
application types. The ordinary synchronous default stays unchanged. A real
Node 24.19.0/esbuild compiler-host bundle runs the SDK banner before a dependency
initializer, which sees all four globals and no private bridge. This check uses
controlled HTTP callbacks and is not an installed component or provider receipt.

The source adapter accepts bounded finite request bodies, manual redirects and
native response streams. It copies genuine typed byte arrays across the compiler
realm before dropping chunks, removes the abort listener after successful body
drop, and retains cleanup failures separately. Failed retirement prevents
canonical drops and further fetch admission. Reserved credential headers remain
visible to native permission checks. Automatic redirects, streamed uploads,
native body clone/tee, non-ASCII wire headers, keepalive, cache retrieval and
integrity processing are explicitly unsupported. A Response left unread retains
its real native body owner; returning it or collecting JS wrappers certifies no
canonical retirement and cannot waive the existing root-drain gate.

Canonical 0.3 also has no origin/CORS, cookie-jar, referrer or credential-suppression
selector. Fetch rejects nondefault mode/credentials/referrer options before native
admission; it does not silently forward a request that asked to suppress provider
credentials. The default server profile leaves configured credential authority
with the native provider and has no ambient browser origin or cookie jar.

The actual fresh engine/Wizer probe reports `ReadableStream`, text codecs and
`AbortController` present, while `URL`, `URLSearchParams` and `Blob` are absent.
The standalone probe's intentional initialization exception and earlier missing
compiler-shim setup remain retained. This demonstrates why Node source controls
cannot qualify installed globals. The exact maintained pure URL derivation now
compiles against the authenticated WASI/SpiderMonkey headers with `-Wall -Werror`.
It admits native parser graphs before Rust allocations, owns temporary string
bases and standalone params, and retains a strong JS parent for linked params.
The linked box keeps a separate lease in its URL owner until Rust actually frees
both. Finalizers mark physical death; the existing outside-GC checkpoint performs
the acknowledgements. Object-URL methods reject explicitly; Blob/File/Worker/UUID
remain unselected. The original Native64 and compiler-snapshot phase gate remain
intact, so URL construction during snapshot is currently unsupported. The added
URL owner still needs its distinct fetch core and actual runtime controls.

The first new native run executed all 31 selectors. All original 27 and the three
direct retirement controls passed. The actual JS bridge case retained its own
`globalThis.retired` Promise after successful subtask/set drops, leaving one
reachable native owner at the unchanged final gate. That failed product and log
are preserved. The second run cleared that global and reached zero physical
owners, then correctly refused a new native Promise constructed after root
settlement. The fixture now creates that validation input under the original
root, checks exact bridge rejection reasons afterward, and clears its own roots
before the unchanged full GC/checkpoints. The fresh third run passes all 31
selectors: retained/idempotent checks pass, all three exact refusals are observed,
all owners end at zero, and native admissions/acknowledgements balance 9/9.
Its exact 9,269,759-byte product is
`ea3a25d8ca8a842109e07de38aff98464993fcb6b526eb41a9f92ebb3eb690e3`.
The [fixture packet](../testing/evidence/typescript-native-retirement-2026-10-13.json)
retains source/link/product identities and both failed attempts. This is finite
diagnostic-broker evidence; it does not qualify installed fetch. A newly rebuilt,
source-bound engine/splicer and ordinary/signed fetch cancellation, drop and reuse
controls are still required. All profile observations remain unknown and these
changes close none of #691, #745 or #685.
