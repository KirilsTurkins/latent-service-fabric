"""Outside-checkout ordinary-source fixtures for real server lifecycle gates."""
from pathlib import Path
import json

from tools import java_http_client
from tools.java_capsule_project import runtime_wit
from tools.java_server_project import create_server
from tools.rust_capsule_project import canonical


SOURCE = '''package dev.latent.app;

import com.sun.net.httpserver.HttpServer;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public final class Server {
    private static int invocations;

    public static void main(String[] arguments) throws Exception {
        var server = HttpServer.create(new InetSocketAddress(8080), 0);
        server.createContext("/hey", exchange -> {
            byte[] bytes = "/*REVISION*/".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, bytes.length);
            try (var body = exchange.getResponseBody()) { body.write(bytes); }
        });
        server.createContext("/fresh", exchange -> {
            byte[] bytes = Integer.toString(++invocations).getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, bytes.length);
            try (var body = exchange.getResponseBody()) { body.write(bytes); }
        });
        server.createContext("/fuel", exchange -> {
            long work = 0;
            while (true) { work++; }
        });
        server.createContext("/gate", exchange -> {
            var connection = (HttpURLConnection) new URL("http://127.0.0.1:/*PORT*//gate").openConnection();
            connection.setRequestMethod("GET");
            try (var input = connection.getInputStream()) {
                byte[] peer = input.readAllBytes();
                if (peer.length != 1 || peer[0] != 71) throw new java.io.IOException("controlled gate reply");
            } finally { connection.disconnect(); }
            byte[] bytes = "/*REVISION*/".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, bytes.length);
            try (var body = exchange.getResponseBody()) { body.write(bytes); }
        });
        server.start();
    }
}
'''


def create(directory: Path, *, name: str, revision: str, peer_port: int) -> Path:
    if revision not in {"Hey!", "Revision-two"} or type(peer_port) is not int or not 1 <= peer_port <= 65535:
        raise ValueError("finite reviewed server lifecycle fixture selection required")
    root = create_server(directory, name)
    # Edit only developer-owned source/declaration. Captured SDK and lock remain
    # exact; production compilation/inspection/signing are separate required steps.
    (root / "src/dev/latent/app/Server.java").write_text(
        SOURCE.replace("/*REVISION*/", revision).replace("/*PORT*/", str(peer_port)), encoding="utf-8")
    project = json.loads((root / "capsule-project.json").read_bytes())
    project["httpClient"] = {"profile": java_http_client.PROFILE_ID}
    (root / "capsule-project.json").write_bytes(canonical(project) + b"\n")
    world = (f"package examples:{project['name']}@1.0.0;\nworld service {{\n"
        "  import latent:context/context@0.1.0;\n"
        "  import latent:http/streaming@0.3.0;\n"
        "  export latent:web/application@0.1.0;\n}\n").encode()
    (root / "wit/world.wit").write_bytes(runtime_wit(world, "service"))
    return root
