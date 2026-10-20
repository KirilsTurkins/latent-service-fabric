# Published Fetch client experiment

This finite experiment for [#691](https://github.com/KirilsTurkins/latent-service-fabric/issues/691)
captures unchanged Ky2.2.0 and Wretch3.0.9 through normal npm add, lock,
resolve and review. A local package imports Wretch transitively. The two
variants change its name and version, then remove the original source before
building. No catalogue lookup, application Fetch injection, source fork or
custom Promise pump selects the backend.

The profile automatically installs Fetch before dependency initialization.
Request dictionaries ignore unknown members without evaluating their values,
as normal Web IDL dictionaries do. Recognized unsupported settings still
reject. This allows dependency options to pass through ordinary Request
construction without interpreting them as transport authority.

The declarations include the existing URL API and erased Blob/FormData result
types needed by these published declarations. They do not install Blob or
FormData constructors or enable those body formats. The original ofetch1.5.1
attempt failed the normal compiler typecheck: its browser declarations import
Node-only undici types. That retained failed attempt is unqualified; the second
browser client is now Wretch, without declaration suppression or package edits.

`Response.body` and `Request.body` expose the runtime's native ReadableStream
over already-buffered bytes when that native facility exists. The existing
1MiB body ceiling remains. A default reader pulls at most 64KiB per read;
high-water mark zero prevents prefetch. Locking, disturbance, cancellation,
one-shot consumption and body cloning share the same body state. The stream
introduces no additional network read or host provider owner: Fetch has
already retired its typed response body before returning the buffered result.
Tee, piping, async iteration and streaming uploads reject explicitly. This
does not qualify network streaming or backpressure.

The current typed HTTP response does not carry a reason phrase. Its Fetch
`statusText` getter still rejects explicitly. Ky inspects that member when
constructing its default HTTP error object; its404 helper therefore requires
the exact Unsupported result and remains unqualified as an ordinary HTTP error.
Wretch's default helper reads the cloned response body and must produce its
ordinary WretchError with status404. The experiment does
not invent an empty reason phrase or disable client error handling. The older
plain Fetch qualification still treats404 as a normal Response.

The owning20-minute workflow compiles, packages, signs and admits two fresh
components. For each it requires Ky JSON, Wretch JSON, transitive local JSON,
Ky's explicit404 Unsupported result, Wretch's ordinary404 error and a fresh Ky activation. Missing
runtime and HTTP grants must refuse with zero fuel/outbound work. Each real
request uses the existing provider fixture; post-call physical owners must
retire, exactly six peer requests must complete, and node/peer shutdown must
be clean. Existing Task16, queue16, native-owner64 and one-outbound-per-call
limits are unchanged.

The original source-owned import engine and splicer are reused only when
their unchanged40 SDK inputs validate normally. Five ordinary host/tool
binaries retain explicit historical source0754391a/run39276911555 identity;
0754391a is the exact tested pull-request merge, whose second parent is the
owning workflow's aea63cc6 head. These identities are checked separately.
no current normal receipt is fabricated. Fixed original artifact metadata,
whole ZIP SHA256, member shapes, original normal receipt and all five binary
hashes are checked before use. A new source capture and normal build evidence
bind every new caller and backend byte.

The replacement Ky/Wretch normal capture, pinned typecheck and Node reference
controls pass. Signed execution remains pending until the owning workflow
produces retained results.
Full #691 acceptance still requires default HTTP-error compatibility, streaming
and abandonment, Abort/timeout races, uncertainty, limit exhaustion and
cross-tenant lifecycle qualification.
