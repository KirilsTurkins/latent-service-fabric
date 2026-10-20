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
original root interruption retains its root outcome or `HttpFailure` code and
cannot satisfy a phase-timeout assertion. A timed-out header operation retains its explicit uncertain-completion
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

The prepared public campaign uses one ordinary project capturing DavidWebb 1.3.0,
its transitive JSON dependency, and http-request 6.0. Both published clients use
their default timeout paths under the same selected profile; DavidWebb's nonzero
defaults are not replaced. Its other standard URLConnection
cases select explicit nonzero success, held-header and partial-body read expiry,
root deadline/cancellation separation and a fresh request. A Linux connect case
uses the same real full-accept-backlog premise as the maintained native ownership
test: one `listen(1)` listener and two bounded fixture-owned TCP connections.
They write no HTTP and do not warm or retry the guest. The guest's explicit
`connect()` must report the connect-specific timeout; returning from connect,
a read timeout, or a root interruption cannot satisfy that result. Separate
pending-connect cases preserve the root deadline/cancellation distinction.
The maintained campaign plans 16 signed invocations: eleven primary cases and
five fresh calls after terminal operations, with two separate zero-fuel authority
denials. The three connect cases own separate full backlogs, require a real
connecting-pool owner and issue no HTTP. The one-second connect timer leaves a
finite observation window; root-deadline cases retain the original three-second
root bound, and provider/activation ceilings are unchanged. The exact peer oracle
requires thirteen HTTP contacts, no secondary contact or mutation, physical zero
owners after each invocation, and a clean/reaped final node. Results, shutdown,
peer and product checks are retained separately before the compact summary.

V7 native producer `77bf0e3f3b68e17342b6146abd6f2de34a3efa00`, run
`39420914927` / job `118621322461`, completed successfully. Its five products,
eleven filtered controls, exact native sources and 114 compile materials are
authenticated separately from the current Java fixture/compiler source. The
consumer refuses a different native source or any extra/changed WIT, schema or
echo compile input; it does not rebuild native binaries or relabel the old a4
products. Actual TeaVM compilation and these signed Java outcomes remain pending.
The programme is a partial #688/#741 qualification, not whole-issue closure.
