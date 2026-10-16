"""Ordinary Java source that detects state crossing actual HTTP activations."""
import json
from pathlib import Path

from tools.java_capsule_project import ROOT
from tools.java_server_project import create_server
from tools.rust_capsule_project import canonical

SOURCE = '''package outside.developer.routes;
import com.sun.net.httpserver.HttpServer;
import dev.latent.app.Server;
import java.nio.charset.StandardCharsets;

public final class TenantRoutes {
    private static Object retained;
    private static int calls;
    public static void install(HttpServer server) {
        server.createContext("/isolation", exchange -> {
            if (Server.initialized != 1 || retained != null || ++calls != 1)
                throw new java.io.IOException("activation state crossed");
            String marker = exchange.getRequestHeaders().getFirst("X-Isolation-Marker");
            if (marker == null || marker.length() > 64) throw new java.io.IOException("marker");
            byte[] input = exchange.getRequestBody().readAllBytes();
            retained = new Object[]{marker, input};
            byte[] prefix = (marker + "|fresh=1|").getBytes(StandardCharsets.UTF_8);
            byte[] result = new byte[prefix.length + input.length];
            System.arraycopy(prefix, 0, result, 0, prefix.length);
            System.arraycopy(input, 0, result, prefix.length, input.length);
            exchange.sendResponseHeaders(200, result.length);
            try (var body = exchange.getResponseBody()) { body.write(result); }
        });
    }
}
'''


def create(directory: Path) -> Path:
    root = create_server(directory, "tenant-isolation-server")
    original = (ROOT / "sdk/java-guest/tests/server/Server.java").read_bytes()
    marker = b"        Router.install(server);\n"
    if original.count(marker) != 1:
        raise ValueError("original server helper registration changed")
    (root / "src/dev/latent/app/Server.java").write_bytes(original.replace(marker,
        marker + b"        outside.developer.routes.TenantRoutes.install(server);\n"))
    helper = root / "src/outside/developer/routes"
    helper.mkdir(parents=True)
    (helper / "Router.java").write_bytes((ROOT / "sdk/java-guest/tests/server/Router.java").read_bytes())
    (helper / "TenantRoutes.java").write_text(SOURCE, encoding="utf-8")
    project = json.loads((root / "capsule-project.json").read_bytes())
    project["tenant"] = None
    (root / "capsule-project.json").write_bytes(canonical(project) + b"\n")
    return root
