package dev.latent.sdk.transport;

import io.grpc.Metadata;
import io.grpc.MethodDescriptor;
import io.grpc.Server;
import io.grpc.ServerCall;
import io.grpc.ServerCallHandler;
import io.grpc.ServerServiceDefinition;
import io.grpc.Status;
import io.grpc.netty.shaded.io.grpc.netty.NettyServerBuilder;
import io.grpc.netty.shaded.io.netty.channel.nio.NioEventLoopGroup;
import io.grpc.netty.shaded.io.netty.channel.socket.nio.NioServerSocketChannel;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;

@SuppressWarnings("deprecation")
final class RawPeer implements AutoCloseable {
    record Reply(byte[] body, Status status, Metadata headers, Metadata trailers) { }
    private final NioEventLoopGroup accept = new NioEventLoopGroup(1);
    private final NioEventLoopGroup work = new NioEventLoopGroup(1);
    private final Server server;

    <Request, Response> RawPeer(MethodDescriptor<Request, Response> method, Function<Request, Reply> reply) throws Exception {
        var raw = MethodDescriptor.<Request, byte[]>newBuilder().setFullMethodName(method.getFullMethodName())
                .setType(MethodDescriptor.MethodType.UNARY).setRequestMarshaller(method.getRequestMarshaller())
                .setResponseMarshaller(new MethodDescriptor.Marshaller<byte[]>() {
                    @Override public InputStream stream(byte[] value) { return new ByteArrayInputStream(value); }
                    @Override public byte[] parse(InputStream value) { throw new UnsupportedOperationException(); }
                }).build();
        var service = ServerServiceDefinition.builder(method.getServiceName()).addMethod(raw, new ServerCallHandler<Request, byte[]>() {
            @Override public ServerCall.Listener<Request> startCall(ServerCall<Request, byte[]> call, Metadata requestHeaders) {
                call.request(1);
                return new ServerCall.Listener<>() {
                    private Request request;
                    @Override public void onMessage(Request value) { request = value; }
                    @Override public void onHalfClose() {
                        Reply value = reply.apply(request);
                        call.sendHeaders(value.headers());
                        if (value.body() != null) call.sendMessage(value.body());
                        call.close(value.status(), value.trailers());
                    }
                };
            }
        }).build();
        server = NettyServerBuilder.forAddress(new InetSocketAddress("127.0.0.1", 0)).bossEventLoopGroup(accept).workerEventLoopGroup(work)
                .channelType(NioServerSocketChannel.class).directExecutor().addService(service).build().start();
    }

    String endpoint() { return "http://127.0.0.1:" + server.getPort(); }
    RpcClient client() { return new RpcClient(ClientConfig.loopback(endpoint(), "tenant-a", "test-only-java-token")); }

    @Override public void close() throws Exception {
        server.shutdownNow();
        if (!server.awaitTermination(3, TimeUnit.SECONDS)) throw new AssertionError("raw peer not retired");
        accept.shutdownGracefully(0, 1, TimeUnit.SECONDS).sync();
        work.shutdownGracefully(0, 1, TimeUnit.SECONDS).sync();
    }
}
