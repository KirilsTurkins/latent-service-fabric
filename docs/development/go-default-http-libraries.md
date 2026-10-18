# Captured default Go HTTP client candidate

This is a pending extension to the
[finite typed HTTP candidate](go-standard-http-candidate.md), not completed
[#692](https://github.com/KirilsTurkins/latent-service-fabric/issues/692)
qualification. It supplies no new runtime/backend implementation or authority.

| Original module | Version | Ordinary application execution |
| --- | --- | --- |
| `github.com/dghubble/sling` | `v1.4.0` | `New`, `Request`, `Do`, original JSON decoder and default HTTP client |
| `github.com/carlmjohnson/requests` | `v0.24.3` | `URL`, `ToJSON`, `Fetch` and default HTTP client |

The fixture uses Sling's normal request to attach its request context, then
Sling itself sends and decodes the response. Requests uses its public response
validator to observe HTTP status and permit parsing HTTP error bodies. Neither
path receives a transport, Doer, dialer, executor or SDK HTTP call. The original
module closure is captured with the native resolver and exact review through
the existing Go dependency owner. Fixture coordinates do not affect production
compiler dispatch or API eligibility.

An outside-checkout private module embeds a resource and calls an ordinary
goroutine, `sync.WaitGroup` and `time.Sleep`. The application checks its returned
resource value before calling each client. Its original directory is retained
at an owned sibling path after capture so the declared original replace target
is unavailable during subsequent isolated builds. Two variants change the
private coordinate and application import without changing the SDK/backend.
This is transitive runtime coverage once actually executed, not a claim that
either published HTTP builder starts its own worker by default.

The maintained `tools/qualify_go_http_libraries.py` command consumes the five
byte-checked normal native products from a passed ordinary Go qualification.
It performs two normal captured builds and signed node runs. Each node has
30 finite client cases and requires exactly 24 controlled peer contacts, two
accepted uncertain mutations, no alternate peer contact, and physical provider
retirement after each activation. The 1,200-second overall deadline bounds
capture/build/node commands to the remaining time. Each capture and build has
a separate 300-second ceiling; node runs retain their existing 300-second bound.
There is no additional native workspace build or automatic release publication.

Cases cover domain JSON, HTTP 404/500, truncation, body limits, malformed JSON,
reserved credentials, pending contexts, pre-cancellation, sibling cancellation,
POST and lost replies, denied alternate destinations and fresh state. The
oversized vector declares65,536 bytes, exceeding the host's32,768-byte output
allowance. Both clients receive that transport refusal before any JSON decoding;
this host policy result is independent of an unrestricted native client.
Sling's partial-response context cancellation does not
independently prove that headers were returned first. Requests starts that
cancellation in its response callback. The existing independent 33-case standard
HTTP gate remains responsible for concrete transports, early close and separately
labelled custom transports, including its after-header body cancellation case.

Before each signed library variant, a native reference compiles the unchanged
captured application's ordinary Run function against the reviewed offline module
closure. The private origin remains unavailable. One native binary is invoked
in a fresh process per client and response vector: short body (five bytes,
declared Content-Length32), then complete malformed JSON (six bytes,
declared Content-Length6). Each must make exactly one GET. Sling streams its
JSON decoder and can report syntax before body truncation, while Requests reads
the entire response before decoding. The four truncated/malformed-body
expectations come from these observed native results. Host authority and body
limit refusals retain their independent strict oracles; no native result can
permit a denied operation or enlarge a limit.
A missing, failed, malformed, repeated-request or wrong-source reference cannot
supply an oracle. Native control rows are retained separately, never counted as
guest execution or among the24 signed peer contacts. No transport is injected,
and source, module closure and Go executable identities are checked unchanged.
The reference has a120-second sub-bound inside the unchanged1,200-second total;
capture/component/node limits and the45-minute job are unchanged.

The original Go workflow commands, timer/GC regression and 45-minute job limit
remain. Native module capture, compilation and signed results for these clients
are pending. No complete Go runtime, TLS/socket profile, catalogue-removal proof,
cross-tenant matrix, allocator bound or full ticket completion follows from the
local capture-model tests. Original runtime failures stay visible.
