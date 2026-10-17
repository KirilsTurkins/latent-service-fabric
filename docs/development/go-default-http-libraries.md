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
POST and lost replies, denied alternate destinations and fresh state. Sling's
original decoder can reject malformed bytes before its deferred discard reaches
a provider size error; that case expects its actual syntax error rather than
inventing a later exception. Its partial-response context cancellation does not
independently prove that headers were returned first. Requests starts that
cancellation in its response callback. The existing independent 33-case standard
HTTP gate remains responsible for concrete transports, early close and separately
labelled custom transports, including its after-header body cancellation case.

The original Go workflow commands, timer/GC regression and 45-minute job limit
remain. Native module capture, compilation and signed results for these clients
are pending. No complete Go runtime, TLS/socket profile, catalogue-removal proof,
cross-tenant matrix, allocator bound or full ticket completion follows from the
local capture-model tests. Original runtime failures stay visible.
