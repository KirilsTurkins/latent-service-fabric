using System.Buffers.Binary;
using System.Collections.Concurrent;
using System.Net;
using Google.Protobuf;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.Extensions.Logging;
using WireInvocation = global::Latent.Invocation.V1;

namespace Latent.Sdk.Transport.Tests;

internal sealed class Peer : IAsyncDisposable
{
    private readonly WebApplication application;
    internal readonly ConcurrentDictionary<string, int> Requests = new();
    internal readonly ConcurrentDictionary<string, bool> Connections = new();
    internal string Endpoint => application.Urls.Single();

    private Peer(WebApplication application) { this.application = application; }

    internal static async Task<Peer> Start(Func<HttpContext, Task> handler, uint streams = 8)
    {
        WebApplicationBuilder builder = WebApplication.CreateSlimBuilder();
        builder.Logging.ClearProviders();
        builder.Logging.AddConsole().SetMinimumLevel(LogLevel.Error);
        builder.WebHost.ConfigureKestrel(options =>
        {
            options.Listen(IPAddress.Loopback, 0, listener => listener.Protocols = HttpProtocols.Http2);
            options.Limits.Http2.MaxStreamsPerConnection = checked((int)streams);
            options.Limits.MaxRequestBodySize = 4 * 1024 * 1024 + 5;
            options.Limits.MaxResponseBufferSize = 64 * 1024;
        });
        WebApplication application = builder.Build();
        var peer = new Peer(application);
        application.Run(async context =>
        {
            string path = context.Request.Path.Value!;
            peer.Requests.AddOrUpdate(path, 1, (_, count) => count + 1);
            peer.Connections.TryAdd(context.Connection.Id, true);
            if (context.Request.Headers.Authorization != "Bearer " + Program.Token || context.Request.Protocol != "HTTP/2")
                throw new InvalidOperationException("explicit test authentication or HTTP/2 missing");
            try { await handler(context); }
            catch (OperationCanceledException) when (context.RequestAborted.IsCancellationRequested) { }
        });
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        await application.StartAsync(deadline.Token);
        return peer;
    }

    internal static async Task<Message> Read<Message>(HttpContext context) where Message : IMessage, new()
    {
        byte[] prefix = new byte[5];
        await context.Request.Body.ReadExactlyAsync(prefix, context.RequestAborted);
        uint length = BinaryPrimitives.ReadUInt32BigEndian(prefix.AsSpan(1));
        if (prefix[0] != 0 || length > 4 * 1024 * 1024) throw new InvalidOperationException("invalid controlled request frame");
        byte[] payload = new byte[(int)length];
        await context.Request.Body.ReadExactlyAsync(payload, context.RequestAborted);
        var message = new Message();
        message.MergeFrom(payload);
        return message;
    }

    internal static async Task Reply(HttpContext context, IMessage message, string status = "0")
    {
        // A normal unary peer consumes the bounded request before completing
        // its response. Otherwise Kestrel may reset the unread request stream,
        // correctly triggering the client's no-replay connection retirement.
        await context.Request.Body.CopyToAsync(Stream.Null, context.RequestAborted);
        context.Response.ContentType = "application/grpc+proto";
        context.Response.DeclareTrailer("grpc-status");
        await context.Response.Body.WriteAsync(Packet(message.ToByteArray()), context.RequestAborted);
        context.Response.AppendTrailer("grpc-status", status);
    }

    internal static async Task Error(HttpContext context, string status)
    {
        await context.Request.Body.CopyToAsync(Stream.Null, context.RequestAborted);
        context.Response.ContentType = "application/grpc+proto";
        context.Response.Headers["grpc-status"] = status;
    }

    internal static byte[] Packet(byte[] payload)
    {
        byte[] packet = new byte[payload.Length + 5];
        BinaryPrimitives.WriteUInt32BigEndian(packet.AsSpan(1), (uint)payload.Length);
        payload.CopyTo(packet, 5);
        return packet;
    }

    internal static WireInvocation.InvokeResponse Success(string identity = "activation-a") => new()
    {
        ActivationId = identity, RevisionId = "revision-a", ReleaseDigest = "sha256:" + new string('a', 64),
        PublicationId = "publication:sha256:" + new string('b', 64), RouteGeneration = ulong.MaxValue,
        Consumption = new() { CpuFuel = ulong.MaxValue },
        Success = new() { Payload = ByteString.CopyFrom([0, 255, 1, 128]), MediaType = "application/octet-stream", CommittedStateVersion = "" }
    };

    public async ValueTask DisposeAsync()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        await application.StopAsync(deadline.Token);
        await application.DisposeAsync();
    }
}
