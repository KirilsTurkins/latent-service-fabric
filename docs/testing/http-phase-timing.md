# Explicit HTTP phase timing

The opt-in `latent:http/phase-timing@0.4.0` interface adds connect and per-read
timeouts to the original owned streaming transport. The default host profile
remains V5 and the existing `latent:http/streaming@0.3.0` WIT remains unchanged.
Node configuration must explicitly select `providers.httpStreaming.phaseTiming:
true`, install its distinct provider identity and grant the new capability.
Selecting V7 supplies neither destination authority nor an implicit provider.

Connect timing covers admission, approved DNS and the actual TCP/TLS handshake;
it does not wait for response headers. A read timer covers one public response
header or body-read operation, including all internal protocol frames needed for
that read. Zero or absent phase timers retain the original deadline. The
original root cancellation and deadline always take precedence. A phase failure
destroys pending physical I/O before it is returned, retains charges for any
earlier live chunk, and never retries an operation. Header timeout reports whether
the original request may already have been written; it does not assert remote
rollback.

The new response carries up to 512 actual HTTP/1 reason-phrase bytes. Adapters
must distinguish observed empty bytes from unavailable metadata and interpret
bytes as Latin1 without substituting a canonical phrase for an unobserved
protocol. Both the retained head and its result copy are prepaid. The old response
and old provider reserve no new reason metadata.

For this explicit profile, a fixed-capacity observer reads the decrypted HTTP/1
status line before pinned `httparse` drops non-ASCII reason bytes. The existing
512-byte buffer moves directly into the retained head, and its connection slot
is cleared before pool reuse. Informational responses do not replace the final
reason; fragmented lines share the existing 32 KiB protocol-prefix bound. The
observer does not inspect or retain response body bytes. Legacy connections do
not allocate it. The earlier hosted failure on `Caf\xC3\xA9` is retained as a
parser-loss failure. Corrected transport/reason groups each passed seven native
test executions on source `795a623bd20c05cc83645ab22c42cba44a27aa7e`, run
`39390072288`, job `118519184537`; their shared case is not counted twice.
That workflow's later test-formatting failure remains a failure, distinct from
these passed groups and the profile/packaging controls.

The focused hosted lane checks the immutable profile, strict semantic aliases,
prepared bindings, real stalled TLS/header/body sockets, original root precedence
and fresh component Store retirement. On source
`be14147400f94b86bd271d2ed554ae90664ea82e`, run `39416952792`, job
`118608182714`, all three canonical component cases passed, including Latin1
and observed-empty reason metadata, uncertain header timeout, held body/chunk
retirement, exact finalized outbound charge and reusable Store/physical cleanup.
The original admission boundary and an actual preparation/inspection control
also passed. The nominal legacy type/resource owner remains fully checked and
linked under the phase host; it supplies no operational legacy binding or grant.
An injected extra operational binding still refuses before guest execution.
It never enters the generic structural-type linker path.

Source formatting and catalogue validation are separate from those native
results. No fresh five-product native build or signed Java/TypeScript V7 campaign
is claimed yet. Ordinary Java still selects v0.3; its connect/read setters and
default DavidWebb timeout qualification are not claimed by this backend slice.
Transactional-state plus phase timing is rejected until a combined profile is
explicitly defined and qualified. Issues #688 and #741 remain open.
