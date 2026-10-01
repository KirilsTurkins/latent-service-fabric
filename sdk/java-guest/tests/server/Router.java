package outside.developer.routes;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import dev.latent.app.Server;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/** Developer-owned helper: no SDK annotation, WIT or catalogue registration. */
public final class Router {
    private static int calls;
    private static volatile long spinning;
    private static volatile Object retained;

    public static void install(HttpServer server) {
        server.createContext("/hey", Router::hey);
        server.createContext("/hey/", Router::longest);
        server.createContext("/case", Router::cases);
    }

    private static void reply(HttpExchange exchange, int status, byte[] body) throws IOException {
        exchange.sendResponseHeaders(status, body.length);
        if (!exchange.getRequestMethod().equals("HEAD")) {
            try (var output = exchange.getResponseBody()) { output.write(body); }
        }
        exchange.close();
    }
    private static void hey(HttpExchange exchange) throws IOException {
        if (Server.initialized != 1 || ++calls != 1) throw new IOException("activation state leaked");
        reply(exchange, 200, "Hey!".getBytes(StandardCharsets.UTF_8));
    }
    private static void longest(HttpExchange exchange) throws IOException {
        if (!exchange.getHttpContext().getPath().equals("/hey/")) throw new IOException("wrong longest context");
        reply(exchange, 201, new byte[]{76});
    }
    private static void cases(HttpExchange exchange) throws IOException {
        if (Server.initialized != 1 || ++calls != 1) throw new IOException("activation state leaked");
        String query = exchange.getRequestURI().getRawQuery();
        if (query == null) query = "raw";
        if (query.startsWith("query&")) {
            reply(exchange, 200, query.getBytes(StandardCharsets.UTF_8));
            return;
        }
        switch (query) {
            case "raw":
                exchange.getResponseHeaders().add("Set-Cookie", "__Host-a=1; Secure; HttpOnly; SameSite=Strict; Path=/");
                exchange.getResponseHeaders().add("Set-Cookie", "__Host-b=2; Secure; HttpOnly; SameSite=Strict; Path=/");
                exchange.getResponseHeaders().set("Content-Type", "application/octet-stream");
                reply(exchange, 200, new byte[]{0, 1, (byte)128, (byte)255});
                return;
            case "input":
                if (!exchange.getRequestMethod().equals("POST")) throw new IOException("request method changed");
                reply(exchange, 200, exchange.getRequestBody().readAllBytes());
                return;
            case "error": reply(exchange, 500, new byte[]{69}); return;
            case "no-body": exchange.sendResponseHeaders(204, -1); exchange.close(); return;
            case "throw": throw new IOException("intentional bounded qualification failure");
            case "over": exchange.sendResponseHeaders(200, 1); exchange.getResponseBody().write(new byte[]{1, 2}); break;
            case "under": exchange.sendResponseHeaders(200, 2); exchange.getResponseBody().write(1); exchange.close(); break;
            case "double": exchange.sendResponseHeaders(200, -1); exchange.sendResponseHeaders(201, -1); break;
            case "before": exchange.getResponseBody().write(1); break;
            case "closed":
                exchange.sendResponseHeaders(200, 1);
                exchange.getResponseBody().write(1);
                exchange.close();
                exchange.getResponseBody().write(2);
                break;
            case "flush": exchange.sendResponseHeaders(200, 1); exchange.getResponseBody().flush(); break;
            case "chunk": exchange.sendResponseHeaders(200, 0); break;
            case "forbidden":
                exchange.getResponseHeaders().set("Authorization", "qualification-only");
                exchange.sendResponseHeaders(200, -1);
                break;
            case "unsafe-cookie":
                exchange.getResponseHeaders().add("Set-Cookie", "a=1; HttpOnly");
                reply(exchange, 200, new byte[]{65});
                return;
            case "oversize": exchange.sendResponseHeaders(200, 262145); break;
            case "memory": retained = new byte[70000000]; break;
            case "spin": while (true) spinning++;
            default: throw new IOException("unknown qualification case");
        }
        throw new IOException("invalid response must not become success");
    }
}
