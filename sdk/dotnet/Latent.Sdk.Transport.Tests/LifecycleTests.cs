using System.Net;
using System.Net.Sockets;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;
using WireInvocation = global::Latent.Invocation.V1;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    private static async Task CancellationAndQueue()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var retired = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        await using Peer peer = await Peer.Start(async context =>
        {
            if (context.Request.Path.Value!.EndsWith("/Invoke"))
            {
                await Peer.Read<WireInvocation.InvokeRequest>(context);
                started.TrySetResult();
                try { await Task.Delay(Timeout.Infinite, context.RequestAborted); }
                finally { retired.TrySetResult(); }
            }
            else if (context.Request.Path.Value.EndsWith("/GetActivation"))
                await Peer.Reply(context, new WireInvocation.ActivationStatus { ActivationId = "held-a", Phase = "running" });
            else if (context.Request.Path.Value.EndsWith("/Cancel"))
                await Peer.Reply(context, new WireInvocation.CancelResponse { Disposition = WireInvocation.CancelDisposition.Accepted });
            else throw new InvalidOperationException("queued request escaped admission");
        }, 2);
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint, 2, 1, 1));
        using var local = new CancellationTokenSource();
        Task held = client.InvokeAsync(Invoke("held-a"), Defaults, local.Token).AsTask();
        await started.Task.WaitAsync(TimeSpan.FromSeconds(3));
        using var waiting = new CancellationTokenSource();
        Task queued = client.GetPolicyAsync(new("policy-a", Profile.CapabilityPolicyRecordKind.Policy), Defaults, waiting.Token).AsTask();
        await Until(() => client.Snapshot().Queued == 1);
        await Failure(client.InvokeAsync(Invoke(), Defaults).AsTask(), Profile.FailureCategory.Limit, false);
        Check((await client.GetActivationAsync(new("held-a"), Defaults)).Value.Phase == "running", "recovery reservation unavailable");
        waiting.Cancel();
        await Failure(queued, Profile.FailureCategory.LocalCancelled, false);
        local.Cancel();
        Profile.ClientFailure failure = await Failure(held, Profile.FailureCategory.LocalCancelled, true);
        Check(failure.Identity.ActivationId == "held-a" && failure.Outcome == Profile.OutcomeKnowledge.Unknown, "cancellation lost original identity or uncertainty");
        await retired.Task.WaitAsync(TimeSpan.FromSeconds(3));
        Check(peer.Requests.Count == 2, "local cancellation sent an implicit Cancel");
        Check((await client.CancelAsync(new("held-a", "explicit"), Defaults)).Value.Disposition == Profile.CancelDisposition.Accepted, "fresh cancellation token could not recover");
        Check(peer.Connections.Count == 1 && peer.Requests.Values.Sum() == 3, "hidden reconnect or RPC replay");
    }

    private static async Task DeadlinesAndShutdown()
    {
        int started = 0;
        await using Peer peer = await Peer.Start(async context =>
        {
            Interlocked.Increment(ref started);
            await Task.Delay(Timeout.Infinite, context.RequestAborted);
        }, 4);
        await using BoundedClient client = await BoundedClient.ConnectAsync(Options(peer.Endpoint, 4, 1, 4));
        await Failure(client.InvokeAsync(Invoke(), new(0)).AsTask(), Profile.FailureCategory.Deadline, false);
        await Failure(client.InvokeAsync(Invoke(), new(ulong.MaxValue)).AsTask(), Profile.FailureCategory.InvalidRequest, false);
        await Failure(client.InvokeAsync(Invoke(), new(30001)).AsTask(), Profile.FailureCategory.Limit, false);
        Check(started == 0, "invalid local timeouts dispatched");
        long before = Environment.TickCount64;
        await Failure(client.InvokeAsync(Invoke(), new(80)).AsTask(), Profile.FailureCategory.Deadline, true);
        Check(Environment.TickCount64 - before < 1500, "original deadline was extended");
        Task[] pending = Enumerable.Range(0, 7).Select(index => client.InvokeAsync(Invoke("close-" + index), Defaults).AsTask()).ToArray();
        await Until(() => client.Snapshot() is { InFlight: 3, Queued: 4 });
        await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => client.DisposeAsync().AsTask()));
        foreach (Task operation in pending) await Failure(operation, Profile.FailureCategory.Transport);
        Check(client.Snapshot() is { Reaped: true, InFlight: 0, Queued: 0, WireStreams: 0 }, "concurrent shutdown retained owners");
        await Failure(client.CancelAsync(new("close-0", "after-close"), Defaults).AsTask(), Profile.FailureCategory.Transport, false);
    }

    private static async Task ConnectionOwnership()
    {
        foreach (string endpoint in new[] { "http://localhost:1", "https://127.0.0.1:1", "http://127.0.0.1:1/", "http://127.0.0.1", "http://127.0.0.1:0001", "http://10.0.0.1:1", "http://user@127.0.0.1:1" })
            await Failure(BoundedClient.ConnectAsync(Options(endpoint)).AsTask(), Profile.FailureCategory.InvalidRequest, false);
        await using Peer peer = await Peer.Start(context => Peer.Reply(context, Peer.Success()));
        var endpointAddress = new Uri(peer.Endpoint);
        using var supplied = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
        await supplied.ConnectAsync(IPAddress.Loopback, endpointAddress.Port);
        await using BoundedClient client = await BoundedClient.AdoptConnectionAsync(Options(peer.Endpoint), supplied);
        await client.InvokeAsync(Invoke(), Defaults);
        await client.DisposeAsync();
        Check(supplied.SafeHandle.IsClosed && client.Snapshot().Reaped, "adopted socket was not owned through disposal");
        using var rejected = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
        await rejected.ConnectAsync(IPAddress.Loopback, endpointAddress.Port);
        await Failure(BoundedClient.AdoptConnectionAsync(Options("http://localhost:" + endpointAddress.Port), rejected).AsTask(), Profile.FailureCategory.InvalidRequest, false);
        Check(rejected.SafeHandle.IsClosed, "adopted socket leaked on constructor rejection");
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        await Failure(BoundedClient.ConnectAsync(Options(peer.Endpoint), cancellation.Token).AsTask(), Profile.FailureCategory.LocalCancelled, false);
        Check(!Options(peer.Endpoint).ToString().Contains(Token) && !client.ToString().Contains(Token), "credential exposed by formatting");
    }

    private static async Task ZeroLengthReads()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start(1);
        try
        {
            using var local = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            Task<Socket> accepted = listener.AcceptSocketAsync(deadline.Token).AsTask();
            await local.ConnectAsync(listener.LocalEndpoint, deadline.Token);
            using Socket remote = await accepted;
            bool faulted = false;
            var wire = new Http2WireState(8, 1, () => { });
            using var owned = new OwnedStream(local, wire, TimeSpan.FromSeconds(1), () => faulted = true);
            byte[] settings = Frame(4, 0, 0, [0, 3, 0, 0, 0, 8]);
            await remote.SendAsync(settings, deadline.Token);
            Check(await owned.ReadAsync(Memory<byte>.Empty, deadline.Token) == 0 && !faulted, "zero-length readiness probe became EOF");
            byte[] buffer = new byte[settings.Length];
            await owned.ReadExactlyAsync(buffer, deadline.Token);
            Check(wire.Snapshot().Ready && !faulted, "readiness probe consumed the HTTP/2 preface");
        }
        finally { listener.Stop(); }
    }
}
