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
be clean. The explicitly selected `typescript-published-client-owners-v1`
operator profile allows Task64/Queue64/Native256 while retaining Executor2,
Wait8/Timer8/Result8 and one outbound request per call. It applies identically
to every client and outside identity. The smaller ordinary Fetch profile stays
Task16/Queue16/Native64; its historical client failures remain failures. This
selection changes finite operator capacity, not engine ownership, admission,
physical cleanup, application source or the shared default profile.

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

Run39369743834 at19f5c2d207 completed a normal build, package, signing and
admission. Both pre-guest grant denials passed; the first Ky JSON invocation
then trapped after exactly one outbound request. The authenticated131-member
artifact12240944275 retains that failure and the actual component identity.
No trap cause is inferred. Two additive zero-outbound buffered-reader/JSON
probes and a closed diagnostic projection now distinguish supported reader
execution from rejected library calls; all six original library outcomes and
the exact peer-contact gate remain required. Unknown diagnostics reveal only
a static error-kind/unknown label, never arbitrary exception text.

The subsequent ab60 run passed both real zero-outbound reader/JSON probes,
then Ky still trapped after one outbound request. Reader availability is
therefore observed; the native trap's cause remains unknown. The next run keeps
every original client outcome mandatory while collecting all six attempts,
with physical retirement required before each fresh activation. Failed results
retain their original row and existing redacted audit projection. A failure
cannot count as a passing case, and the original ordered-case/peer gates still
refuse the programme. This allows comparison with Wretch and the outside caller
after the Ky failure instead of ending evidence collection at the first case.
Full #691 acceptance still requires default HTTP-error compatibility, streaming
and abandonment, Abort/timeout races, uncertainty, limit exhaustion and
cross-tenant lifecycle qualification.

The7a2 actual attempt retained all six original failed HTTP cases. Ky reached one
outbound open but the peer received no HTTP bytes; Wretch and the outside Wretch
consumer trapped before outbound dispatch. Both pure buffered-reader/JSON probes
passed. Artifact12241909608 retains223 members and original failed outcomes;
this is not published-client compatibility qualification.

An opt-in manual diagnostic reuses the same compiled/signed input in a separate
node with fixed Task64/Queue64/Native256 owner ceilings; all other bounds remain.
The original Task16/Queue16/Native64 attempt stays mandatory and failed. The
separate result cannot populate successful variants or turn original failure
into qualification. This comparison tests owner pressure without early refunds,
source forks, transport replacement or an assumed engine cause. A passing
larger-profile result alone would not establish correct physical accounting.

The a75 manual diagnostic passed all eight probe/client observations under the
separate64/64/256 profile, with exactly six real HTTP contacts and verified
physical retirement. Original16/16/64 still failed; artifact12242633589 retains
both outcomes (SHA2565dceaab832ae2f53931bcb2d4e3691e0e905385f97021f14f4c989e135262d96).
The next diagnostic varies only one owner ceiling per separate node: Task64,
Queue64 or Native256. The original failed profile remains mandatory and no
single-dimension result is inferred from the all-three passing comparison.

Run39376443876 at d6cd949 retained all three single-dimension failures in
artifact12243628634 (727 members, SHA256
5b2410d8fe75d0a3336ff164dbdaa572d7f78e54ea1fae713cf18d408f3a7421).
Increasing only Task, Queue or Native capacity did not qualify the clients.
Both Task and Queue reservations precede each owned reaction allocation; the
next normal two-identity run explicitly selects64/64 while retaining Native64.
That pair has not yet passed and is not inferred from the larger diagnostic.
All eight outcomes, both grant denials, all six real contacts and physical
retirement remain mandatory. Failure under this profile remains failure.

The normal5baccbaf attempt at64/64/64 passed Wretch JSON, transitive outside
JSON and ordinary Wretch404 handling, but all three Ky calls still trapped.
Artifact12244433338 retains that failed result (SHA256
c190fafcfcabf22f1f2f2cb8d0457358603db1ced647228f6e2a8f619d3cc1b9).
The selected normal client profile now uses the previously observed64/64/256
combination uniformly. The complete two-identity programme must still pass;
this does not establish minimum capacities or fix/classify an engine defect.
