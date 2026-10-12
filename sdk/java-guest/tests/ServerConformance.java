package dev.latent.guest.server.http;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;

/** Native kernel conformance, deliberately separate from signed ingress evidence. */
public final class ServerConformance {
    private static int cases;
    private interface Checked { void run() throws Exception; }
    private static void check(boolean condition) {
        if (!condition) throw new AssertionError("server conformance assertion");
    }
    private static void rejects(Checked operation) throws Exception {
        try { operation.run(); }
        catch (IllegalArgumentException | IllegalStateException | UnsupportedOperationException | java.io.IOException expected) { return; }
        throw new AssertionError("unsupported or failed operation succeeded");
    }
    private static HttpExchange exchange(String method, String path) {
        return new HttpExchange(method, path, "name=one+two&name=three", new Headers(), new byte[]{0, (byte)255, 7});
    }
    private static void response(HttpExchange exchange, int status, byte[] bytes) throws java.io.IOException {
        exchange.sendResponseHeaders(status, bytes.length == 0 ? -1 : bytes.length);
        try (OutputStream body = exchange.getResponseBody()) { body.write(bytes); }
    }
    private static void run(String name, Checked operation) throws Exception {
        operation.run();
        cases++;
        System.out.println("observed " + name);
    }
    public static void main(String[] arguments) throws Exception {
        run("literal-longest-prefix-case-query-trailing", () -> {
            ServerSession.begin();
            try {
                HttpServer server = HttpServer.create(new InetSocketAddress(8080), 0);
                server.createContext("/hey", e -> response(e, 200, "root".getBytes(StandardCharsets.US_ASCII)));
                server.createContext("/hey/", e -> response(e, 201, "child".getBytes(StandardCharsets.US_ASCII)));
                server.start();
                ServerSession.verify("wildcard", 8080, 0, new String[]{"/hey", "/hey/"});
                for (String path : List.of("/hey", "/heyday", "/hey/", "/hey/child", "/HEY", "/other")) {
                    HttpExchange e = exchange("POST", path);
                    ServerSession.dispatch(e);
                    int expected = path.startsWith("/hey/") ? 201 : path.startsWith("/hey") ? 200 : 404;
                    check(e.getResponseCode() == expected);
                    check(Arrays.equals(e.sealedBody(), expected == 404 ? new byte[0] : (expected == 201 ? "child" : "root").getBytes(StandardCharsets.US_ASCII)));
                    e.retire();
                }
            } finally { ServerSession.retire(); }
        });
        run("fresh-session-registration-and-captured-plan", () -> {
            for (int count = 0; count < 2; count++) {
                ServerSession.begin();
                HttpServer server = HttpServer.create(new InetSocketAddress(8080), 3);
                HttpContext context = server.createContext("/hey");
                context.setHandler(e -> response(e, 404, new byte[0]));
                server.setExecutor(null);
                server.start();
                ServerSession.verify("wildcard", 8080, 3, new String[]{"/hey"});
                rejects(() -> ServerSession.verify("loopback", 8080, 3, new String[]{"/hey"}));
                rejects(() -> ServerSession.verify("wildcard", 8080, 3, new String[]{"/other"}));
                ServerSession.retire();
                rejects(() -> server.createContext("/late", e -> {}));
            }
        });
        run("duplicate-start-live-context-and-real-unsupported-members", () -> {
            ServerSession.begin();
            try {
                HttpServer server = HttpServer.create(new InetSocketAddress(8080), 0);
                rejects(() -> server.start());
                server.createContext("/hey", e -> {});
                rejects(() -> server.createContext("/hey", e -> {}));
                rejects(() -> server.createContext("/a%2Fb", e -> {}));
                rejects(() -> server.setExecutor(Runnable::run));
                rejects(server::getAddress);
                server.start();
                rejects(server::start);
                rejects(() -> server.createContext("/late", e -> {}));
                rejects(() -> server.stop(0));
                rejects(server::getExecutor);
            } finally { ServerSession.retire(); }
        });
        run("raw-request-opaque-fields-and-query", () -> {
            Headers fields = new Headers();
            fields.add("Cookie", "one=1"); fields.add("cookie", "two=2"); fields.add("x-bytes", "\u00ff");
            HttpExchange e = new HttpExchange("POST", "/hey", "q=a%2Fb+z&q=", fields, new byte[]{0, (byte)255});
            check(e.getRequestURI().getRawPath().equals("/hey"));
            check(e.getRequestURI().getRawQuery().equals("q=a%2Fb+z&q="));
            check(fields.get("COOKIE").equals(List.of("one=1", "two=2")));
            check(Arrays.equals(e.getRequestBody().readAllBytes(), new byte[]{0, (byte)255}));
            rejects(() -> fields.set("cookie", "changed"));
            e.retire();
        });
        run("header-syntax-allocation-and-sealing", () -> {
            Headers headers = new Headers();
            for (String value : List.of(" leading", "trailing ", "cr\r", "lf\n", "tab\t", "\u0100")) rejects(() -> headers.add("safe", value));
            rejects(() -> headers.add("bad name", "safe"));
            for (int count = 0; count < 64; count++) headers.add("x", "a");
            rejects(() -> headers.add("x", "a"));
            check(headers.get("x").size() == 64);
            headers.freeze(); rejects(() -> headers.clear());
        });
        run("positive-response-length-and-second-headers", () -> {
            HttpExchange e = exchange("POST", "/hey");
            e.sendResponseHeaders(200, 3); e.getResponseBody().write(new byte[]{0, (byte)255, 7});
            check(Arrays.equals(e.sealedBody(), new byte[]{0, (byte)255, 7}));
            rejects(() -> e.sendResponseHeaders(200, 3)); rejects(e::sealedBody); e.retire();
        });
        run("overwrite-is-terminal", () -> {
            HttpExchange e = exchange("POST", "/hey"); e.sendResponseHeaders(200, 1);
            rejects(() -> e.getResponseBody().write(new byte[2])); rejects(e::sealedBody); e.retire();
        });
        run("underwrite-is-terminal", () -> {
            HttpExchange e = exchange("POST", "/hey"); e.sendResponseHeaders(200, 2); e.getResponseBody().write(1);
            rejects(() -> e.getResponseBody().close()); rejects(e::sealedBody); e.retire();
        });
        run("write-before-headers-is-terminal", () -> {
            HttpExchange e = exchange("POST", "/hey"); rejects(() -> e.getResponseBody().write(1));
            rejects(() -> e.sendResponseHeaders(200, 1)); rejects(e::sealedBody); e.retire();
        });
        run("chunked-and-streaming-flush-rejected", () -> {
            HttpExchange zero = exchange("POST", "/hey"); rejects(() -> zero.sendResponseHeaders(200, 0)); zero.retire();
            HttpExchange e = exchange("POST", "/hey"); e.sendResponseHeaders(200, 1);
            rejects(() -> e.getResponseBody().flush()); rejects(e::sealedBody); e.retire();
        });
        run("head-and-no-body-status-semantics", () -> {
            HttpExchange head = exchange("HEAD", "/hey"); head.sendResponseHeaders(200, 4); head.getResponseBody().close();
            check(head.representationLength() == 4 && head.sealedBody().length == 0); head.retire();
            for (int status : List.of(204, 205, 304)) {
                HttpExchange e = exchange("POST", "/hey"); e.sendResponseHeaders(status, -1); e.close();
                check(e.sealedBody().length == 0); e.retire();
            }
        });
        run("repeated-response-fields-and-media-type", () -> {
            HttpExchange e = exchange("POST", "/hey");
            e.getResponseHeaders().add("Set-Cookie", "one=1"); e.getResponseHeaders().add("set-cookie", "two=2");
            e.getResponseHeaders().set("Content-Type", "application/octet-stream");
            response(e, 400, new byte[]{0});
            check(e.sealedHeaders().get("set-cookie").equals(List.of("one=1", "two=2")));
            check(e.mediaType().equals("application/octet-stream"));
            rejects(() -> e.sealedHeaders().set("late", "value")); e.retire();
        });
        run("reserved-fields-never-return-success", () -> {
            for (String name : List.of("content-length", "server", "date", "authorization", "x-lsf-principal", "connection", "keep-alive", "te", "traceparent")) {
                HttpExchange e = exchange("POST", "/hey"); e.getResponseHeaders().set(name, "forged");
                rejects(() -> e.sendResponseHeaders(200, -1)); rejects(e::sealedBody); e.retire();
            }
        });
        run("every-closed-input-stream-bulk-path-fails", () -> {
            HttpExchange e = exchange("POST", "/hey"); InputStream body = e.getRequestBody(); body.close();
            rejects(() -> body.read()); rejects(body::readAllBytes); rejects(() -> body.readNBytes(1));
            rejects(() -> body.readNBytes(new byte[1], 0, 1)); rejects(() -> body.transferTo(new ByteArrayOutputStream()));
            rejects(() -> body.skip(1)); rejects(body::reset); rejects(() -> body.mark(1)); e.retire();
        });
        run("use-after-close-and-retirement-fails", () -> {
            HttpExchange e = exchange("POST", "/hey"); OutputStream body = e.getResponseBody();
            e.sendResponseHeaders(200, 1); body.write(7); e.close(); check(e.sealedBody()[0] == 7);
            rejects(() -> body.write(8)); rejects(e::getRequestBody); e.retire(); rejects(e::sealedBody);
        });
        run("body-limits-and-failed-close", () -> {
            rejects(() -> new HttpExchange("POST", "/hey", null, new Headers(), new byte[65537]));
            HttpExchange large = exchange("POST", "/hey"); rejects(() -> large.sendResponseHeaders(200, 262145)); large.retire();
            HttpExchange incomplete = exchange("POST", "/hey"); rejects(incomplete::close); rejects(incomplete::sealedBody); incomplete.retire();
        });
        check(cases == 16);
        System.out.println("native-server-kernel-cases=" + cases);
    }
}
