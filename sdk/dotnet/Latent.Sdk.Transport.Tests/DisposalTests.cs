using System.Net;
using System.Net.Sockets;
using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    private sealed class HeldDisposalSocket : Socket
    {
        private readonly TaskCompletionSource entered;
        private readonly ManualResetEventSlim release;
        private int held;

        internal HeldDisposalSocket(TaskCompletionSource entered, ManualResetEventSlim release)
            : base(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp)
        {
            this.entered = entered;
            this.release = release;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && Interlocked.Exchange(ref held, 1) == 0)
            {
                entered.TrySetResult();
                if (!release.Wait(TimeSpan.FromSeconds(3)))
                    throw new TimeoutException("controlled socket disposal was not released");
            }
            base.Dispose(disposing);
        }
    }

    private static async Task DisposalOwnsSocketTeardown()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start(1);
        try
        {
            foreach (bool exceedBound in new[] { false, true })
            {
                using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
                using var release = new ManualResetEventSlim(false);
                var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                using var socket = new HeldDisposalSocket(entered, release);
                Task<Socket> accept = listener.AcceptSocketAsync(deadline.Token).AsTask();
                await socket.ConnectAsync(listener.LocalEndpoint, deadline.Token);
                using Socket remote = await accept;
                int port = ((IPEndPoint)listener.LocalEndpoint).Port;
                BoundedClient client = await BoundedClient.AdoptConnectionAsync(Options("http://127.0.0.1:" + port), socket);
                // No RPC or stream owner remains to mask an unfinished socket close.
                Task first = Task.Run(async () => await client.DisposeAsync());
                try
                {
                    await entered.Task.WaitAsync(deadline.Token);
                    Task concurrent = client.DisposeAsync().AsTask();
                    Check(!client.Snapshot().Reaped && !socket.SafeHandle.IsClosed,
                        "held adopted socket teardown was reported as physically reaped");
                    if (exceedBound)
                    {
                        await Failure(concurrent, Profile.FailureCategory.Transport);
                        Check(!client.Snapshot().Reaped && !socket.SafeHandle.IsClosed,
                            "retirement timeout hid an unfinished adopted socket close");
                    }
                    else
                    {
                        Check(!concurrent.IsCompleted, "concurrent disposal completed before socket teardown");
                        release.Set();
                        await concurrent.WaitAsync(deadline.Token);
                        await first.WaitAsync(deadline.Token);
                        Check(socket.SafeHandle.IsClosed && client.Snapshot().Reaped,
                            "released adopted socket teardown retained an owner");
                    }
                }
                finally
                {
                    release.Set();
                    if (exceedBound)
                        await Failure(first, Profile.FailureCategory.Transport);
                    else
                        await first.WaitAsync(deadline.Token);
                }
                Check(socket.SafeHandle.IsClosed, "controlled adopted socket escaped final cleanup");
            }
        }
        finally { listener.Stop(); }
    }
}
