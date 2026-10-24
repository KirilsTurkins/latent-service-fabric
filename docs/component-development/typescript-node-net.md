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
65,536 queued write bytes and 16,384 bytes per transfer.
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

The fourteen Socket controls and three owning project/record/entry guards are
host-only source/protocol evidence. They include
the actual pinned parser/bundler/typechecker and an authenticated previous
raw generated source fixture. That fixture includes the old diagnostic Gate;
it is mechanism evidence, not qualification of a new ordinary no-Gate Socket
component. No new Socket component has been compiled or signed/executed yet.
Ordinary signed TCP, cancellation/root drain, physical ownership and published
client compatibility need their actual owning programme. Whole #745 AC7 and
the whole-cost criterion remain open.

The pending owning programme extends the existing signed stream target with
one normal no-Gate Socket component. Its six cells cover echo/EOF and ordinary
close events, a sibling write while the primary read is held, zero-contact
alternate-endpoint denial, destroy with original cancellation acknowledgements,
failed root with unclosed stream owners, and fresh success on the same
backend. It retains the normal one-billion fuel grant, eight outbound calls,
and the original Task/Queue/Native bounds. The unclosed cell requires the actual
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
