package dev.latent.guest.server.http;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** Invocation-local byte views. Sealing is not network delivery or receipt. */
public final class HttpExchange implements AutoCloseable {
    public static final int MAX_REQUEST = 65536;
    public static final int MAX_RESPONSE = 262144;
    private final String method;
    private final URI uri;
    private final Headers requestHeaders;
    private final Headers responseHeaders = new Headers();
    private final byte[] requestBytes;
    private final InputStream requestBody;
    private final Body responseBody = new Body();
    private HttpContext context;
    private int status = -1;
    private long expectedLength = -1;
    private Long representationLength;
    private boolean headersSent;
    private boolean closed;
    private boolean failed;
    private boolean retired;

    public HttpExchange(String method, String path, String query, Headers headers, byte[] body) {
        if (body == null || body.length > MAX_REQUEST) throw new IllegalArgumentException("request body limit");
        if (!List.of("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS").contains(method)) {
            throw new IllegalArgumentException("unsupported request method");
        }
        this.method = method;
        this.uri = URI.create(path + (query == null ? "" : "?" + query));
        this.requestHeaders = headers;
        headers.freeze();
        requestBytes = body.clone();
        requestBody = new ByteArrayInputStream(requestBytes) {
            private boolean inputClosed;
            private void valid() {
                if (closed || inputClosed) throw new IllegalStateException("request stream is closed");
            }
            @Override public synchronized int read() { valid(); return super.read(); }
            @Override public synchronized int read(byte[] value, int offset, int length) { valid(); return super.read(value, offset, length); }
            @Override public synchronized long skip(long count) { valid(); return super.skip(count); }
            @Override public synchronized int available() { valid(); return super.available(); }
            @Override public synchronized byte[] readAllBytes() { valid(); return super.readAllBytes(); }
            @Override public synchronized byte[] readNBytes(int length) throws IOException { valid(); return super.readNBytes(length); }
            @Override public synchronized int readNBytes(byte[] value, int offset, int length) { valid(); return super.readNBytes(value, offset, length); }
            @Override public synchronized long transferTo(OutputStream target) throws IOException { valid(); return super.transferTo(target); }
            @Override public synchronized void mark(int limit) { valid(); super.mark(limit); }
            @Override public synchronized void reset() { valid(); super.reset(); }
            @Override public void close() { inputClosed = true; }
        };
    }

    private void open() {
        if (closed || failed) throw new IllegalStateException("exchange is closed or failed");
    }
    public String getRequestMethod() { open(); return method; }
    public URI getRequestURI() { open(); return uri; }
    public Headers getRequestHeaders() { open(); return requestHeaders; }
    public Headers getResponseHeaders() { open(); return responseHeaders; }
    public InputStream getRequestBody() { open(); return requestBody; }
    public OutputStream getResponseBody() { open(); return responseBody; }
    public HttpContext getHttpContext() { open(); return context; }
    public int getResponseCode() { return status; }
    void context(HttpContext selected) { context = selected; }

    public void sendResponseHeaders(int code, long length) throws IOException {
        open();
        if (headersSent) fail("response headers already sent");
        if (code < 200 || code > 599 || length < -1 || length == 0 || length > MAX_RESPONSE) {
            fail("unsupported status or response length");
        }
        boolean noBody = method.equals("HEAD") || code == 204 || code == 205 || code == 304;
        if ((code == 204 || code == 205) && length != -1) fail("no-body status requires explicit no-body length");
        validateResponseHeaders();
        responseHeaders.freeze();
        status = code;
        representationLength = (method.equals("HEAD") || code == 304) && length > 0 ? length : null;
        expectedLength = noBody || length == -1 ? 0 : length;
        headersSent = true;
    }

    private void validateResponseHeaders() throws IOException {
        responseHeaders.check();
        for (Map.Entry<String, List<String>> field : responseHeaders.entrySet()) {
            String name = field.getKey();
            if (name.equals("content-type")) {
                if (field.getValue().size() != 1 || !field.getValue().get(0).matches("[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+")) {
                    fail("unsupported media type");
                }
            } else if (name.equals("host") || name.equals("content-length") || name.equals("server")
                    || name.equals("date") || name.equals("via") || name.equals("alt-svc")
                    || name.equals("authorization") || name.equals("proxy-authorization")
                    || name.equals("connection") || name.equals("transfer-encoding") || name.equals("upgrade")
                    || name.equals("keep-alive") || name.equals("proxy-connection") || name.equals("te")
                    || name.equals("trailer") || name.equals("forwarded") || name.equals("traceparent")
                    || name.equals("tracestate") || name.equals("baggage") || name.startsWith("x-forwarded-")
                    || name.startsWith("x-lsf-")) {
                fail("reserved response header");
            }
        }
    }

    private void fail(String code) throws IOException {
        failed = true;
        throw new IOException(code);
    }

    private final class Body extends OutputStream {
        private final class OwnedBytes extends ByteArrayOutputStream {
            void retire() { Arrays.fill(buf, (byte) 0); reset(); }
        }
        private final OwnedBytes bytes = new OwnedBytes();
        private boolean sealed;
        private void writable(int length) throws IOException {
            if (closed || failed || sealed || !headersSent) fail("response body unavailable");
            if (length < 0 || length > expectedLength - bytes.size()) fail("response body exceeds declared length");
        }
        @Override public void write(int value) throws IOException {
            writable(1);
            bytes.write(value);
        }
        @Override public void write(byte[] value, int offset, int length) throws IOException {
            if (value == null) throw new NullPointerException();
            if (offset < 0 || length < 0 || offset > value.length - length) throw new IndexOutOfBoundsException();
            writable(length);
            bytes.write(value, offset, length);
        }
        @Override public void flush() throws IOException {
            // True streaming visibility has no mapping in buffered-v1.
            fail("streaming flush is unsupported by buffered-v1");
        }
        @Override public void close() throws IOException {
            if (sealed && !failed) return;
            if (!headersSent || failed || bytes.size() != expectedLength) fail("response body shorter than declared length");
            sealed = true;
        }
        byte[] result() throws IOException {
            if (!sealed) close();
            if (failed) fail("failed response cannot be returned");
            return bytes.toByteArray();
        }
        void retire() { sealed = true; bytes.retire(); }
    }

    public byte[] sealedBody() throws IOException {
        if (!headersSent || failed || retired) fail("response is not valid");
        return responseBody.result();
    }
    public Long representationLength() { return representationLength; }
    public String mediaType() { return responseHeaders.getFirst("content-type"); }
    public Headers sealedHeaders() { return responseHeaders; }
    @Override public void close() {
        if (closed) return;
        try { responseBody.close(); }
        catch (IOException failure) { failed = true; throw new IllegalStateException("invalid response at close", failure); }
        finally { closed = true; Arrays.fill(requestBytes, (byte) 0); }
    }
    public void retire() {
        closed = true;
        retired = true;
        Arrays.fill(requestBytes, (byte) 0);
        responseBody.retire();
        context = null;
    }
}
