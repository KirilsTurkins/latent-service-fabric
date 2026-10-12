package dev.latent.guest.server.http;

import java.io.IOException;

/** Compiler-owned activation gate; never an application-authored adapter. */
public final class ServerSession {
    private static boolean active;
    private static HttpServer server;
    private ServerSession() { }
    public static void begin() {
        if (active) throw new IllegalStateException("nested server activation");
        active = true;
        server = null;
    }
    static void register(HttpServer value) {
        if (!active || server != null) throw new IllegalStateException("simple profile requires one activation-local server");
        server = value;
    }
    public static void dispatch(HttpExchange exchange) throws IOException {
        if (!active || server == null) throw new IllegalStateException("original initialization did not register server");
        server.dispatch(exchange);
    }
    public static void verify(String address, int port, int backlog, String[] paths) {
        if (!active || server == null) throw new IllegalStateException("original initialization did not register a server");
        server.verify(address, port, backlog, paths);
    }
    public static void retire() {
        if (server != null) server.retire();
        server = null;
        active = false;
    }
}
