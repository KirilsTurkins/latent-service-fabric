# Bounded .NET client

`Latent.Sdk.Transport.BoundedClient` is the executable implementation of both
`ILatentClient` and the complete [eight-operation profile](../profile/README.md).
Generated Protobuf/gRPC types stay in the transport assembly; callers use the
portable `Latent.Sdk` and `Latent.Sdk.Profile` types. This is a host client, not
a .NET Wasm guest binding or a browser transport.

## Qualified profile

| Surface | Contract |
| --- | --- |
| Platform | Linux x86-64; SDK 8.0.425, runtime 8.0.31, `net8.0` |
| Endpoint | Exact numeric loopback `http://127.0.0.1:PORT` or `http://[::1]:PORT`; HTTP/2 prior knowledge |
| Authentication | Explicit bounded bearer token; no environment discovery, logging, redirects, cookies, proxies or caller-lineage authority |
| Ownership | One owned TCP connection and reusable `SocketsHttpHandler`/`HttpClient` for the client's lifetime |
| Recovery | Reserved admission for Cancel/GetActivation/GetPolicyOperation; no automatic invocation, mutation or connection replacement |
| Shutdown | `Dispose()` aborts without blocking; await `DisposeAsync()` for bounded physical reclamation |

Remote listeners, TLS/mTLS, DNS, routing, .NET browser/Wasm and other operating
systems are not qualified. SDK/runtime pins do not freeze the independently
versioned wire contracts. Update dependencies through the graph/generation and
native test gates rather than bypassing a pin.

## Bounds and cancellation

`ConnectAsync(ClientOptions, CancellationToken)` creates the connection under
the configured two-second default connect deadline. The additive
`AdoptConnectionAsync` transfers an already-connected numeric-loopback socket
to the client on entry, including disposal on validation/startup failure. Never
use, close or lend that socket after calling it. Arbitrary externally owned
HttpClient/handlers are not accepted, so hidden retry/connection pools cannot
escape this ownership model.

Defaults are eight in-flight calls, two reserved recovery slots, eight queued
calls, 1 MiB request/response frames, 16 KiB headers, and an 8 MiB/8192-node
input graph ceiling. Configurable maxima are 32 in-flight, 64 queued, 4 MiB
frames, 32 KiB headers and 32 MiB/16384 graph nodes. Management operations apply
their smaller authoritative limits as well. Admission and wire-stream tracking
both enforce the bounds; a cancelled logical call does not release physical
stream capacity early. These are client-owned bounds, not a whole-process RSS
or framework-allocation guarantee.

Each call uses one monotonic local deadline: default five seconds, maximum
30 seconds, with zero expiring immediately. Queueing, send, receive, decoding
and local completion consume that same budget. The exact full-width remote
invocation deadline and guest wall-time budget remain separate wire values.
Unrepresentable local clock conversions are rejected, never wrapped. A caller
token cancels local waiting; it is not an explicit server Cancel disposition.
Use a fresh live token for subsequent Cancel/GetActivation recovery.

Await each returned `ValueTask` only once, or call `AsTask()` once and retain
that Task. Request `ReadOnlyMemory<byte>`, dictionary backing storage and nested
collections remain caller-owned and must stay valid and unchanged until the
operation completes; read-only interfaces do not make mutable backing storage
immutable. Conversion makes bounded wire copies; returned payloads/collections
belong to the response and never borrow the transport receive buffer.

## Outcomes and recovery

Keep activation and operation IDs before sending. The client preserves nullable
presence, full `ulong` values, opaque payload bytes and unknown enum values.
Successful transport still distinguishes success, declared application error
and platform failure. Transport/protocol failures use `ClientException`;
`ClientCancellationException` also follows native cancellation conventions.
Inspect its typed `Failure`, dispatch knowledge and original identity.

Lost responses remain uncertain. Query GetActivation/GetPolicyOperation using
the original identity; bounded not-found does not prove nonexecution. Mutations
retain generation preconditions, exact replay receipts and independent audit
status/attempt fields. No retry, new ID, fabricated acknowledgement or automatic
Cancel is added. Legacy interfaces remain available via `client.Legacy`, but
use the profile facade to retain rich management/error metadata.

## Clean-checkout validation and example

Install the pinned tools from [the toolchain guide](../../docs/development/toolchain.md).
From the repository root:

```bash
python3 -m unittest discover -s sdk/dotnet -p test_validate.py
python3 sdk/dotnet/validate.py --check --osv
```

The validator builds the example as well as both SDK assemblies and tests,
using two fresh locked restores and signature/graph/generation verification.
`tools/validate_sdks.sh` runs these focused checks without the optional live
advisory query; the security workflow owns the separate advisory gate.

The maintained language-native example is
[`Latent.Sdk.ProviderWorkflow`](Latent.Sdk.ProviderWorkflow/Program.cs).
For a retained executable, run from `sdk/dotnet`:

```bash
dotnet restore Latent.Sdk.ProviderWorkflow/Latent.Sdk.ProviderWorkflow.csproj \
  --locked-mode --configfile nuget.transport.config \
  -p:ArtifactsPath="$PWD/target/example" \
  -p:ImportDirectoryBuildProps=false -p:ImportDirectoryBuildTargets=false \
  -p:ImportDirectoryPackagesProps=false
dotnet build Latent.Sdk.ProviderWorkflow/Latent.Sdk.ProviderWorkflow.csproj \
  --no-restore --disable-build-servers --artifacts-path "$PWD/target/example" \
  -p:ImportDirectoryBuildProps=false -p:ImportDirectoryBuildTargets=false \
  -p:ImportDirectoryPackagesProps=false
dotnet target/example/bin/Latent.Sdk.ProviderWorkflow/debug/Latent.Sdk.ProviderWorkflow.dll \
  --config /absolute/private/input.json
```

The config is the exact `latent.sdk.provider.workflow.input.v1` document created
by the shared operator runner in PR #366, with `language: dotnet`. Its
[bounded parser](Latent.Sdk.ProviderWorkflow/Input.cs) requires a private 0700
input directory and 0600 file/credential. It contains endpoint, tenant, credential
file, controlled upstream, scoped guest targets, control directory and a policy
document, never direct HTTP/blob provider secrets. Do not invent IDs or copy
expired signed fixtures. Stage fresh operator-authorized guests with the shared
runner; then the example itself performs the eight typed RPCs without invoking
another executable.

HTTP/blob calls execute through authorized guests with preserved WIT JSON
framing (`"2201"` and `"4"` stay exact unsigned decimal values). Four actual held
requests distinguish local cancellation, explicit Cancel, deadline and shutdown.
The [qualification evidence](EVIDENCE.md) separates this real-node execution
from controlled peer tests and the remaining shared CI integration.
