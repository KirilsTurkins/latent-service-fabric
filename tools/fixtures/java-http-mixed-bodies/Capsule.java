package dev.latent.app;

import com.github.kevinsawicki.http.HttpRequest;
import dev.latent.generated.Bindings;
import dev.latent.guest.client.HttpFailure;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Ordinary single-use body ownership under the explicitly selected phase profile. */
public final class Capsule implements Bindings.Exports {
    private static int calls;
    private static volatile int prefixReady;
    private static volatile int completed;
    private static volatile Throwable childFailure;

    private static final class BorrowedOutput extends OutputStream {
        final byte[] bytes = new byte[8193];
        int used;
        boolean closed;
        public void write(int value) throws IOException {
            if (closed || used == bytes.length) throw new IOException("caller-output-not-writable");
            bytes[used++] = (byte)value;
            if (used >= 5) prefixReady = 1;
        }
        public void write(byte[] value, int offset, int length) throws IOException {
            if (value == null) throw new NullPointerException();
            if (offset < 0 || length < 0 || offset > value.length - length)
                throw new IndexOutOfBoundsException();
            for (int index = 0; index < length; index++) write(value[offset + index]);
        }
        public void close() { closed = true; }
    }

    private static HttpURLConnection connection(String endpoint, String path) throws IOException {
        HttpURLConnection value = (HttpURLConnection)new URL(endpoint + path).openConnection();
        value.setInstanceFollowRedirects(false);
        return value;
    }

    private static int readPrefix(InputStream input, byte[] prefix) throws IOException {
        int used = 0;
        while (used < prefix.length) {
            int count = input.read(prefix, used, prefix.length - used);
            if (count <= 0) throw new IOException("missing-public-prefix");
            used += count;
        }
        return used;
    }

    private static String code(Throwable value) {
        for (int depth = 0; value != null && depth < 8; depth++, value = value.getCause())
            if (value instanceof HttpFailure) return ((HttpFailure)value).code();
        throw new IllegalStateException("missing-typed-http-failure");
    }

    private static int get(String endpoint) {
        HttpRequest request = HttpRequest.get(endpoint + "/conformance/json");
        try { return request.code(); }
        finally { request.disconnect(); }
    }

    private static void exactBody(BorrowedOutput output, boolean partial) {
        String body = new String(output.bytes, 0, output.used, StandardCharsets.UTF_8);
        if (partial) {
            if (output.used != 4109 || !body.startsWith("first-second-"))
                throw new IllegalStateException("wrong-streamed-prefix-or-length");
            for (int index = 13; index < body.length(); index++)
                if (body.charAt(index) != 'x') throw new IllegalStateException("wrong-streamed-suffix");
        } else if (!body.equals("{\"empty\":\"\",\"id\":7,\"items\":[\"first\",\"λ\"],\"name\":\"café\"}")) {
            throw new IllegalStateException("wrong-borrowed-response-bytes");
        }
    }

    private static String borrowed(String endpoint, boolean pending, boolean cancellation) throws Exception {
        BorrowedOutput output = new BorrowedOutput();
        HttpRequest request = HttpRequest.get(endpoint + (pending ? "/conformance/body/partial" : "/conformance/json"));
        try {
            if (!pending) {
                if (request.receive(output) != request) throw new IllegalStateException("receive-result-identity");
            } else {
                Thread child = new Thread(() -> {
                    try { request.receive(output); }
                    catch (Throwable error) { childFailure = error; }
                    finally { completed = 1; }
                });
                child.start();
                while (prefixReady == 0 && completed == 0) Thread.yield();
                if (prefixReady != 1 || completed != 0) throw new IllegalStateException("body-not-pending");
                int sibling = get(endpoint);
                if (sibling != 200) throw new IllegalStateException("blocked-body-sibling");
                child.join();
                if (cancellation) throw new IllegalStateException("cancelled-body-returned");
                if (childFailure != null) throw new IllegalStateException("streamed-body-failed", childFailure);
            }
            exactBody(output, pending);
            int received = output.used;
            if (output.closed) throw new IllegalStateException("borrowed-output-was-closed");
            output.write('!');
            if (output.used != received + 1 || output.bytes[received] != '!')
                throw new IllegalStateException("caller-output-no-longer-owned");
            return ":borrowed:" + received + ":" + pending + ":false";
        } finally { request.disconnect(); }
    }

