package dev.latent.app;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import outside.developer.routes.Router;

/** Captured ordinary application source, including effects after start. */
public final class Server {
    public static int initialized;
    public static void main(String[] arguments) throws Exception {
        var server = HttpServer.create(new InetSocketAddress(8080), 0);
        Router.install(server);
        server.start();
        initialized++;
    }
}
