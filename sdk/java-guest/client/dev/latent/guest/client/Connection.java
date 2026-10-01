package dev.latent.guest.client;

import dev.latent.generated.Bindings.*;
import dev.latent.guest.Option;
import dev.latent.guest.Unsigned64;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.UncheckedIOException;
import java.net.HttpRetryException;
import java.net.HttpURLConnection;
import java.net.ProtocolException;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;

/** Finite streaming URLConnection path sharing the original activation owners. */
public final class Connection extends HttpURLConnection {
    private static final int CHUNK_BYTES = 4096;
    private static final long BODY_BYTES = 262144;
    private static final String[] ERRORS = {"invalid-url", "invalid-request", "permission-denied",
        "request-too-large", "response-too-large", "deadline-exceeded", "cancelled", "budget-exhausted",
        "dns-failed", "tls-failed", "connection-failed", "unavailable", "uncertain", "invalid-state",
        "unexpected-eof", "unsupported-encoding"};
    private LatentHttpStreamingUpload upload;
    private ResponseInput input;
    private Output output;
    private boolean terminal;
    private IOException failure;
    private long acceptedBytes;
    private long declaredBytes = -1;
    private Map<String, List<String>> responseHeaders;

    public Connection(URL url) {
        super(Objects.requireNonNull(url));
        if (!"http".equals(url.getProtocol())) throw new IllegalArgumentException("HTTP URL required");
    }

    private static HttpFailure error(LatentHttpStreamingHttpError value) {
        int tag = value.tag();
        if (tag < 0 || tag >= ERRORS.length) throw new IllegalStateException("unknown typed HTTP outcome");
        return new HttpFailure(ERRORS[tag]);
    }

    private void usable() throws IOException {
        if (failure != null) throw failure;
        if (terminal) throw new IOException("http-connection-closed");
    }

    private IOException fail(IOException original) {
        if (failure == null) failure = original;
        // Consumption/drop does not assert physical retirement. The installed
        // provider retains each original owner/charge until its actual cleanup.
        if (upload != null) { var owned = upload; upload = null; owned.close(); }
        if (input != null) input.close();
        return failure;
    }

    @Override public void connect() throws IOException {
        usable();
        if (connected) return;
        if (url.getUserInfo() != null) throw fail(new ProtocolException("URL credentials require provider policy"));
        if (getConnectTimeout() != 0 || getReadTimeout() != 0) {
            throw fail(new ProtocolException("separate connect/read timeout phases are not qualified"));
        }
        if (ifModifiedSince != 0 || allowUserInteraction) {
            throw fail(new ProtocolException("conditional date or interactive authentication is not qualified"));
        }
        var headers = new ArrayList<LatentHttpStreamingHeader>();
        String media = null;
        int count = 0, bytes = 0;
        var seen = new HashSet<String>();
        for (var entry : getRequestProperties().entrySet()) {
            String name = entry.getKey();
            String folded = name.toLowerCase(Locale.ROOT);
            if (!seen.add(folded)) throw fail(new ProtocolException("ambiguous request field casing"));
            if (entry.getValue().size() != 1) throw fail(new ProtocolException("duplicate request field is unsupported"));
            String value = entry.getValue().get(0);
            if (name.isEmpty() || name.length() > 64 || value.length() > 4096) {
                throw fail(new HttpFailure("request-too-large"));
            }
            for (int i = 0; i < name.length(); i++) {
                char c = name.charAt(i);
                if (!(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9'
                        || "!#$%&'*+-.^_`|~".indexOf(c) >= 0)) {
                    throw fail(new ProtocolException("invalid request field name"));
                }
            }
            for (int i = 0; i < value.length(); i++) {
                char c = value.charAt(i);
                if (c > 255 || c == 127 || c < 32 && c != '\t') {
                    throw fail(new ProtocolException("invalid request field value"));
                }
            }
            if (++count > 64 || (bytes += name.length() + value.length()) > 16384) {
                throw fail(new HttpFailure("request-too-large"));
            }
            if (folded.equals("content-type")) media = value;
            else headers.add(new LatentHttpStreamingHeader(name, value));
        }
        var selected = switch (method) {
            case "GET" -> LatentHttpStreamingMethod.Get;
            case "HEAD" -> LatentHttpStreamingMethod.Head;
            case "POST" -> LatentHttpStreamingMethod.Post;
            case "PUT" -> LatentHttpStreamingMethod.Put;
            case "DELETE" -> LatentHttpStreamingMethod.Delete;
            case "OPTIONS" -> LatentHttpStreamingMethod.Options;
            default -> throw fail(new ProtocolException("unsupported standard HTTP method"));
        };
        String target = url.toExternalForm();
        int fragment = target.indexOf('#');
        if (fragment >= 0) target = target.substring(0, fragment);
        var length = declaredBytes >= 0 ? Option.some(new Unsigned64(declaredBytes))
            : !doOutput ? Option.some(new Unsigned64(0)) : Option.<Unsigned64>none();
        var opened = LatentHttpStreaming.open(new LatentHttpStreamingRequest(selected, target, headers,
            length, media == null ? Option.none() : Option.some(media), Option.none(), Option.none()));
        if (opened.isError()) throw fail(error(opened.error()));
        upload = opened.value();
        connected = true;
    }

