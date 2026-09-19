using System.Net;
using System.Net.Sockets;
using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transport;

public sealed record ClientSnapshot(bool Closed, int InFlight, int Queued, int WireStreams, bool Reaped);

public sealed partial class BoundedClient : IAsyncDisposable, IDisposable
{
    private readonly object gate = new();
    private readonly ClientOptions config;
    private readonly Uri endpoint;
    private readonly OwnedStream stream;
    private readonly Http2WireState wire;
    private readonly HttpClient http;
    private readonly CancellationTokenSource lifetime = new();
    private TaskCompletionSource changed = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly TaskCompletionSource drained = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private Task? disposal;
    private int handedOff;
    private int active;
    private int normal;
    private int queued;
    private bool closed;

    private BoundedClient(ClientOptions config, Uri endpoint, IPEndPoint address, Socket socket)
    {
        this.config = config;
        this.endpoint = endpoint;
        wire = new(config.MaxInFlight, config.ReservedRecovery, Pulse);
        stream = new(socket, wire, config.ConnectTimeout, Abort);
        var handler = new SocketsHttpHandler
        {
            AllowAutoRedirect = false, UseCookies = false, UseProxy = false, AutomaticDecompression = DecompressionMethods.None,
            MaxConnectionsPerServer = 1, EnableMultipleHttp2Connections = false, InitialHttp2StreamWindowSize = 65536,
            MaxResponseHeadersLength = config.MaxHeaderBytes / 1024, ConnectTimeout = config.ConnectTimeout,
            PooledConnectionIdleTimeout = System.Threading.Timeout.InfiniteTimeSpan,
            PooledConnectionLifetime = System.Threading.Timeout.InfiniteTimeSpan,
            ActivityHeadersPropagator = null,
            ConnectCallback = (context, cancellationToken) =>
            {
                if (cancellationToken.IsCancellationRequested || lifetime.IsCancellationRequested || context.DnsEndPoint.Port != address.Port ||
                    !IPAddress.TryParse(context.DnsEndPoint.Host, out IPAddress? target) || !target.Equals(address.Address) ||
                    Interlocked.Exchange(ref handedOff, 1) != 0)
                    throw new IOException("automatic connection replacement is forbidden");
                return new ValueTask<Stream>(stream);
            }
        };
        http = new HttpClient(handler, disposeHandler: true) { Timeout = System.Threading.Timeout.InfiniteTimeSpan };
    }

    public override string ToString() => "Latent bounded .NET client (redacted)";

    public static ValueTask<BoundedClient> ConnectAsync(ClientOptions options, CancellationToken cancellationToken = default) =>
        ConnectCoreAsync(options, null, false, cancellationToken);

    public static ValueTask<BoundedClient> AdoptConnectionAsync(ClientOptions options, Socket connection, CancellationToken cancellationToken = default) =>
        ConnectCoreAsync(options, connection, true, cancellationToken);

    private static async ValueTask<BoundedClient> ConnectCoreAsync(ClientOptions options, Socket? supplied, bool adopt, CancellationToken caller)
    {
        Socket? socket = supplied;
        bool transferred = false;
        try
        {
            if (options is null || (adopt && socket is null)) throw ClientOptions.Invalid();
            (Uri endpoint, IPEndPoint address) = options.Validate();
            using var startup = CancellationTokenSource.CreateLinkedTokenSource(caller);
            startup.CancelAfter(options.ConnectTimeout);
            try
            {
                startup.Token.ThrowIfCancellationRequested();
                if (!adopt)
                {
                    socket = new Socket(address.AddressFamily, SocketType.Stream, ProtocolType.Tcp);
                    await socket.ConnectAsync(address, startup.Token).ConfigureAwait(false);
                }
                if (socket!.RemoteEndPoint is not IPEndPoint remote || socket.LocalEndPoint is not IPEndPoint local ||
                    !remote.Equals(address) || !IPAddress.IsLoopback(local.Address) || socket.SocketType != SocketType.Stream || socket.ProtocolType != ProtocolType.Tcp)
                    throw ClientOptions.Invalid();
                socket.NoDelay = true;
                socket.SendBufferSize = 65536;
                socket.ReceiveBufferSize = 65536;
                var result = new BoundedClient(options, endpoint, address, socket);
                transferred = true;
                return result;
            }
            catch (OperationCanceledException)
            {
                var failure = ClientOptions.Failure(caller.IsCancellationRequested ? Profile.FailureCategory.LocalCancelled : Profile.FailureCategory.Deadline,
                    "loopback startup cancelled or expired");
                throw new Profile.ClientCancellationException(failure.Failure, caller.IsCancellationRequested ? caller : startup.Token);
            }
            catch (Exception failure) when (failure is SocketException or IOException or ObjectDisposedException)
            {
                throw ClientOptions.Failure(Profile.FailureCategory.Transport, "loopback connection failed");
            }
        }
        finally
        {
            if (!transferred) socket?.Dispose();
        }
    }

