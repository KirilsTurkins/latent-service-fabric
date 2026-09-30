package dev.latent.guest.server.http;

import java.io.IOException;

@FunctionalInterface
public interface HttpHandler {
    void handle(HttpExchange exchange) throws IOException;
}
