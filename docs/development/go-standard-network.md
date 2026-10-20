# Go declared-stream source port

The selected `go-component-activation-v5` compiler can derive a finite
`net.Dial`, `net.DialTimeout` and `Dialer.DialContext` backend from the captured
`latent:network/streams@0.1.0` import. This is an implementation prerequisite
for [#742](https://github.com/KirilsTurkins/latent-service-fabric/issues/742)
criteria 7/8 and the accepted
[outbound design](../../adr/0061-bound-standard-outbound-streams.md).
It installs no provider, grants no endpoint authority and does not qualify
TCP, DNS, kernel accounting, guest TLS, host TLS or an unchanged protocol client.
The normal provider remains refused while physical accounting is unqualified.

An undeclared stream import retains the ordinary compiler/SDK path. A declared
stream under any other runtime profile, unknown stream version/interface or
unexpected generated package fails closed. The compiler authenticates all
three complete Go 1.27.2 source files before staging private overlays. GOROOT,
application/dependency source and the generic SDK resource owner are unchanged.
Every original generated canonical entry point is preserved; context variants
authenticate the seven generated function bodies and decode result buffers only
after terminal return. Cancellation retains pins and real owners until its
acknowledgement. An own close handle is restored only if canonical entry never
acquired it; uncertain close/write effects are not labelled rolled back.

The compiler-owned connection uses independent read/write ownership and an
exclusive final close. Close cancels active canonical operations and waits for
their actual acknowledgements before consuming or dropping the original own
resource. Same-direction overlap is refused instead of queued. Reads consume
one owned nonempty chunk of at most 16 KiB; only an absent chunk is EOF. Writes
perform one bounded host attempt, preserve an accepted prefix and return
`io.ErrShortWrite` for a short result. There is no reconnect, write-all retry,
proxy, application executor or conversion of HTTP authority into TCP authority.
The host's existing shared address/SSRF policy remains authoritative.

This finite surface accepts `tcp`, numeric nonzero ports, canonical IP literals
or ASCII DNS names. DNS is performed only inside an authorized host connect.
Standalone resolver operations, concrete `*net.TCPConn` construction, UDP,
listeners, native socket options, custom resolvers/controls/local binds,
explicit keepalive and address-family/fallback policies are unsupported. Numeric
`LookupPort` remains a pure local conversion. Next-operation deadlines map to
the bounded host timeout; expired deadlines fail before dispatch. Re-arming a
deadline while its direction is active is explicitly unsupported. Send shutdown
uses an actual context deadline. The WIT exposes no local endpoint, so
`LocalAddr` is nil; `RemoteAddr` describes the declared target, not a resolved
peer address. This is not full `net.Conn` compatibility.

The focused construction lane builds one ordinary-source component and runs
six standalone Go controls against the exact private owner: independent
directions, same-direction refusal, cancellation followed by real drain,
send shutdown sharing the write owner while preserving read ownership,
one final own resource, invalid inputs and duplicate
release. The component includes ordinary `net` calls for closed unsupported,
pre-cancelled, expired and eventual TCP exchange paths. Construction does not
execute those guest paths. The receipt distinguishes native owner-reference
execution from emitted-component construction and leaves signed/provider/kernel
qualification false. Both actual hosted outcomes are pending until retained
terminal evidence is checked. No native LSF host is rebuilt by this lane.

Pinned pure generation was checked locally with official componentize-go
0.4.3 (source `148dba505f8c6c64ad84db777cfde5e34e25098b`, bindings
`4f9a02d74cec9257c14ba9b160fa787a3523fd0b`) and Go 1.27.2's formatter.
Both independent formatted binding outputs match. No local Go compiler or
guest was executed. The full upstream preimages and derivation/refusal controls
are source evidence; they cannot satisfy the remaining signed workload matrix
or the maintained-kernel allocation/final-free artifact requirement.
