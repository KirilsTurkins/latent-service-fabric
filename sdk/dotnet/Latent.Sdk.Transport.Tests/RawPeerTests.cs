using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    private static async Task NoReplay()
    {
        foreach (bool goaway in new[] { false, true })
        foreach (bool mutation in new[] { false, true })
        {
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start(4);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(4));
            int requests = 0;
            bool physicalClose = false;
            Task peer = Task.Run(async () =>
            {
                using TcpClient accepted = await listener.AcceptTcpClientAsync(deadline.Token);
                using NetworkStream socket = accepted.GetStream();
                byte[] preface = new byte[24];
                await socket.ReadExactlyAsync(preface, deadline.Token);
                Check(preface.AsSpan().SequenceEqual("PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"u8), "raw peer did not receive HTTP/2");
                await socket.WriteAsync(Frame(4, 0, 0, [0, 3, 0, 0, 0, 8]), deadline.Token);
                while (true)
                {
                    byte[] header = new byte[9];
                    if (await socket.ReadAsync(header.AsMemory(0, 1), deadline.Token) == 0) { physicalClose = true; break; }
                    await socket.ReadExactlyAsync(header.AsMemory(1), deadline.Token);
                    int length = header[0] << 16 | header[1] << 8 | header[2];
                    Check(length <= 16384, "client frame exceeds raw peer bound");
                    byte[] payload = new byte[length];
                    await socket.ReadExactlyAsync(payload, deadline.Token);
                    if (header[3] == 4 && (header[4] & 1) == 0) await socket.WriteAsync(Frame(4, 1, 0, []), deadline.Token);
                    if (header[3] == 6 && (header[4] & 1) == 0) await socket.WriteAsync(Frame(6, 1, 0, payload), deadline.Token);
                    if (header[3] == 1)
                    {
                        requests++;
                        int identity = BinaryPrimitives.ReadInt32BigEndian(header.AsSpan(5)) & int.MaxValue;
                        await socket.WriteAsync(goaway ? Frame(7, 0, 0, new byte[8]) : Frame(3, 0, identity, [0, 0, 0, 7]), deadline.Token);
                    }
                }
            });
            try
            {
                await using BoundedClient client = await BoundedClient.ConnectAsync(Options("http://" + listener.LocalEndpoint));
                Task call = mutation ? client.ApplyPolicyAsync(Apply(), Defaults).AsTask() : client.InvokeAsync(Invoke(), Defaults).AsTask();
                Profile.ClientFailure failure = await Failure(call, Profile.FailureCategory.Transport, true);
                Check(failure.Outcome == Profile.OutcomeKnowledge.Unknown && (mutation ? failure.Identity.OperationId == "operation-a" : failure.Identity.ActivationId == "activation-a"), "reset lost uncertainty or original identity");
                await client.DisposeAsync();
                await peer.WaitAsync(deadline.Token);
                Check(requests == 1 && physicalClose && !listener.Pending() && client.Snapshot().Reaped, "REFUSED_STREAM/GOAWAY replayed, reconnected, or leaked");
                await Failure(client.GetPolicyOperationAsync(new("operation-a"), Defaults).AsTask(), Profile.FailureCategory.Transport, false);
                Check(!listener.Pending(), "closed owner opened a replacement connection");
            }
            finally { deadline.Cancel(); listener.Stop(); }
        }
    }

    private static byte[] Frame(byte kind, byte flags, int identity, byte[] payload)
    {
        byte[] packet = new byte[payload.Length + 9];
        packet[0] = (byte)(payload.Length >> 16);
        packet[1] = (byte)(payload.Length >> 8);
        packet[2] = (byte)payload.Length;
        packet[3] = kind;
        packet[4] = flags;
        BinaryPrimitives.WriteInt32BigEndian(packet.AsSpan(5), identity);
        payload.CopyTo(packet, 9);
        return packet;
    }

    private static async Task StalledRawPeers()
    {
        foreach (bool cancel in new[] { false, true })
        {
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start(4);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(4));
            using var caller = new CancellationTokenSource();
            var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var retired = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            int requests = 0;
            bool physicalClose = false;
            Task peer = Task.Run(async () =>
            {
                using TcpClient accepted = await listener.AcceptTcpClientAsync(deadline.Token);
                using NetworkStream socket = accepted.GetStream();
                byte[] preface = new byte[24];
                await socket.ReadExactlyAsync(preface, deadline.Token);
                Check(preface.AsSpan().SequenceEqual("PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"u8), "stalled peer did not observe HTTP/2");
                await socket.WriteAsync(Frame(4, 0, 0, [0, 3, 0, 0, 0, 2]), deadline.Token);
                while (true)
                {
                    byte[] header = new byte[9];
                    if (await socket.ReadAsync(header.AsMemory(0, 1), deadline.Token) == 0) { physicalClose = true; break; }
                    await socket.ReadExactlyAsync(header.AsMemory(1), deadline.Token);
                    int length = header[0] << 16 | header[1] << 8 | header[2];
                    Check(length <= 16384, "stalled peer frame bound");
                    byte[] payload = new byte[length];
                    await socket.ReadExactlyAsync(payload, deadline.Token);
                    if (header[3] == 4 && (header[4] & 1) == 0) await socket.WriteAsync(Frame(4, 1, 0, []), deadline.Token);
                    if (header[3] == 6 && (header[4] & 1) == 0) await socket.WriteAsync(Frame(6, 1, 0, payload), deadline.Token);
                    if (header[3] == 1) { requests++; started.TrySetResult(); }
                    if (header[3] == 3) retired.TrySetResult();
                }
            });
            try
            {
                await using BoundedClient client = await BoundedClient.ConnectAsync(Options("http://" + listener.LocalEndpoint, inflight: 2, recovery: 1, queue: 1));
                Task pending = client.InvokeAsync(Invoke("raw-held"), new(400), caller.Token).AsTask();
                await started.Task.WaitAsync(deadline.Token);
                Profile.ClientFailure queued = await Failure(client.InvokeAsync(Invoke("raw-queued"), new(30)).AsTask(), Profile.FailureCategory.Deadline, false);
                Check(queued.Identity.ActivationId == "raw-queued" && queued.Outcome == Profile.OutcomeKnowledge.NotDispatched, "queued deadline lost original identity");
                if (cancel) caller.Cancel();
                Profile.ClientFailure failure = await Failure(pending, cancel ? Profile.FailureCategory.LocalCancelled : Profile.FailureCategory.Deadline, true);
                Check(failure.Identity.ActivationId == "raw-held" && failure.Outcome == Profile.OutcomeKnowledge.Unknown, "raw local failure invented an outcome");
                await retired.Task.WaitAsync(deadline.Token);
                await Until(() => client.Snapshot().WireStreams == 0);
                await client.DisposeAsync();
                await peer.WaitAsync(deadline.Token);
                Check(requests == 1 && physicalClose && !listener.Pending() && client.Snapshot().Reaped, "raw deadline/cancel replayed or leaked a physical owner");
            }
            finally { deadline.Cancel(); listener.Stop(); }
        }
    }

    private static Task FrameFragments()
    {
        byte[] packet = Frame(4, 0, 0, [0, 3, 0, 0, 0, 8, 0, 4, 0, 1, 0, 0])
            .Concat(Frame(4, 1, 0, [])).Concat(Frame(0, 1, 1, [0, 255, 128])).Concat(Frame(4, 0, 0, [0, 3, 0, 0, 0, 2])).ToArray();
        for (int fragment = 1; fragment <= packet.Length; fragment++)
        {
            var owner = new Http2WireState(8, 1, () => { });
            var observer = new Http2FrameObserver(owner, false);
            int acknowledgements = 0;
            for (int offset = 0; offset < packet.Length; offset += fragment)
                observer.Observe(packet.AsSpan(offset, Math.Min(fragment, packet.Length - offset)), null, ref acknowledgements);
            Check(owner.Snapshot() is { Maximum: 2, Ready: true, Streams: 0 }, "fragmented settings lost finite capacity");
        }
        foreach (byte kind in new byte[] { 3, 5, 7 })
        {
            var observer = new Http2FrameObserver(new(8, 1, () => { }), false);
            int acknowledgements = 0;
            try { observer.Observe(Frame(kind, 0, kind == 7 ? 0 : 1, new byte[8]), null, ref acknowledgements); }
            catch (IOException) { assertions++; continue; }
            throw new InvalidOperationException("replay-triggering control frame reached the managed handler");
        }
        return Task.CompletedTask;
    }
}