    @Override public void setFixedLengthStreamingMode(int length) { setFixedLengthStreamingMode((long) length); }
    @Override public void setFixedLengthStreamingMode(long length) {
        if (connected) throw new IllegalStateException("already connected");
        if (length < 0 || length > BODY_BYTES) throw new IllegalArgumentException("body length outside profile");
        declaredBytes = length;
    }
    @Override public void setChunkedStreamingMode(int size) {
        throw new UnsupportedOperationException("explicit HTTP chunk framing is not qualified");
    }
    @Override public boolean usingProxy() { return false; }
    @Override public void disconnect() {
        if (terminal) return;
        terminal = true;
        if (upload != null) { var owned = upload; upload = null; owned.close(); }
        if (input != null) input.close();
    }

    @Override public OutputStream getOutputStream() throws IOException {
        usable();
        if (!doOutput) throw new ProtocolException("doOutput is false");
        if (responseCode >= 0) throw new ProtocolException("response already started");
        if (method.equals("GET") && !connected) method = "POST";
        connect();
        if (output == null) output = new Output();
        return output;
    }

    private void response() throws IOException {
        usable();
        if (responseCode >= 0) return;
        connect();
        if (declaredBytes >= 0 && acceptedBytes != declaredBytes) {
            throw fail(new ProtocolException("fixed request length was not satisfied"));
        }
        if (output != null) output.closed = true;
        var owned = upload;
        upload = null; // finish consumes on every outcome; never recreate/replay.
        var completed = LatentHttpStreaming.finish(owned);
        if (completed.isError()) throw fail(error(completed.error()));
        var result = completed.value();
        responseCode = result.status();
        var fields = new LinkedHashMap<String, List<String>>();
        for (var header : result.headers()) {
            fields.computeIfAbsent(header.name(), key -> new ArrayList<>()).add(header.value());
        }
        if (result.bodyMediaType().isSome()
                && fields.keySet().stream().noneMatch(key -> key.equalsIgnoreCase("Content-Type"))) {
            fields.put("Content-Type", new ArrayList<>(List.of(result.bodyMediaType().value())));
        }
        var frozen = new LinkedHashMap<String, List<String>>();
        fields.forEach((key, values) -> frozen.put(key, Collections.unmodifiableList(values)));
        responseHeaders = Collections.unmodifiableMap(frozen);
        input = new ResponseInput(result.body());
        if (instanceFollowRedirects && (responseCode == 301 || responseCode == 302 || responseCode == 303
                || responseCode == 307 || responseCode == 308)) {
            throw fail(new HttpRetryException("automatic redirect handling is not qualified", responseCode,
                header("Location")));
        }
    }

