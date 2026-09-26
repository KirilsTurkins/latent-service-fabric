using Google.Protobuf;
using Grpc.Core;

namespace Latent.Sdk.Transport;

internal sealed class UnaryInvoker(BoundedClient owner, CallState state, CancellationToken token) : CallInvoker
{
    internal CancellationToken Token => token;

    public override AsyncUnaryCall<TResponse> AsyncUnaryCall<TRequest, TResponse>(Method<TRequest, TResponse> method, string? host, CallOptions options, TRequest request)
    {
        Task<TResponse> result = owner.UnaryAsync<TResponse>(method.FullName, (IMessage)request, state, token);
        return new(result, Task.FromResult(new Metadata()), () => new Status((StatusCode)(state.GrpcStatus ?? 2), "bounded unary call"),
            () => new Metadata(), () => { });
    }

    public override TResponse BlockingUnaryCall<TRequest, TResponse>(Method<TRequest, TResponse> method, string? host, CallOptions options, TRequest request) => throw new NotSupportedException();
    public override AsyncClientStreamingCall<TRequest, TResponse> AsyncClientStreamingCall<TRequest, TResponse>(Method<TRequest, TResponse> method, string? host, CallOptions options) => throw new NotSupportedException();
    public override AsyncDuplexStreamingCall<TRequest, TResponse> AsyncDuplexStreamingCall<TRequest, TResponse>(Method<TRequest, TResponse> method, string? host, CallOptions options) => throw new NotSupportedException();
    public override AsyncServerStreamingCall<TResponse> AsyncServerStreamingCall<TRequest, TResponse>(Method<TRequest, TResponse> method, string? host, CallOptions options, TRequest request) => throw new NotSupportedException();
}
