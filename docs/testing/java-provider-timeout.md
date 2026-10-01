# Composed Java provider-timeout fixture

`tools/java_http_composition/provider_timeout.py` extends the maintained real
Java HTTP composition with a finite provider failure. The hosted conductor owns
the original compiler, native runtime, package admission, node, peer process and
absolute workflow deadline. This helper supplies no replacement execution or
provider owner.

Create fresh domain and adapter projects, complete their normal generator checks,
then call `adapt_domain` and `adapt_adapter` before compiler input capture. Adapt
both adapter revisions if the campaign builds two. The domain helper uses the
actual maintained Java `http-status` template and requests a 250 ms provider
timeout. Its normal `text` input and all exports remain available. Its declared
outbound allowance is one; the adapter allowance is two because the existing
local-child broker halves the parent's remaining allowance. Retain the returned
source, WIT, descriptor, template and helper digests in the new build receipt.
Original C4 projects and receipts remain unchanged.

Start the existing `sdk_provider_scenario.start_provider` peer under the
conductor's original deadline. Pass its actual loopback port to `configure`
before node startup. That function adds the original bounded HTTP provider
configuration and one domain binding. Call `grant` with the actual startup
record and admitted domain publication, and include the returned grant in the
domain's explicit deployment operation. It scopes the current policy to the
original adapter service caller, exact domain publication, GET and the peer's
fixed `/allowed` destination. Credentials and raw request fields are absent from
the evidence.

`qualify` performs two distinct real HTTP requests through the adapter and child.
For the first request the peer records an actual authenticated GET, then an actual
socket EOF or reset. The domain handles the provider error; authorized root/tree
inspection must observe nonterminal stage 6, reason 13. Cell and quota counters
must return to zero before the second request returns status 201 through the same
provider. The first send is never retried and no external mutation disposition is
inferred. Original observations are written before assertions.

An older approved runtime may omit that typed observation. The campaign then
reports `typed-diagnostic-unavailable`; its successful cleanup or fresh request
cannot satisfy the diagnostic acceptance criterion. It never classifies error
text or substitutes a queue deadline for a running provider timeout.

After normal node shutdown, pass the original `stopped_record` to
`verify_shutdown`. Provider counters are unavailable before that report; the
helper requires every known pool counter to be zero and the original node to be
reaped. Call `stop_peer` to reap the original peer and require exactly one
physically closed hold and one fresh authorized request. The SDK matrix's
`stop_provider` requires four holds and is not the correct campaign oracle.
For a failed campaign use the existing `close_failed_provider`, retain its failed
receipt and preserve the original failure independently of cleanup.

The registered Python fixture tests qualify the source adaptations, original
configuration and real peer GET/close rendezvous. A fresh signed Java build and
actual node campaign are separate evidence and remain required.