    // Keep independently suspended cases in separate ordinary Java methods.
    // Their original operations, ownership assertions and caller finally remain.
    private static String requestBoundary(HttpURLConnection connection, Long which, int invocation) throws Exception {
        connection.setDoOutput(true);
        connection.setFixedLengthStreamingMode(which == 5 ? 4096 : 4097);
        try {
            byte[] bytes = new byte[4096];
            for (int index = 0; index < bytes.length; index++) bytes[index] = 'x';
            try (OutputStream output = connection.getOutputStream()) { output.write(bytes); }
            if (which == 6) throw new IllegalStateException("over-limit-request-accepted");
            JSONObject response;
            try (InputStream input = connection.getInputStream()) {
                response = new JSONObject(new String(input.readAllBytes(), StandardCharsets.UTF_8));
            }
            StringBuilder expected = new StringBuilder();
            for (int index = 0; index < 1365; index++) expected.append("eHh4");
            expected.append("eA==");
            if (!response.getString("bodyBase64").equals(expected.toString())
                    || !response.getString("method").equals("POST")
                    || !response.getBoolean("contentLengthPresent"))
                throw new IllegalStateException("request-boundary-body-changed");
            return invocation + ":request-boundary:4096:200";
        } catch (IOException error) {
            if (which != 6 || !code(error).equals("invalid-request")) throw error;
            return invocation + ":request-limit:invalid-request";
        }
    }

    private static String responseBoundary(HttpURLConnection connection, int invocation) throws Exception {
        try (InputStream input = connection.getInputStream()) {
            int length = 0;
            for (int value; (value = input.read()) != -1;) {
                if (value != 'x') throw new IllegalStateException("response-boundary-bytes-changed");
                length++;
            }
            if (length != 8192) throw new IllegalStateException("response-boundary-length");
            return invocation + ":response-boundary:8192:200";
        }
    }

    private static String responseLimit(HttpURLConnection connection, int invocation) throws Exception {
        try {
            try (InputStream input = connection.getInputStream()) { input.readAllBytes(); }
            throw new IllegalStateException("over-limit-response-accepted");
        } catch (IOException error) {
            if (!code(error).equals("response-too-large")) throw error;
            return invocation + ":response-limit:response-too-large";
        }
    }

    private static String responseViews(HttpURLConnection connection, Long which, int invocation) throws Exception {
        try (InputStream input = connection.getInputStream()) {
            byte[] prefix = new byte[5];
            readPrefix(input, prefix);
            if (which == 3) {
                if (!new String(prefix, StandardCharsets.UTF_8).equals("short"))
                    throw new IllegalStateException("truncation-prefix-lost");
                try { input.read(); }
                catch (IOException error) {
                    if (!code(error).equals("unexpected-eof")) throw error;
                    return invocation + ":partial-error:short:unexpected-eof";
                }
                throw new IllegalStateException("truncation-became-normal-eof");
            }
            InputStream borrowed = connection.getInputStream();
            if (borrowed != input) throw new IllegalStateException("response-stream-was-replayed");
            int length = prefix.length;
            for (int value; (value = borrowed.read()) != -1;) length++;
            if (length != 57 || input.read() != -1 || connection.getInputStream().read() != -1)
                throw new IllegalStateException("consumed-response-restarted");
            borrowed.close();input.close();
            try { input.read(); }
            catch (IOException closed) { return invocation + ":views:57:same:consumed:closed"; }
            throw new IllegalStateException("closed-body-still-readable");
        }
    }

    public String run(Long which, String endpoint) {
        if (which == null || which < 0 || which > 9) throw new IllegalArgumentException("unknown-body-case");
        int invocation = ++calls;
        try {
            if (which == 1 || which == 2 || which == 7)
                return invocation + borrowed(endpoint, which != 1, which == 7);
            if (which == 8) return invocation + ":fresh:" + get(endpoint) + ":" + prefixReady + ":" + completed;
            String path = which == 3 ? "/conformance/body/truncated"
                : which == 4 ? "/conformance/body/oversized"
                : which == 9 ? "/conformance/body/boundary"
                : which == 5 || which == 6 ? "/conformance/echo" : "/conformance/json";
            HttpURLConnection connection = connection(endpoint, path);
            try {
                if (which == 5 || which == 6) return requestBoundary(connection, which, invocation);
                if (which == 9) return responseBoundary(connection, invocation);
                if (which == 4) return responseLimit(connection, invocation);
                return responseViews(connection, which, invocation);
            } finally { connection.disconnect(); }
        } catch (Exception error) {
            throw new IllegalStateException("ordinary-java-mixed-body-failed", error);
        }
    }
}
