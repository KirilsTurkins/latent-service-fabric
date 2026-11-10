# Go declared-stream source port

The selected `go-component-activation-v5` and `go-component-activation-v7`
compilers can derive a finite `net.Dial`, `net.DialTimeout` and
`Dialer.DialContext` backend from the captured
`latent:network/streams@0.1.0` import. This is an implementation prerequisite
for [#742](https://github.com/KirilsTurkins/latent-service-fabric/issues/742)
criteria 7/8 and the accepted
[outbound design](../../adr/0061-bound-standard-outbound-streams.md).
It installs no provider, grants no endpoint authority and does not qualify
general TCP, DNS, kernel accounting, guest TLS, host TLS or an unchanged protocol client.
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
one owned nonempty chunk of at most 16 KiB; only an absent chunk is EOF. A public
`Write` holds its original direction owner while advancing across acknowledged
positive prefixes in host fragments of at most 16 KiB. Its original absolute
deadline is checked before every fragment; elapsed time never becomes a fresh
per-fragment allowance. Any host error or uncertain effect stops the call and
preserves the cumulative accepted count and typed uncertainty. Zero progress
returns `io.ErrShortWrite`; accepted bytes are never resent. The existing
per-connection transfer and lifetime bounds remain authoritative. There is no
reconnect, retry after an error, proxy, application executor or conversion of
HTTP authority into TCP authority.
The host's existing shared address/SSRF policy remains authoritative.

This finite surface accepts `tcp`, numeric nonzero ports, canonical IP literals
or ASCII DNS names. DNS is performed only inside an authorized host connect.
Standalone resolver operations, concrete `*net.TCPConn` construction, UDP,
listeners, native socket options, custom resolvers/controls/local binds,
explicit keepalive and address-family/fallback policies are unsupported. Numeric
`LookupPort` remains a pure local conversion. Read and write deadlines map to
the bounded host timeout; expired deadlines fail before dispatch. Remaining
deadlines over 10 seconds use the provider's 10-second timeout maximum: the
accepted profile already limits connection lifetime to at most 10 seconds and
still enforces the original root deadline and its shorter idle bound. The guest
samples its remaining time before dispatch and passes a relative timeout; delay
between that sample and host admission can therefore outlast the original Go
deadline. This conversion does not establish exact wall-clock deadline behavior
at that boundary. Dial context cancellation retains its existing path. Re-arming a
deadline while its direction is active is explicitly unsupported. `CloseWrite`
does not use the Go write deadline; the original connection, idle, provider and
activation bounds still apply to send shutdown. The WIT exposes no local endpoint, so
`LocalAddr` is nil; `RemoteAddr` describes the declared target, not a resolved
peer address. This is not full `net.Conn` compatibility.

The port pins the original package-initialized `DefaultResolver`. Replacing it
or changing its public `PreferGo`, `StrictErrors` or `Dial` settings returns
`errors.ErrUnsupported` before host dispatch; those custom paths are never
silently replaced by the host resolver. The ordinary fixture includes all four
negative cases. The earlier construction receipt below predates this additive
refusal guard and those cases; the later signed execution below includes them.

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


The v7 selection composes this same declared stream port with the existing
queued-work owner and single-stack ceiling. Its separate signed owner selects
Task16, Executor2, Queue16, Wait4, Timer2, Result2 and Native2. The v5 owner's
original Queue2 remains unchanged. A passing v5 receipt does not qualify the
v7 composition; the v7 owner must execute independently. The v6 composition
remains refused. Neither selection enables the normal provider.

The dedicated runtime lane compiles the current guarded ordinary fixture
once, then builds only the `go_outbound_streams` native integration target. It
uses the existing signed catalog, node admission, broker, runtime grants and
explicit development logical-stream installation. The synthetic callee is
attributed to its actual handwritten fixture builder; the Go caller additionally
binds its real source, WIT and compiler observation. This in-process test package
construction is distinct from released standalone authoring/packager and native
five-product qualification.

The historical twelve-case run covered the original unsupported/pre-cancelled/expired
modes, all four custom global resolvers, ordinary ping/pong, send half-close and
reading through EOF, cancellation after a delivered byte and a fresh connection
afterward. The peer used multiple writes, but that alone did not prove separate
or short guest reads because TCP can coalesce them. Its cancellation barrier
observed one delivered byte, a
live pending operation and the original I/O call. Those counters alone cannot
show whether the first read had retired or a second read had begun. The
historical receipt below remains unchanged and supports only that narrower claim.

The current signed owner explicitly selects `development-go-network-read-witness`
for the additional fragmented-read case and for the cancellation barrier. The
sole live connection must report that the guard which delivered the first byte
retired, a second read future was successfully constructed and its original
read guard is live. The peer withholds the remaining bytes until the fragmented
case has observed that state. This witnesses application read ordering, not an
OS-readiness poll or final kernel free. The feature is absent from ordinary
builds and records only inert diagnostics within the existing prepaid connection
allocation. The guest's own one-second connection deadline still applies; the
host's two-second barrier is a failure ceiling, not a longer guest timeout.

The revised source-bound owner also requires one connection's original second
`Pending` read to remain before its first destructor marker when cancellation is
accepted. It samples a saturating sequentially consistent marker counter before
and immediately after the real cancellation call, without holding a provider
lock across it. A thread could be preempted just before publishing that marker,
but the read's socket and guard cannot begin dropping before it. A concurrent
published marker makes the observation fail closed.
The existing signed v2 receipt does not establish this new edge; a successful
v3 run is required. This observation does not prove OS-readiness polling or
final kernel free.

Cancellation acknowledgement must retain the original activation, Store and
socket owner. Each completed observation requires zero original user-space
owners; peer close and those counters never attest final kernel free. The
original managed Task16, Executor2, Queue2, Wait4, Timer2, Result2 and Native2
limits remain fixed. The added source owner requires its own signed run before
its thirteen-case observations can be treated as evidence.

The [authenticated runtime observation](../testing/evidence/go-network-runtime-2026-10-20.json)
records actual source `bc638ac30bd28bbff492b8cd8ea0e91f5317c845`,
[run 39425642133/job 118637383474](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39425642133/job/118637383474).
All twelve ordered guest cases passed with exactly four peer contacts, twelve
zero-user-owner rows and a clean logical-provider stop. The exact selected Rust
test passed with zero ignored or filtered cases. All 50 archive members passed
CRC and SHA-256 checks; all 5,415 source-input rows (44,996,795 bytes) match the
exercised Git source. The newly compiled managed-v5 component is 3,351,500 bytes,
SHA-256 `4ec00509c122ff283c4216d057ac9035b304873d955e488a05e55f65ff8cc00c`.
The producer performed full in-memory compiler/source checks before and after;
full compiler manifests and the native executable were not retained. An earlier
attempt built the same component but failed to compile its native test harness;
that failure supplies no guest-execution credit.

The strict reader rejects missing or reordered cases, private/unknown/duplicate
fields, numeric type substitutions, retained owners, incomplete stop and any
claimed normal/kernel qualification. This proves the finite declared-TCP guest
surface under the explicit development provider. The normal provider and full
networking/TLS/accounting gates remain closed.


The bounded write-progress source candidate closes the internal chunk-boundary
short-write gap for ordinary larger `Write` and `io.Copy` calls. It follows
[Go 1.27.2's stream write progression](https://github.com/golang/go/blob/go1.27.2/src/internal/poll/fd_unix.go),
while retaining the smaller host fragment bound and existing activation limits.
A separate tiny Go reference projects the exact production method without body
rewrites, with explicit deterministic protocol doubles. It must reproduce the
original 40 KiB copy stopping at 16 KiB, then pass eight corrected progress,
partial-error/uncertainty, zero-progress, original-deadline, ownership and refusal
controls. The [authenticated reference](../testing/evidence/go-write-progress-reference-2026-10-20.json)
passed on source `fb79a7ab6ea86f53baec78ee341aca075c14a2ef`,
[run 39443276481/job 118698441927](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39443276481/job/118698441927):
the old copy returned 16,384 bytes and failed; all eight current cases passed.
All five archive members passed CRC and SHA-256 checks, and all seven exercised
source inputs match that Git source. Those doubles do not establish
emitted-component, live TCP/provider, kernel or full networking qualification.
The earlier twelve-case signed observation remains attributed to its original
source; it is not relabelled as execution of this new method.

A follow-up per-fragment close guard also preserves an already acknowledged
prefix and returns `net.ErrClosed` before any later dispatch after close.
The follow-up [actual reference](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39446468125/job/118709756425)
passed on source `150969cbce75daf6411677ea863618328721a948`: the pinned
previous method reproduced close-between-fragments failure; all nine current
cases passed, alongside the original chunk-boundary counterexample. All seven
archive members passed CRC/SHA-256 checks, and all seven exercised inputs match
that source. All eight original Go control bodies remain unchanged; the earlier
eight-case observation retains its own source identity. No owner, deadline or fragment bound changes.
