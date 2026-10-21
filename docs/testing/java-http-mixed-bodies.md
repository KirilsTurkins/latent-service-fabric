# Java mixed response-body qualification

This finite programme advances #688's remaining body and lifecycle requirements.
It uses ordinary `HttpURLConnection` and unchanged `http-request:6.0` through the
explicit Java phase-timing/FIO profile. The public SPI is not used. The normal
captured dependency review still binds the original JARs and transitive resources.

The ten signed cases require:

| Case | Required observation |
| --- | --- |
| Consumed response views | One response stream, continued consumption, repeated EOF, idempotent close, concrete closed-read refusal; no new request |
| Borrowed output | `HttpRequest.receive(OutputStream)` closes its input while the caller's output remains writable |
| Held multi-read body | The exact 4,109-byte body, its first five bytes delivered before suspension, and an ordinary sibling HTTP response before the peer releases the held suffix |
| Partial error | The actual `short` prefix remains available before typed `unexpected-eof`; truncation cannot become successful EOF |
| Response ceiling | The existing oversized body produces `response-too-large` |
| Request boundary | Exactly 4,096 uploaded bytes are echoed without modification |
| Request ceiling | Declared length 4,097 is refused as the maintained provider's `invalid-request` before pool admission, outbound charge or contact |
| Pending cancellation | After the prefix and sibling response, root cancellation retires the held stream without releasing or replaying it |
| Fresh invocation | The same cell makes a new normal request with invocation-local static counters reset |
| Response boundary | Exactly 8,192 response bytes are consumed successfully |

The upstream [HttpRequest 6.0 source](https://github.com/kevinsawicki/http-request/blob/http-request-6.0/lib/src/main/java/com/github/kevinsawicki/http/HttpRequest.java)
closes the input in its copy operation and leaves the supplied output with the
caller. This programme checks that contract through the normal library path.

The node retains the original 4,096/8,192-byte transfer ceilings, 4,096-byte chunks,
two outstanding chunks, one cell, 1 billion fuel, 64 MiB guest memory, 120-second
invocations and existing provider budgets. The explicitly selected node/operator
component-input ceiling remains 64 MiB; it is not an execution-budget increase.
Publication preparation is a distinct setup operation clipped by the original
300-second node/peer lifetime and returns no execution authority.

Every actual result is written before classification. If a pending observer,
cancellation control or result reader fails earlier, the original exception is
preserved with bounded partial process streams and peer/cancellation state; a
cleanup refusal cannot overwrite it. These partial records never count as
completed invocations. The programme requires the
exact resolved signed revision, no replay, real pending owner observations,
per-case physical retirement and all 18 active provider counters at zero. Raw
final node, peer and product records are separate from the bounded summary. A
closed peer gate is never released later or presented as proof of a late
provider completion. Late-completion coverage must retain its own exact evidence.

One fresh application component is compiled offline. Public compiler dependency
acquisition resolves the existing strictly verified Gradle configurations without
building a greeting or any native product. The native tools remain the immutable
protocol-inclusive `6fd19eab2c224fc31481d03de5008de4d3e4429e` producer; all 3,318
native source files and 134 materials, including 20 protocol files, must match
before and after the consumer. Historical helpers and receipts remain unchanged.

The first two hosted attempts stopped at component assembly, before signing or
guest execution. The second retained the exact public core and adapter. Pinned
`wasm-tools 1.254.0` reproduces its refusal: `Capsule.run` has a 13,797,140-byte
body, exceeding the existing 7,654,321-byte validation limit. The fixture now
places the four original case bodies in separate ordinary methods. Their
operations, assertions, cleanup and result strings are unchanged; a host-JDK
comparison of all ten modes preserves results, errors and ownership operations.
This is a fixture refactor, not a raised parser limit or compiler acceptance
change. The original failed artifacts and core remain unchanged.

The [exact-source hosted campaign](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39528776339/job/118989568182)
passed all ten signed outcomes, one zero-work grant denial and eleven HTTP
contacts at `ef3d836b670775ad398ffee2895fd725c88f1750`. All 237 archive members,
raw outcomes/revisions, two pending physical observations, ten per-case provider
retirements and final clean/reaped node/stopped peer were independently verified.
The component is 7,721,494 bytes, SHA-256
`642b2b7038fa79d18f8c75cd3620788365f3c7ac5c967b78ac80849614fc8862`.
The [fixed receipt](evidence/java-http-mixed-signed-2026-10-21.json) preserves
both failed attempts and the separately compiled historical native source.

The current integration preserves all 199 Java SDK/WIT preimages. Its only two
campaign-material changes are the unrelated Go toolchain patch and optional Rust
HTTP recipe; shared Commands/package inputs remain unchanged. This does not
transfer the historical native compilation to later source. Earlier default,
phase, SPI and tenant programmes retain their original identities. Late accepted
task completion remains a separate gate. No full #688/#741, HTTPS, full JDK,
byte reproducibility or release qualification is claimed.
