# Synchronous Send in the captured WASI HTTP profile

The maintained compiler source derives both default-handler synchronous `Send` methods
only when the existing captured TaskWait/CoreLib and standard HTTP profile are
selected together. Ordinary `new HttpClient()` construction stays intact. The
error-only profile keeps its original unsupported synchronous method.

The original `WasiHttpHandler.Send` throws `PlatformNotSupportedException` in
[the maintained .NET RC1 source](https://github.com/dotnet/runtime/blob/v10.0.0-rc.1.25451.107/src/libraries/System.Net.Http/src/System/Net/Http/WasiHttpHandler/WasiHttpHandler.cs).
The outer `HttpClientHandler.Send` has a separate WASI unsupported throw in
[the same pinned framework source](https://github.com/dotnet/runtime/blob/v10.0.0-rc.1.25451.107/src/libraries/System.Net.Http/src/System/Net/Http/HttpClientHandler.cs).
Adapting the inner method alone leaves ordinary `HttpClient.Send` unsupported.
The compiler verifies the original default construction path and each exact
throw, method signature, virtual slot and framework reference identity before
changing those two methods through separate method-only ports.

Each derived method passes the original request and cancellation token to its
own unchanged `SendAsync`, then joins its original Task through `GetAwaiter` and
`GetResult`. The separately authenticated CoreLib supplies that join. It adds
no handler, task pump, request replay, host import, capability or budget.
`SendAsync`, request validation, body handling, cancellation and response
ownership retain their original implementations. The outer port therefore
keeps the original lazy handler/telemetry chain. Each port checks that every
other method is unchanged; the serialized product is reopened and checked as
in the existing port.

At entry, the outer synchronous method calls the original CoreLib
`CancellationToken.ThrowIfCancellationRequested` before `SendAsync`. The
compiler checks the existing method reference and token identity. An already
cancelled token therefore cannot start an outbound attempt or open a peer
connection. This adds no cancellation implementation to `SendAsync`.

The whole original System.Net.Http digest remains
`3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587`.
The existing pinned Cecil digest and both actual ILC references remain
mandatory. The nested `dotnet-wasi-sync-send-v1` and
`dotnet-default-httpclient-sync-send-v1` receipts have closed field sets and
exact types; either missing or altered evidence fails before compiler project
references are published. Their `nativeSendQualified` values remain false.

The existing fifteen inner-handler host controls remain intact. A separate
nineteen-control captured-BCL probe covers the outer default handler, with an
original-as-derived negative control that must reject its unsupported throw. Each probe
constructs the original default client/handler path in separate original and
derived contexts, demonstrates the original unsupported synchronous method,
and compares the derived synchronous faults with original and derived async
faults for invalid requests. Those paths fail before WASI I/O. They establish
neither successful transmission nor genuinely pending guest progress.
The outer probe also supplies a valid request with an already-cancelled token:
the original synchronous method stays unsupported, while the derived method
throws the original `OperationCanceledException` carrying that same token.

The original fourteen signed HTTP cases and their source remain unchanged.
The new API still needs a signed emitted component calling ordinary
`HttpClient.Send` for success, HTTP errors, buffered/streamed bodies, pending
cancellation, disposal, uncertain POST and fresh-state/owner retirement under
the original authority and resource limits. A host-source build or completed
fault probe cannot supply that evidence. Named factory and unchanged-library
qualification and the broader #693/#746 requirements remain separate.

## Signed component qualification

The maintained `qualify_dotnet_standard_http.py --synchronous-send` entry point
builds a separate ordinary application component through the normal captured
NativeAOT compiler, packaging, fixture signing, admission and enforced node.
Its fixture changes only the original request call to
`client.Send(request, HttpCompletionOption.ResponseHeadersRead, token)` and
adds an already-cancelled-token case. The original `SendAsync` source and
fourteen-case qualification command remain intact.

The API label binds to the exact captured `src/Main.cs`, complete source
snapshot and observed component before signing. The synchronous run executes
all fourteen original cases plus pre-cancellation. It retains the original
compile, node, invocation, authority, fuel, memory, timer and owner limits.
Every invocation must resolve the same signed component revision, return its
expected fresh-state value and pass the existing complete owner-idle checks.
The provider peer must observe exactly the original twelve request vectors:
cancelled headers and partial bodies actually enter unreleased gates, and the
uncertain POST commits once without a response. Pre-cancellation and the two
denials add no peer contact. Peer observations supplement the independent
node/provider accounting; they do not prove a refund or external rollback.
The pre-cancelled invocation must also report zero outbound attempts. Bounded
peer observations are retained before the final assertions, including on
failure, after checking that they contain no per-run credential or token.

The owning .NET workflow runs this command after the unchanged async HTTP
qualification and retains its complete success or failure directory. Until
that emitted component actually passes, this is a qualification programme,
not signed `Send` evidence. It does not cover two unchanged libraries,
factory middleware, default-buffering `Send` overloads, all options,
cross-tenant state or broader runtime limits.

## Asynchronous pre-cancellation

The same TaskWait-selected BCL derivation also checks an already-cancelled token
at the entry to the pinned `WasiHttpHandler.SendAsync`. The original 63-byte IL
preimage is authenticated separately. The prefix returns CoreLib's ordinary
`Task.FromCanceled<HttpResponseMessage>` with that exact token; it does not enter
the original async state machine or allocate its WASI request wrapper. For an
uncancelled token, every original instruction and the state machine remain
unchanged. The default outer handler still validates a null request first.

The host probe compares the retained original and derived assemblies using
requests whose absent URI faults before any WASI import. It checks cancelled
Task state/token, outer validation and unchanged uncancelled faults. This is
host BCL evidence, not proof of zero provider dispatch or pending-I/O retirement.

The separate `--pre-cancelled-async` signed programme retains all fourteen
original async cases and adds one already-cancelled call. The original async
and fifteen-case synchronous fixture bytes stay unchanged. The extra programme
requires an integer zero outbound-attempt count, the same signed revision,
per-call physical idle checks, all twelve original peer vectors and clean
shutdown under the existing bounds. Until its actual component passes, that
gate is pending. This slice establishes no post-dispatch cancellation, new
factory/content profile, default-pool behavior or full #693 completion.
