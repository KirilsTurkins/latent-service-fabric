using System.Net.Sockets;

namespace Latent.Sdk.Transport;

internal sealed class OwnedStream : Stream
{
    private readonly object gate = new();
    private readonly Stream inner;
    private readonly Http2WireState wire;
    private readonly Http2FrameObserver incoming;
    private readonly Http2FrameObserver outgoing;
    private readonly Action fault;
    private readonly TimeSpan writeTimeout;
    private readonly SemaphoreSlim writer = new(1, 1);
    private TaskCompletionSource drained = Completed();
    private int active;
    private bool closed;

    internal OwnedStream(Socket socket, Http2WireState wire, TimeSpan writeTimeout, Action fault)
    {
        inner = new NetworkStream(socket, ownsSocket: true);
        this.wire = wire;
        this.writeTimeout = writeTimeout;
        this.fault = fault;
        incoming = new(wire, false);
        outgoing = new(wire, true);
    }

    internal int InFlight { get { lock (gate) return active; } }
    internal Task Drained { get { lock (gate) return drained.Task; } }
    public override bool CanRead => true;
    public override bool CanWrite => true;
    public override bool CanSeek => false;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
    public override void Flush() { }
    public override Task FlushAsync(CancellationToken cancellationToken) => Task.CompletedTask;
    public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
    public override void SetLength(long value) => throw new NotSupportedException();

    public override int Read(byte[] buffer, int offset, int count)
    {
        Begin();
        try
        {
            int received = inner.Read(buffer, offset, count);
            if (count != 0) ObserveIncoming(buffer.AsSpan(offset, received));
            return received;
        }
        catch { fault(); throw; }
        finally { End(); }
    }

    public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) =>
        ReadAsync(buffer.AsMemory(offset, count), cancellationToken).AsTask();

    public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
    {
        Begin();
        try
        {
            int received = await inner.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
            if (!buffer.IsEmpty) ObserveIncoming(buffer.Span[..received]);
            return received;
        }
        catch { fault(); throw; }
        finally { End(); }
    }

    private void ObserveIncoming(ReadOnlySpan<byte> data)
    {
        if (data.IsEmpty) throw new IOException("owned HTTP/2 connection ended");
        int acknowledged = 0;
        incoming.Observe(data, null, ref acknowledged);
    }

    public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException("only asynchronous HTTP/2 writes are supported");
    public override Task WriteAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) =>
        WriteAsync(buffer.AsMemory(offset, count), cancellationToken).AsTask();

    public override async ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellationToken = default)
    {
        Begin();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        deadline.CancelAfter(writeTimeout);
        bool entered = false;
        try
        {
            await writer.WaitAsync(deadline.Token).ConfigureAwait(false);
            entered = true;
            var retired = new List<int>(32);
            int acknowledged = 0;
            outgoing.Observe(buffer.Span, retired, ref acknowledged);
            await inner.WriteAsync(buffer, deadline.Token).ConfigureAwait(false);
            foreach (int identity in retired) wire.Retire(identity);
            for (int index = 0; index < acknowledged; index++) wire.Control(false);
        }
        catch { fault(); throw; }
        finally
        {
            if (entered) writer.Release();
            End();
        }
    }

    private void Begin()
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(closed, this);
            if (active++ == 0) drained = new(TaskCreationOptions.RunContinuationsAsynchronously);
        }
    }

    private void End()
    {
        lock (gate) if (--active == 0) drained.TrySetResult();
    }

    protected override void Dispose(bool disposing)
    {
        lock (gate) closed = true;
        if (disposing) inner.Dispose();
        wire.Close();
        base.Dispose(disposing);
    }

    private static TaskCompletionSource Completed()
    {
        var result = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        result.SetResult();
        return result;
    }
}
