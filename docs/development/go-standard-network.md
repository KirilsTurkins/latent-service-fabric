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

The port pins the original package-initialized `DefaultResolver`. Replacing it
or changing its public `PreferGo`, `StrictErrors` or `Dial` settings returns
`errors.ErrUnsupported` before host dispatch; those custom paths are never
silently replaced by the host resolver. The ordinary fixture includes all four
negative cases. The earlier construction receipt below predates this additive
refusal guard and those cases; their actual guest execution remains pending.

The focused construction lane builds one ordinary-source component and runs
six standalone Go controls against the exact private owner: independent
directions, same-direction refusal, cancellation followed by real drain,
send shutdown sharing the write owner while preserving read ownership,
one final own resource, invalid inputs and duplicate
release. The component includes ordinary `net` calls for closed unsupported,
pre-cancelled, expired and eventual TCP exchange paths. Construction does not
execute those guest paths. The receipt distinguishes native owner-reference
execution from emitted-component construction and leaves signed/provider/kernel
qualification false. The [authenticated source observation](../testing/evidence/go-network-construction-2026-10-20.json)
records exact source `7701689942f66f3168592942b7e282a116cdda2f`, actual run
39414844795/job 118601242065: all six standalone owner controls and actual
managed-v5 component construction passed. All 50 retained members, 62 recipe
files, 74 SDK files and both ordinary fixture inputs were checked. The emitted
3,304,114-byte component retains the stream import and no ambient WASI import.
Its guest cases were not executed. No native LSF host was rebuilt by this lane.

Pinned pure generation was checked locally with official componentize-go
0.4.3 (source `148dba505f8c6c64ad84db777cfde5e34e25098b`, bindings
`4f9a02d74cec9257c14ba9b160fa787a3523fd0b`) and Go 1.27.2's formatter.
Both independent formatted binding outputs match. No local Go compiler or
guest was executed. The full upstream preimages and derivation/refusal controls
are source evidence; they cannot satisfy the remaining signed workload matrix
or the maintained-kernel allocation/final-free artifact requirement.


The next dedicated runtime lane compiles the current guarded ordinary fixture
once, then builds only the `go_outbound_streams` native integration target. It
uses the existing signed catalog, node admission, broker, runtime grants and
explicit development logical-stream installation. The synthetic callee is
attributed to its actual handwritten fixture builder; the Go caller additionally
binds its real source, WIT and compiler observation. This in-process test package
construction is distinct from released standalone authoring/packager and native
five-product qualification.

Twelve required observations cover the original unsupported/pre-cancelled/expired
modes, all four custom global resolvers, ordinary ping/pong, send half-close with
partial reads through EOF, cancellation of a real pending second read and a
fresh connection afterward. The cancellation barrier requires one delivered byte,
a live pending operation and the original I/O call before cancellation. Its
acknowledgement must retain the original activation, Store and socket owner.
Each completed observation requires zero original user-space owners; peer close
and those counters never attest final kernel free. The original managed Task16,
Executor2, Queue2, Wait4, Timer2, Result2 and Native2 limits remain fixed.

This new lane has no actual result yet. Its strict reader rejects missing or
reordered cases, private/unknown/duplicate fields, numeric type substitutions,
retained owners, incomplete stop and any claimed normal/kernel qualification.
The normal provider and full networking/TLS/accounting gates remain closed.
