package dev.latent.sdk.transport;

import io.grpc.netty.shaded.io.netty.buffer.ByteBuf;
import io.grpc.netty.shaded.io.netty.buffer.Unpooled;
import io.grpc.netty.shaded.io.netty.handler.codec.http2.DefaultHttp2Headers;
import io.grpc.netty.shaded.io.netty.handler.codec.http2.DefaultHttp2HeadersDecoder;
import io.grpc.netty.shaded.io.netty.handler.codec.http2.DefaultHttp2HeadersEncoder;
import io.grpc.netty.shaded.io.netty.handler.codec.http2.Http2Headers;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import latent.invocation.v1.Invocation;

final class FramedPeer implements AutoCloseable {
    enum Fault { REFUSED_STREAM, GOAWAY, UNAVAILABLE }
    final AtomicInteger requests = new AtomicInteger();
    final AtomicInteger probes = new AtomicInteger();
    final AtomicInteger connections = new AtomicInteger();
    final AtomicInteger openSockets = new AtomicInteger();
    private final AtomicReference<Throwable> failure = new AtomicReference<>();
    private final ServerSocket listener = new ServerSocket();
    private final Thread worker;
    private final Fault fault;
    private volatile Socket active;
    private volatile boolean closed;

    FramedPeer(Fault fault) throws Exception {
        this.fault = fault;
        listener.bind(new InetSocketAddress("127.0.0.1", 0), 4);
        worker = new Thread(this::run, "java-framed-peer");
        worker.start();
    }

    String endpoint() { return "http://127.0.0.1:" + listener.getLocalPort(); }

    void checkHealthy() {
        if (failure.get() != null) throw new AssertionError("controlled HTTP/2 peer failed", failure.get());
    }

    private void run() {
        try {
            while (!closed) {
                Socket socket = listener.accept();
                active = socket;
                openSockets.incrementAndGet();
                try (socket) {
                    TransportTest.check(connections.incrementAndGet() <= 8, "finite peer connection inventory");
                    socket.setSoTimeout(3000);
                    serve(socket);
                } finally {
                    if (socket.isClosed()) {
                        active = null;
                        openSockets.decrementAndGet();
                    }
                }
            }
        } catch (Throwable problem) {
            if (!closed) failure.compareAndSet(null, problem);
        }
    }

    private void serve(Socket socket) throws Exception {
        InputStream input = socket.getInputStream();
        OutputStream output = socket.getOutputStream();
        TransportTest.check(new String(input.readNBytes(24), StandardCharsets.US_ASCII)
                .equals("PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"), "HTTP/2 preface");
        frame(output, 4, 0, 0, new byte[0]);
        var decoder = new DefaultHttp2HeadersDecoder();
        var encoder = new DefaultHttp2HeadersEncoder();
        while (!closed) {
            byte[] header = input.readNBytes(9);
            if (header.length == 0) return;
            TransportTest.check(header.length == 9, "complete frame header");
            int size = (Byte.toUnsignedInt(header[0]) << 16) | (Byte.toUnsignedInt(header[1]) << 8) | Byte.toUnsignedInt(header[2]);
            TransportTest.check(size <= 16384, "bounded peer frame");
            int kind = Byte.toUnsignedInt(header[3]);
            int flags = Byte.toUnsignedInt(header[4]);
            int stream = ByteBuffer.wrap(header, 5, 4).getInt() & 0x7fffffff;
            byte[] payload = input.readNBytes(size);
            TransportTest.check(payload.length == size, "complete frame body");
            if (kind == 4 && (flags & 1) == 0) frame(output, 4, 1, 0, new byte[0]);
            if (kind == 6 && (flags & 1) == 0) frame(output, 6, 1, 0, payload);
            if (kind == 7) return;
            if (kind != 1) continue;
            TransportTest.check((flags & 4) != 0 && (flags & 40) == 0, "bounded unpadded header block");
            ByteBuf encoded = Unpooled.wrappedBuffer(payload);
            Http2Headers headers;
            try { headers = decoder.decodeHeaders(stream, encoded); }
            finally { encoded.release(); }
            String path = headers.path().toString();
            if (path.endsWith("/Invoke") || path.endsWith("/ApplyPolicy")) {
                requests.incrementAndGet();
                switch (fault) {
                    case REFUSED_STREAM -> frame(output, 3, 0, stream, ByteBuffer.allocate(4).putInt(7).array());
                    case GOAWAY -> { frame(output, 7, 0, 0, new byte[8]); return; }
                    case UNAVAILABLE -> {
                        headers(output, encoder, stream, false, new DefaultHttp2Headers().status("200").set("content-type", "application/grpc"));
                        headers(output, encoder, stream, true, new DefaultHttp2Headers().set("grpc-status", "14"));
                    }
                }
            } else {
                TransportTest.check(path.endsWith("/GetActivation"), "only explicit recovery probe is accepted");
                probes.incrementAndGet();
                byte[] status = Invocation.ActivationStatus.newBuilder().setActivationId("probe").setPhase("running").build().toByteArray();
                headers(output, encoder, stream, false, new DefaultHttp2Headers().status("200").set("content-type", "application/grpc"));
                frame(output, 0, 0, stream, ByteBuffer.allocate(status.length + 5).put((byte) 0).putInt(status.length).put(status).array());
                headers(output, encoder, stream, true, new DefaultHttp2Headers().set("grpc-status", "0"));
            }
        }
    }

    private static void headers(OutputStream output, DefaultHttp2HeadersEncoder encoder, int stream, boolean end, Http2Headers headers) throws Exception {
        ByteBuf encoded = Unpooled.buffer(128);
        try {
            encoder.encodeHeaders(stream, headers, encoded);
            byte[] payload = new byte[encoded.readableBytes()];
            encoded.readBytes(payload);
            frame(output, 1, end ? 5 : 4, stream, payload);
        } finally { encoded.release(); }
    }

    private static void frame(OutputStream output, int kind, int flags, int stream, byte[] payload) throws Exception {
        output.write(new byte[] {(byte) (payload.length >>> 16), (byte) (payload.length >>> 8), (byte) payload.length, (byte) kind, (byte) flags,
                (byte) (stream >>> 24), (byte) (stream >>> 16), (byte) (stream >>> 8), (byte) stream});
        output.write(payload);
        output.flush();
    }

    @Override public void close() throws Exception {
        closed = true;
        listener.close();
        Socket socket = active;
        if (socket != null) socket.close();
        worker.join(4000);
        TransportTest.check(!worker.isAlive() && openSockets.get() == 0, "framed peer sockets and thread reaped");
        checkHealthy();
    }
}
