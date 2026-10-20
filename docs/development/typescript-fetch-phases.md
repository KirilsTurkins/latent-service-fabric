# Explicit TypeScript Fetch phase-contract candidate

The compiler can select `lsf-fetch-phase-buffered-v2` when the existing
`spidermonkey-activation-promises-clocks-imports-v1` runtime and the explicit
`latent:http/phase-timing@0.4.0` import are both declared. Package names do not
select it, application metadata cannot install/override the backend, and this
selection supplies no provider or destination grant. The legacy0.3 contract
continues to select `lsf-fetch-buffered-v1` with its original call arities.

Ordinary global fetch/Request/Response/Headers calls remain the application path.
Fetch has no independent connect/read-timeout option: the phase adapter passes
None for these operation timers and retains the original caller/root deadline
and AbortSignal behavior. This does not reinterpret an HTTP method/path grant
as stream authority, install a clock/secret or add retries.

The phase response can expose the actual bounded reason-phrase bytes as Latin1
statusText, including an observed empty phrase and exact whitespace/obs-text.
Unavailable metadata and the legacy contract retain the explicit unsupported
getter; no conventional phrase is manufactured from the numeric status. The
512-byte bound and prohibited control bytes are checked before presentation.
Response clones retain the original value/descriptor. All outstanding canonical
operations still settle before the original chunk/body/upload destructors run.
Nested typed HTTP uncertainty and a dispatched read-timeout flag remain visible
on the TypeError cause/uncertain fields without replaying the operation.

Four source/Node controls and all24 existing Fetch adapter controls pass. These
exercise exact/empty/unavailable/malformed reasons, old/new call arities, clone
behavior, ownership, nested uncertain errors and compiler selection. No signed
V7 component, provider, production enablement or whole #691/#745 completion is
claimed. That actual qualification depends on #1184's maintained phase contract
and separately authenticated native products. The existing engine and compiler
splicer identities must still validate; this is not a replacement engine.

## Signed consumer programme

The focused `typescript-fetch-phases.yml` lane prepares one fresh component with
unchanged Ky 2.2.0 and Wretch 3.0.9, plus an outside-checkout transitive local
package. It uses normal dependency capture, removes the original local package,
and performs normal compilation, packaging, signing and node admission.
The compiler engine and splicer retain their authenticated historical identities;
only the separately authenticated V7 native producer supplies the host products.

Its pending execution gate covers both clients' ordinary JSON and HTTP-error
paths, actual empty and Latin1 wire reasons through Response.clone(), public
abort during held headers/body, an uncertain single POST without replay, a denied
target without contact, root cancellation/deadline, and a fresh invocation. The
peer never releases the four held responses. Each terminal invocation must retire
its physical owners before the next case. The explicit published-client owner
profile remains 64 tasks, 64 queued work and 256 native owners; it establishes no
minimum-client or default-budget claim.

The source and real-wire reference controls pass. Signed execution is pending;
no whole #691/#745 criterion is credited to preparing this programme. It supplies
no Fetch connect/read timeout extension, TLS/HTTP2 reason fabrication or new
stream grant.

Normal package compatibility now selects and captures the frozen V7 manifest
from the authoritative declared phase interface, while legacy declarations keep
their original profiles. Phase HTTP combined with transactional state refuses
until a combined profile is qualified. This supplies no provider or grant.
The first emitted component at `1e2bf27881` compiled successfully but its old
selector inspected the phase import under V5 and refused before packaging.
That failed run remains retained; re-inspection of its exact component/graph
under the declared V7 profile has no link blocker, and actual signed execution
still requires the focused lane.

The `8981516dd6` retry compiled and packaged the phase component, then correctly
refused its first invocation as incompatible-contract: WIT dependency resolution
had implicitly imported all eight legacy streaming operations alongside their
nominal resource types. The phase-only fixture now captures a canonical
resource/type declaration with exactly those eight unused calls removed. Every
original type and every phase function remains unchanged, as checked by the
real wasm-tools 1.254.0 parser. No legacy provider or grant is added. Seven focused
source/wire controls pass; actual signed execution of this correction is pending.
