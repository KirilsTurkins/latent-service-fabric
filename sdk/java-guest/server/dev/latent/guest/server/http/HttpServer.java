package dev.latent.guest.server.http;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Executor;

/** Logical registration only. No socket, worker, or application-owned listener. */
public final class HttpServer {
    private final InetSocketAddress address;
    private final int backlog;
    private final Map<String, HttpContext> contexts = new LinkedHashMap<>();
    private boolean started;
    private boolean retired;

    private HttpServer(InetSocketAddress address, int backlog) {
        if (address == null || address.getPort() <= 0 || backlog < 0 || backlog > 65535) {
            throw new IllegalArgumentException("unsupported logical server address or backlog");
        }
        this.address = address;
        this.backlog = backlog;
        ServerSession.register(this);
    }
    public static HttpServer create(InetSocketAddress address, int backlog) throws IOException {
        return new HttpServer(address, backlog);
    }
    void registration() {
        if (started || retired) throw new IllegalStateException("live server context mutation is unsupported");
    }
    public HttpContext createContext(String path, HttpHandler handler) {
        registration();
        if (!canonical(path) || contexts.containsKey(path)
                || contexts.size() >= 64) throw new IllegalArgumentException("invalid or conflicting context");
        if (handler == null) throw new NullPointerException();
        HttpContext context = new HttpContext(this, path, handler);
        contexts.put(path, context);
        return context;
    }
    public HttpContext createContext(String path) {
        registration();
        if (!canonical(path) || contexts.containsKey(path)
                || contexts.size() >= 64) throw new IllegalArgumentException("invalid or conflicting context");
        HttpContext context = new HttpContext(this, path, null);
        contexts.put(path, context);
        return context;
    }
    public void start() {
        registration();
        if (contexts.isEmpty()) throw new IllegalStateException("server has no statically captured context");
        for (HttpContext context : contexts.values()) {
            if (context.getHandler() == null) throw new IllegalStateException("context has no handler");
        }
        started = true;
    }
    private static boolean canonical(String path) {
        if (path == null || path.length() > 1024 || !path.matches("/[A-Za-z0-9._~!$&'()*+,;=:@/-]*")
                || path.contains("//") || path.equals("/_lsf") || path.startsWith("/_lsf/")) return false;
        for (String part : path.split("/")) if (part.equals(".") || part.equals("..")) return false;
        return true;
    }
    void verify(String bind, int port, int expectedBacklog, String[] paths) {
        if (!started || retired || address.getPort() != port || backlog != expectedBacklog
                || !(address.getAddress().isAnyLocalAddress() && bind.equals("wildcard")
                    || address.getAddress().isLoopbackAddress() && bind.equals("loopback"))
                || contexts.size() != paths.length) throw new IllegalStateException("registration differs from captured declaration");
        int index = 0;
        for (String path : contexts.keySet()) {
            if (!path.equals(paths[index++])) throw new IllegalStateException("registration differs from captured declaration");
        }
    }
    public void setExecutor(Executor value) {
        registration();
        if (value != null) throw new UnsupportedOperationException("custom server executor requires qualified runtime profile");
    }
    public Executor getExecutor() {
        if (started || retired) throw new UnsupportedOperationException("default executor introspection has no buffered profile mapping");
        return null;
    }
    public InetSocketAddress getAddress() {
        throw new UnsupportedOperationException("logical declaration is not a bound address observation");
    }
    public void stop(int delay) {
        throw new UnsupportedOperationException("server shutdown lifecycle requires a separate qualified profile");
    }
    public void removeContext(String path) {
        throw new UnsupportedOperationException("context removal has no static-registration profile mapping");
    }
    public void removeContext(HttpContext context) {
        throw new UnsupportedOperationException("context removal has no static-registration profile mapping");
    }
    void dispatch(HttpExchange exchange) throws IOException {
        if (!started || retired) throw new IllegalStateException("server is not started");
        String path = exchange.getRequestURI().getRawPath();
        HttpContext selected = null;
        for (HttpContext context : contexts.values()) {
            if (path.startsWith(context.getPath()) && (selected == null || context.getPath().length() > selected.getPath().length())) {
                selected = context;
            }
        }
        if (selected == null) {
            exchange.sendResponseHeaders(404, -1);
            exchange.close();
            return;
        }
        exchange.context(selected);
        selected.getHandler().handle(exchange);
    }
    void retire() {
        retired = true;
        contexts.clear();
    }
}
