# Explicit Java HTTP phase adapter

`lsf.java.httpurlconnection.phase-timing.v1` selects an additive compiler-owned
`HttpURLConnection` variant for `latent:http/phase-timing@0.4.0` and host ABI V7.
It requires the existing explicit `teavm-activation-fibers-io-v1` runtime,
activation/monotonic imports, and the new phase interface. Transaction authority
cannot be combined with this profile. The existing streaming profile, SDK client
source, frozen 0.3 interface and default host ABI remain unchanged.

The compiler verifies the exact captured `Connection.java` preimage and derives
only its selected owned copy. Both source identities enter the HTTP profile
receipt, together with the recipe, source and final component identities. A
changed SDK preimage or staged copy refuses before replacement.

Nonzero `setConnectTimeout` values select the provider's actual queue/DNS/TCP/TLS
connection-establishment boundary. Nonzero `setReadTimeout` values select response
headers and each subsequent provider read, independently. Zero remains an absent
phase timer. Neither setter extends or replaces the original activation deadline.
Only the new typed connect/read timeout outcomes become `SocketTimeoutException`;
the original root deadline and cancellation remain their original `HttpFailure`
codes. A timed-out header operation retains its explicit uncertain-completion
cause. Failed operations preserve the first exception and never recreate or
replay an upload or body read.

Response-message metadata uses actual bounded Latin1 reason bytes: unavailable
is `null`, observed empty is `""`, and no status-derived phrase is synthesized.
The selected body owner is acquired before validating those bytes so a malformed
result closes that owner. Existing request/body/chunk bounds, redirect refusal,
header ownership and immutable views remain in force. HTTPS remains explicitly
unsupported; selecting this profile does not grant any destination or transport
authority.

Focused source controls and an installed-JDK reference exercise the actual derived
adapter against a modeled typed port. The reference checks 27 phase outcomes and
four legacy controls, including exception identity, root-error separation, timeout
options, reason bytes and body release. This is host adapter evidence. It does
not establish TeaVM compilation, canonical-ABI aliases, signed component execution,
physical provider retirement or whole-issue #688/#741 completion. Those require
the new V7 host and actual pending HTTP component programme; historical 0.3 native
products cannot qualify this profile.

The prepared public campaign uses an ordinary captured DavidWebb 1.3.0 project
without replacing its nonzero timeout defaults. Its other standard URLConnection
cases select explicit nonzero success, held-header and partial-body read expiry,
root deadline/cancellation separation and a fresh request. A Linux connect case
uses the same real full-accept-backlog premise as the maintained native ownership
test: one `listen(1)` listener and two bounded fixture-owned TCP connections.
They write no HTTP and do not warm or retry the guest. The guest's explicit
`connect()` must report the connect-specific timeout; returning from connect,
a read timeout, or a root interruption cannot satisfy that result. Separate
pending-connect cases preserve the root deadline/cancellation distinction.
This fixture and its pure ownership/source controls are preparation only; no
TeaVM, V7 native or signed execution result is claimed yet.