    private String header(String name) {
        if (name == null) throw new UnsupportedOperationException("HTTP version/reason metadata unavailable");
        for (var entry : responseHeaders.entrySet()) {
            if (entry.getKey().equalsIgnoreCase(name)) {
                var values = entry.getValue();
                return values.isEmpty() ? null : values.get(values.size() - 1);
            }
        }
        return null;
    }
    @Override public int getResponseCode() throws IOException { response(); return responseCode; }
    @Override public String getResponseMessage() throws IOException {
        response();
        throw new ProtocolException("HTTP reason phrase is not supplied by this exact profile");
    }
    @Override public Map<String, List<String>> getHeaderFields() {
        try { response(); return responseHeaders; }
        catch (IOException e) { throw new UncheckedIOException(e); }
    }
    @Override public String getHeaderField(String name) {
        try { response(); return header(name); }
        catch (IOException e) { throw new UncheckedIOException(e); }
    }
    @Override public String getHeaderField(int index) {
        throw new UnsupportedOperationException("indexed status-line/header view is not qualified");
    }
    @Override public String getHeaderFieldKey(int index) {
        throw new UnsupportedOperationException("indexed status-line/header view is not qualified");
    }
    @Override public InputStream getInputStream() throws IOException {
        if (!doInput) throw new ProtocolException("doInput is false");
        response();
        if (responseCode >= 400) {
            if (responseCode == 404 || responseCode == 410) throw new FileNotFoundException("HTTP " + responseCode);
            throw new IOException("HTTP " + responseCode + "; use getErrorStream");
        }
        return input;
    }
    @Override public InputStream getErrorStream() {
        if (failure != null || terminal || responseCode < 400) return null;
        return input;
    }

    private final class Output extends OutputStream {
        private boolean closed;
        @Override public void write(int value) throws IOException { write(new byte[]{(byte) value}, 0, 1); }
        @Override public void write(byte[] values, int offset, int length) throws IOException {
            Objects.checkFromIndexSize(offset, length, values.length);
            usable();
            if (closed || upload == null) throw new IOException("http-upload-closed");
            if (length > BODY_BYTES - acceptedBytes
                    || declaredBytes >= 0 && length > declaredBytes - acceptedBytes) {
                throw fail(new HttpFailure("request-too-large"));
            }
            while (length > 0) {
                int size = Math.min(length, CHUNK_BYTES);
                byte[] chunk = new byte[size];
                System.arraycopy(values, offset, chunk, 0, size);
                var written = LatentHttpStreaming.write(upload, chunk);
                if (written.isError()) throw fail(error(written.error()));
                acceptedBytes += size; offset += size; length -= size;
            }
        }
        @Override public void flush() throws IOException {
            usable();
            if (closed) throw new IOException("http-upload-closed");
            // No delivery acknowledgement is fabricated. write accepted owned
            // transport chunks; finish, response and remote processing differ.
        }
        @Override public void close() throws IOException {
            if (closed) return;
            closed = true;
            usable();
            if (declaredBytes >= 0 && acceptedBytes != declaredBytes) {
                throw fail(new ProtocolException("fixed request length was not satisfied"));
            }
        }
    }

    private final class ResponseInput extends InputStream {
        private final LatentHttpStreamingBody body;
        private byte[] bytes = new byte[0];
        private int position;
        private long received;
        private boolean closed, eof;
        private ResponseInput(LatentHttpStreamingBody body) { this.body = body; }
        @Override public int read() throws IOException {
            byte[] value = new byte[1];
            return read(value, 0, 1) < 0 ? -1 : value[0] & 255;
        }
        @Override public int read(byte[] values, int offset, int length) throws IOException {
            Objects.checkFromIndexSize(offset, length, values.length);
            usable();
            if (closed) throw new IOException("http-body-closed");
            if (length == 0) return 0;
            if (position == bytes.length) {
                bytes = new byte[0]; position = 0;
                if (eof) return -1;
                var next = LatentHttpStreaming.read(body, (long) CHUNK_BYTES);
                if (next.isError()) throw fail(error(next.error()));
                if (!next.value().isSome()) {
                    var trailers = LatentHttpStreaming.trailers(body);
                    if (trailers.isError()) throw fail(error(trailers.error()));
                    eof = true;
                    return -1;
                }
                try (var owned = next.value().value()) {
                    var materialized = LatentHttpStreaming.chunkBytes(owned);
                    if (materialized.isError()) throw fail(error(materialized.error()));
                    bytes = materialized.value();
                }
                if (bytes.length == 0 || bytes.length > CHUNK_BYTES) throw fail(new HttpFailure("invalid-state"));
                if (bytes.length > BODY_BYTES - received) throw fail(new HttpFailure("response-too-large"));
                received += bytes.length;
            }
            int size = Math.min(length, bytes.length - position);
            System.arraycopy(bytes, position, values, offset, size);
            position += size;
            return size;
        }
        @Override public int available() throws IOException {
            usable();
            if (closed) throw new IOException("http-body-closed");
            return bytes.length - position;
        }
        @Override public void close() {
            if (closed) return;
            closed = true;
            bytes = new byte[0];
            body.close();
        }
    }
}
