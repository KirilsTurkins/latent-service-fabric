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

The eight focused source/controller controls and existing peer controls are not
signed-component evidence. Hosted execution is pending. Earlier default-client,
phase, SPI and tenant programmes keep their original source attribution. No full
#688/#741, HTTPS, full JDK or release qualification is claimed.
