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