    public ClientSnapshot Snapshot()
    {
        lock (gate)
        {
            var state = wire.Snapshot();
            return new(closed, active, queued, state.Streams, disposal is { IsCompletedSuccessfully: true } && stream.InFlight == 0 && active == 0 && queued == 0);
        }
    }

    public void Dispose() => Abort();

    public ValueTask DisposeAsync()
    {
        Abort();
        lock (gate) return new ValueTask(disposal!);
    }

    private void Abort()
    {
        lock (gate)
        {
            if (closed) return;
            closed = true;
            if (active == 0 && queued == 0) drained.TrySetResult();
            PulseLocked();
            disposal = FinishDisposeAsync();
        }
        lifetime.Cancel();
        http.Dispose();
        stream.Dispose();
    }

    private async Task FinishDisposeAsync()
    {
        await Task.Yield();
        try
        {
            using var deadline = new CancellationTokenSource(config.ConnectTimeout);
            await drained.Task.WaitAsync(deadline.Token).ConfigureAwait(false);
            await stream.Drained.WaitAsync(deadline.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw ClientOptions.Failure(Profile.FailureCategory.Transport, "async transport disposal exceeded its retirement bound");
        }
    }

    private async ValueTask AcquireAsync(CallState state, CancellationToken cancellationToken)
    {
        bool waiting = false;
        try
        {
            while (true)
            {
                Task wake;
                lock (gate)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    if (closed) throw state.Error(Profile.FailureCategory.Transport, "client is closed");
                    var capacity = wire.Snapshot();
                    bool available = capacity.Ready
                        ? active < capacity.Maximum && capacity.Streams < capacity.Maximum && (state.Recovery || normal < capacity.Maximum - config.ReservedRecovery)
                        : active == 0;
                    if (available)
                    {
                        if (waiting) { queued--; waiting = false; }
                        active++;
                        if (!state.Recovery) normal++;
                        return;
                    }
                    if (!waiting)
                    {
                        if (queued >= config.MaxQueued) throw state.Error(Profile.FailureCategory.Limit, "client admission queue is full");
                        waiting = true;
                        queued++;
                    }
                    wake = changed.Task;
                }
                await wake.WaitAsync(cancellationToken).ConfigureAwait(false);
            }
        }
        finally
        {
            if (waiting)
            {
                lock (gate)
                {
                    queued--;
                    if (closed && active == 0 && queued == 0) drained.TrySetResult();
                }
            }
        }
    }

    private void Release(CallState state)
    {
        lock (gate)
        {
            active--;
            if (!state.Recovery) normal--;
            if (closed && active == 0 && queued == 0) drained.TrySetResult();
            PulseLocked();
        }
    }

    private void Pulse()
    {
        lock (gate) PulseLocked();
    }

    private void PulseLocked()
    {
        TaskCompletionSource previous = changed;
        changed = new(TaskCreationOptions.RunContinuationsAsynchronously);
        previous.TrySetResult();
    }
}
