# Synchronous Send in the captured WASI HTTP profile

The maintained compiler source derives the WASI handler's synchronous `Send`
only when the existing captured TaskWait/CoreLib and standard HTTP profile are
selected together. Ordinary `new HttpClient()` construction stays intact. The
error-only profile keeps its original unsupported synchronous method.

The original `WasiHttpHandler.Send` throws `PlatformNotSupportedException` in
[the maintained .NET RC1 source](https://github.com/dotnet/runtime/blob/v10.0.0-rc.1.25451.107/src/libraries/System.Net.Http/src/System/Net/Http/WasiHttpHandler/WasiHttpHandler.cs).
`HttpClientHandler` constructs that WASI handler through its original default
path. The compiler verifies that path and the exact original throw, method
signature, virtual slot and framework reference identities before changing
that one method.

The derived method passes the original request and cancellation token to the
unchanged `SendAsync`, then joins its original Task through `GetAwaiter` and
`GetResult`. The separately authenticated CoreLib supplies that join. It adds
no handler, task pump, request replay, host import, capability or budget.
`SendAsync`, request validation, body handling, cancellation and response
ownership retain their original implementations. Every other method is
checked before serialization, and the serialized product is reopened and
checked as in the existing port.

The whole original System.Net.Http digest remains
`3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587`.
The existing pinned Cecil digest and both actual ILC references remain
mandatory. The nested `dotnet-wasi-sync-send-v1` receipt has a closed field set
and exact types; missing or altered evidence fails before compiler project
references are published. Its `nativeSendQualified` value remains false.

The existing captured-BCL probe includes fifteen additional host controls. It
constructs the original default client/handler path in separate original and
derived contexts, demonstrates the original unsupported synchronous method,
and compares the derived synchronous faults with original and derived async
faults for invalid requests. Those paths fail before WASI I/O. They establish
neither successful transmission nor genuinely pending guest progress.

The original fourteen signed HTTP cases and their source remain unchanged.
The new API still needs a signed emitted component calling ordinary
`HttpClient.Send` for success, HTTP errors, buffered/streamed bodies, pending
cancellation, disposal, uncertain POST and fresh-state/owner retirement under
the original authority and resource limits. A host-source build or completed
fault probe cannot supply that evidence. Named factory and unchanged-library
qualification and the broader #693/#746 requirements remain separate.
