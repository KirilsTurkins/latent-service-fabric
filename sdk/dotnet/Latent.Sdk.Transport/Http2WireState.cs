using System.Buffers.Binary;

namespace Latent.Sdk.Transport;

internal sealed class Http2WireState
{
    private readonly object gate = new();
    private readonly int maximum;
    private readonly int recovery;
    private readonly Action changed;
    private readonly HashSet<int> streams = new();
    private int controls;
    private uint peerMaximum;
    private bool settingsReceived;
    private bool closed;

    internal Http2WireState(int maximum, int recovery, Action changed)
    {
        this.maximum = maximum;
        this.recovery = recovery;
        this.changed = changed;
    }

    internal (int Streams, int Maximum, bool Ready) Snapshot()
    {
        lock (gate) return (streams.Count, (int)Math.Min((uint)maximum, peerMaximum), settingsReceived);
    }

    internal void Start(int identity)
    {
        lock (gate)
        {
            if (closed || identity == 0 || (identity & 1) == 0 || streams.Count >= maximum || !streams.Add(identity))
                throw new IOException("bounded HTTP/2 stream ownership rejected");
        }
    }

    internal void Retire(int identity)
    {
        lock (gate) streams.Remove(identity);
        changed();
    }

    internal void Settings(uint? value)
    {
        lock (gate)
        {
            peerMaximum = value ?? (settingsReceived ? peerMaximum : uint.MaxValue);
            if (peerMaximum <= recovery) throw new IOException("peer cannot supply reserved recovery capacity");
            settingsReceived = true;
        }
        changed();
    }

    internal void Control(bool admitted)
    {
        lock (gate)
        {
            controls += admitted ? 1 : -1;
            if (controls > 16) throw new IOException("HTTP/2 control queue exceeds bound");
            controls = Math.Max(controls, 0);
        }
    }

    internal void Close()
    {
        lock (gate)
        {
            closed = true;
            streams.Clear();
            controls = 0;
        }
        changed();
    }
}

internal sealed class Http2FrameObserver
{
    private static readonly byte[] Preface = "PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"u8.ToArray();
    private readonly Http2WireState owner;
    private readonly bool outgoing;
    private readonly byte[] header = new byte[9];
    private readonly byte[] setting = new byte[6];
    private int prefaceOffset;
    private int headerLength;
    private int remaining;
    private int payloadOffset;
    private int identity;
    private byte kind;
    private byte flags;
    private uint? peerMaximum;

    internal Http2FrameObserver(Http2WireState owner, bool outgoing)
    {
        this.owner = owner;
        this.outgoing = outgoing;
        prefaceOffset = outgoing ? 0 : Preface.Length;
    }

    internal void Observe(ReadOnlySpan<byte> data, List<int>? retired, ref int acknowledged)
    {
        while (!data.IsEmpty)
        {
            if (prefaceOffset < Preface.Length)
            {
                int count = Math.Min(data.Length, Preface.Length - prefaceOffset);
                if (!data[..count].SequenceEqual(Preface.AsSpan(prefaceOffset, count))) throw new IOException("invalid HTTP/2 preface");
                prefaceOffset += count;
                data = data[count..];
                continue;
            }
            if (headerLength < header.Length)
            {
                int count = Math.Min(data.Length, header.Length - headerLength);
                data[..count].CopyTo(header.AsSpan(headerLength));
                data = data[count..];
                headerLength += count;
                if (headerLength != header.Length) continue;
                remaining = (header[0] << 16) | (header[1] << 8) | header[2];
                kind = header[3];
                flags = header[4];
                identity = BinaryPrimitives.ReadInt32BigEndian(header.AsSpan(5)) & int.MaxValue;
                payloadOffset = 0;
                peerMaximum = null;
                if (remaining > 16384 || (kind == 4 && (remaining > 96 || remaining % 6 != 0)))
                    throw new IOException("HTTP/2 frame exceeds supported bound");
                if (!outgoing && kind is 3 or 5 or 7)
                    throw new IOException("remote stream reset, push or shutdown; automatic replay is forbidden");
                if (outgoing && kind == 1) owner.Start(identity);
                if (!outgoing && kind is 4 or 6 && (flags & 1) == 0) owner.Control(true);
            }
            int consumed = Math.Min(remaining, data.Length);
            if (!outgoing && kind == 4 && (flags & 1) == 0)
            {
                for (int offset = 0; offset < consumed; offset++)
                {
                    setting[payloadOffset % 6] = data[offset];
                    payloadOffset++;
                    if (payloadOffset % 6 == 0 && BinaryPrimitives.ReadUInt16BigEndian(setting) == 3)
                        peerMaximum = BinaryPrimitives.ReadUInt32BigEndian(setting.AsSpan(2));
                }
            }
            remaining -= consumed;
            data = data[consumed..];
            if (remaining != 0) continue;
            if (!outgoing && kind == 4 && (flags & 1) == 0) owner.Settings(peerMaximum);
            if (!outgoing && kind is 0 or 1 && (flags & 1) != 0) owner.Retire(identity);
            if (outgoing && kind == 3) retired!.Add(identity);
            if (outgoing && kind is 4 or 6 && (flags & 1) != 0) acknowledged++;
            headerLength = 0;
        }
    }
}
