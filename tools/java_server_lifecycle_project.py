"""Outside-checkout ordinary-source fixtures for real server lifecycle gates."""
from pathlib import Path
import json

from tools import java_http_client
from tools.java_capsule_project import ROOT, runtime_wit
from tools.java_server_project import create_server
from tools.rust_capsule_project import canonical, fresh


LIFECYCLE_SOURCE = '''package outside.developer.routes;

import com.sun.net.httpserver.HttpServer;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public final class LifecycleRoutes {
    private static int invocations;
    private static volatile long work;

    public static void install(HttpServer server) {
        server.createContext("/fresh", exchange -> {
            byte[] bytes = Integer.toString(++invocations).getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, bytes.length);
            try (var body = exchange.getResponseBody()) { body.write(bytes); }
        });
        server.createContext("/fuel", exchange -> {
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
    }
}
'''



def create(directory: Path, *, name: str, revision: str, peer_port: int,
           service: str | None = None, outbound_requests: int = 0) -> Path:
    if revision not in {"Hey!", "Revision-two"} or type(peer_port) is not int or not 1 <= peer_port <= 65535:
        raise ValueError("finite reviewed server lifecycle fixture selection required")
    if type(outbound_requests) is not int or outbound_requests not in {0, 1}:
        raise ValueError("lifecycle fixture requires the explicit zero-or-one request declaration")
    if service is not None and service != "examples/lifecycle-server":
        raise ValueError("lifecycle fixture service must remain the reviewed deployment target")
    root = create_server(directory, name)
    # Preserve the complete original helper fixture, including code after
    # start and every body/error case. Add only a separate ordinary helper.
    original = (ROOT / "sdk/java-guest/tests/server/Server.java").read_bytes()
    marker = b"        Router.install(server);\n"
    if original.count(marker) != 1:
        raise ValueError("maintained original helper registration shape changed")
    expanded = original.replace(marker, marker + b"        outside.developer.routes.LifecycleRoutes.install(server);\n")
    (root / "src/dev/latent/app/Server.java").write_bytes(expanded)
    helper = root / "src/outside/developer/routes"
    helper.mkdir(parents=True)
    router = (ROOT / "sdk/java-guest/tests/server/Router.java").read_bytes()
    if revision != "Hey!":
        if router.count(b'"Hey!".getBytes(StandardCharsets.UTF_8)') != 1:
            raise ValueError("maintained original helper reply shape changed")
        router = router.replace(b'"Hey!".getBytes(StandardCharsets.UTF_8)',
                                b'"Revision-two".getBytes(StandardCharsets.UTF_8)')
    (helper / "Router.java").write_bytes(router)
    (helper / "LifecycleRoutes.java").write_text(
        LIFECYCLE_SOURCE.replace("/*REVISION*/", revision).replace("/*PORT*/", str(peer_port)),
        encoding="utf-8", newline="\n")
    project = json.loads((root / "capsule-project.json").read_bytes())
    project["httpClient"] = {"profile": java_http_client.PROFILE_ID}
    if service is not None:
        project["service"] = service
    project["limits"]["outboundRequests"] = outbound_requests
    (root / "capsule-project.json").write_bytes(canonical(project) + b"\n")
    world = (f"package examples:{project['name']}@1.0.0;\nworld service {{\n"
        "  import latent:context/context@0.1.0;\n"
        "  import latent:http/streaming@0.3.0;\n"
        "  export latent:web/application@0.1.0;\n}\n").encode()
    (root / "wit/world.wit").write_bytes(runtime_wit(world, "service"))
    return root


def create_fixtures(directory: Path, peer_port: int) -> dict[str, Path]:
    """Keep the complete zero-egress helper distinct from the one-call gate."""
    if type(peer_port) is not int or not 1 <= peer_port <= 65535:
        raise ValueError("finite reviewed server lifecycle fixture selection required")
    root = fresh(directory)
    baseline = create_server(root / "baseline", "lifecycle-server-baseline")
    (baseline / "src/dev/latent/app/Server.java").write_bytes(
        (ROOT / "sdk/java-guest/tests/server/Server.java").read_bytes())
    helper = baseline / "src/outside/developer/routes"
    helper.mkdir(parents=True)
    (helper / "Router.java").write_bytes((ROOT / "sdk/java-guest/tests/server/Router.java").read_bytes())
    return {"baseline": baseline, **{label: create(root / label,
        name="lifecycle-server-gate-" + label, revision=revision, peer_port=peer_port,
        service="examples/lifecycle-server", outbound_requests=1)
        for label, revision in (("first", "Hey!"), ("second", "Revision-two"))}}
