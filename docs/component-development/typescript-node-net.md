# Finite ordinary TCP Socket source profile

`lsf-node-net-tcp-v1` supplies `net` and `node:net` through a compiler-owned
module over the original `latent:network/streams@0.1.0` operations. It requires
the explicit TypeScript import-runtime candidate, the exact maintained stream
interface and an independently granted TCP endpoint. Importing this module
grants no authority and enables no production provider.

The source implementation supports `Socket`, `connect`/`createConnection`,
connection and data events, copied Buffer chunks, pause/resume, serialized
writes, backpressure, writable readiness after zero progress, timeout events,
send shutdown and explicit destroy. It preserves typed stream errors, known
accepted write prefixes and possible effects; it never retries an uncertain
write. Only an explicitly unaccepted suffix can enter another charged write.
A positive accepted prefix conservatively sets the public possible-effect flag;
the original native prefix and flag remain available separately. `bytesWritten`
counts WIT-confirmed accepted bytes rather than promising Node's intermediate
queued/dispatched counter implementation.

This finite port permits at most two reserved Socket states, three pending
operations per Socket, 16 queued write records (including empty writes),
65,536 queued write bytes and 16,384 bytes per transfer. Queued empty-write
callback records remain reserved until their actual callback job returns;
original runtime budgets can refuse earlier than these port ceilings.
These bounds describe this module, not a universal activation ledger or a
whole-cost accounting qualification. Original native, request, memory, fuel,
task, deadline and endpoint limits continue to apply independently. A normal
unconnected constructor allocates guest state without reserving a port slot.
The slot is reserved before the original connect starts.

Native operations retain their original logical result and separate borrow
release acknowledgement. Destroy first requests cancellation of admitted
operations, waits for those original acknowledgements and the workers' chunk
cleanup, then consumes the original connection through close. A failed or
unknown acknowledgement/destruction retains the private registry entry.
Borrow release never certifies physical IoCall/IoTransfer retirement.

The selected generated export checks the same private registry after the
application resolves, inside its original error handler and before result
lowering. A second check precedes canonical publication. During the original
synchronous lowering, resolve and exit tail, a private admission fence rejects
new Socket reservations/connects before any CAP call, including reentrant
result getters and resolve callbacks. Its finally restores the fence on error;
it does not certify later jobs or whole-root quiescence. The snapshot footer
remains assertion-only and checks the registry before snapshot mode ends.
The initializer installs the registry before application ESM evaluation;
application imports cannot select or replace its transport. An actual linked
module in the bundler output selects this profile; an unused, erased import
does not. Unselected application bundles and generated JavaScript bindings
retain their default bytes. Normal project capture and compiler declaration
staging also include `net.d.ts`; this does not select a runtime module, grant
a capability or require that new declaration in an old unselected capture.

Application completion requires **completed close**, not merely calling
`end()` or `destroy()`. Ordinary code can await a Promise resolved by the normal
Socket `close` event, while rejecting on `error`. Returning while close
acknowledgement is still pending fails the registry check. The public `closed`
property describes logical stream destruction, as in Node; it is not proof of
borrow acknowledgement, consuming native close or physical retirement. Idle sockets,
persistent pools and automatic accepted-close drainage remain unsupported.

There is no TLS Socket API, DNS API, listener/server, descriptor namespace,
address export, proxy, arbitrary socket option, custom lookup or family
fallback. Unsupported operations fail closed. This is a finite Socket API;
it does not claim the complete Node stream/Duplex surface or compatibility
with arbitrary npm networking packages.

The finite 25 host controls include the pinned parser/bundler/typechecker,
an authenticated previous raw generated initializer, and bounded real Node24
loopback references for the promised callback/close ordering. The raw fixture
contains the old diagnostic Gate; it remains mechanism evidence, not a new
signed Socket qualification. Native handle/ACK holds, distinct cancellation
acknowledgements, callback throws and caught synchronous emit errors are
controlled separately. No host model count proves physical Task retirement.

The private Socket coordinator uses synchronous completion transitions driven
by its existing original result/ACK observer jobs, without private async worker
Promise chains. It retains an operation through its callback tail; consuming
close waits actual native/cancel ACKs, chunk disposal and synchronous callback
tails. The ordinary queued close notification retains the registry until its
listeners return. User callback throws escape unchanged; a synchronous emit
throw caught by its caller does not poison the Socket. Listener-returned
Promises retain normal Node/global runtime obligations and are not implicitly
awaited. This is not whole-root/persistent-pool drainage qualification.

Actual normal no-Gate components have compiled and packaged. Fixture namespace
and tenant-signing failures were corrected without weakening normal admission.
The first signed echo then failed Task16 in runs
[40131804673](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40131804673),
[40134104074](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40134104074)
and [40138401959](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40138401959).
The latter passed all 21 then-current pinned controls and host compilation but
completed zero signed cells: Task16/QueuedWork12/Result2/Native48, with fifteen
parked tasks. Original post-root stream, I/O, pool, Store and activation counters
were all zero. Those remain failed receipts. Removing duplicate ACK awaits and
an unused observation sink did not resolve the peak. The completion coordinator
still needs its actual signed campaign; no physical Task benefit is claimed.

Task16 is the fixture's explicit stress-profile choice, not a production default
or a qualified minimum. Production activation runtime installation is opt-in
and requires operator-selected limits; no TypeScript minimum successful resource
profile has been established. The fixture limits remain Task16/Executor2/
Queued16/Wait8/Timer8/Result8/Native64. Whole #745 AC7, ordinary published client
compatibility and the whole-cost criterion remain open.

The pending owning programme extends the existing signed stream target with
one normal no-Gate Socket component. Its six cells cover echo/EOF and ordinary
close events, a sibling write while the primary read is held, zero-contact
alternate-endpoint denial, destroy with original cancellation acknowledgements,
failed root with unclosed stream owners, and fresh success on the same
backend. It retains the normal one-billion fuel grant, 128MiB memory, 120s root
wall bound and eight OutboundRequests. That budget dimension charges connects;
it does not count every read/write/chunkBytes WIT dispatch. The unchanged
installed stream policy has an operations ceiling of 128, and the unchanged
broker maximum_calls_per_session is 16. All original Task/Queue/Native bounds
remain enforced; no cap is enlarged for qualification. The unclosed cell requires the actual
two-read/owner sample before peer permission, control close, a failed root with its original closed public code,
no recorded admission/quota/stop refusal, physical idle, a paired closed positive
and fresh success under the same bounds. Its original public classification
must be coherent `runtime-error` or `unreachable-code`; missing, ambiguous,
stack/memory/allocation/other known trap classifications fail the programme.
Original JavaScript error text is
intentionally redacted: the original failure cause remains unknown and guard
attribution is source-only. This does not prove that the guard instruction ran;
it does not qualify the complete diagnostics or root-quiescence contract.
No result from this pending programme is claimed here.
