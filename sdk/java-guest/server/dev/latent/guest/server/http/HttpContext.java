package dev.latent.guest.server.http;

/** A context is invocation-local; mutation is permitted only before start. */
public final class HttpContext {
    private final HttpServer server;
    private final String path;
    private HttpHandler handler;
    HttpContext(HttpServer server, String path, HttpHandler handler) {
        this.server = server;
        this.path = path;
        this.handler = handler;
    }
    public String getPath() { return path; }
    public HttpServer getServer() { return server; }
    public HttpHandler getHandler() { return handler; }
    public void setHandler(HttpHandler value) {
        server.registration();
        if (value == null) throw new NullPointerException();
        if (handler != null) throw new IllegalArgumentException("handler already assigned");
        handler = value;
    }
}
