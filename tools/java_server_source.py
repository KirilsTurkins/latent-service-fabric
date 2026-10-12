"""SDK-owned static Java server analysis and automatic invocation bridge."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from tools import server_source
from tools.rust_capsule_project import canonical, digest, inventory, read_file, snapshot, write_json

PROFILE_ID = "lsf.java.httpserver.buffered.v1"
RECIPE = ("tools/java_server_source.py", "tools/java_server_project.py", *server_source.RECIPE)
SOURCE_APIS = [
    "com.sun.net.httpserver.HttpServer.create", "com.sun.net.httpserver.HttpServer.createContext",
    "com.sun.net.httpserver.HttpServer.start", "com.sun.net.httpserver.HttpServer.setExecutor-null",
    "com.sun.net.httpserver.HttpContext.setHandler", "com.sun.net.httpserver.HttpContext.getPath",
    "com.sun.net.httpserver.HttpContext.getHandler", "com.sun.net.httpserver.HttpExchange.getRequestMethod",
    "com.sun.net.httpserver.HttpExchange.getRequestURI", "com.sun.net.httpserver.HttpExchange.getRequestHeaders",
    "com.sun.net.httpserver.HttpExchange.getResponseHeaders", "com.sun.net.httpserver.HttpExchange.getRequestBody",
    "com.sun.net.httpserver.HttpExchange.getResponseBody", "com.sun.net.httpserver.HttpExchange.getHttpContext",
    "com.sun.net.httpserver.HttpExchange.getResponseCode", "com.sun.net.httpserver.HttpExchange.sendResponseHeaders-positive-or-minus-one",
    "com.sun.net.httpserver.HttpExchange.close", "com.sun.net.httpserver.Headers",
    "java.net.InetSocketAddress.logical-wildcard-or-ipv4-loopback",
]
UNSUPPORTED = [
    "HttpServer.create-no-address", "HttpServer.bind", "HttpServer.getAddress", "HttpServer.stop",
    "HttpServer.setExecutor-custom", "HttpServer.getExecutor-after-start", "HttpServer.removeContext",
    "HttpContext.getFilters", "HttpContext.setAuthenticator", "HttpsServer", "HttpExchange.getPrincipal",
    "HttpExchange.getLocalAddress", "HttpExchange.getRemoteAddress", "HttpExchange.getProtocol",
    "HttpExchange.getAttribute", "HttpExchange.setAttribute", "HttpExchange.setStreams",
    "HttpExchange.chunked-response-zero-length", "OutputStream.flush", "Headers.mutable-map-views",
    "ServerSocket.accept", "dynamic-server-registration", "persistent-server-workers",
]


def selection(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"profile", "entryPoint"}
            or value["profile"] != PROFILE_ID or not isinstance(value["entryPoint"], str)
            or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)+", value["entryPoint"])
            or len(value["entryPoint"]) > 160 or value["entryPoint"] == "dev.latent.app.Capsule"
            or value["entryPoint"].startswith(("java.", "javax.", "com.sun.", "dev.latent.guest.", "dev.latent.generated."))):
        raise ValueError("unsupported Java server profile or original public main")
    return value


def analyze(compiler, sources: Path, selected: dict, jars: tuple[Path, ...], output: Path) -> dict:
    selection(selected)
    empty = output / "server-empty-classpath"
    empty.mkdir()
    # This argument is javac's symbol classpath, never the analyzer JVM's loader.
    # -proc:none and analyze (without generate) prevent application processors,
    # main methods and static initializers from executing on the compiler host.
    classpath = os.pathsep.join(map(str, jars)) if jars else str(empty)
    try:
        raw = compiler.run("server-source-analysis", "java", compiler.sdk / "server/analysis/ServerAnalyzer.java",
                           sources, selected["entryPoint"], classpath)
    except ValueError:
        # Keep closed, source-attributed diagnostics from the failed bounded command.
        logs = sorted(compiler.directory.glob("*-server-source-analysis.log"))
        if logs:
            try:
                report = json.loads(read_file(logs[-1], 1024 * 1024))
                if report.get("schemaVersion") == "lsf.java.server.analysis.v1" and report.get("status") == "blocked":
                    write_json(output / "server-analysis.json", report)
            except (ValueError, OSError, UnicodeError): pass
        raise
    report = json.loads(raw)
    if (not isinstance(report, dict) or set(report) != {"schemaVersion", "status", "plan"}
            or report["schemaVersion"] != "lsf.java.server.analysis.v1" or report["status"] != "observed"):
        raise ValueError("invalid Java server AST analysis result")
    plan = report["plan"]
    if plan.get("initializer") != selected["entryPoint"] + ".main" or plan.get("extraction") != "compiler-ast":
        raise ValueError("Java server analysis changed original initializer")
    files = {"src/" + name: data for name, data in snapshot(sources).items()}
    server_source.endpoints(plan["endpoints"], files)
    if len(plan["endpoints"]) != 1: raise ValueError("simple Java server profile supports one logical endpoint")
    write_json(output / "server-analysis.json", report)
    return plan


def bridge(sdk: Path, selected: dict, plan: dict) -> bytes:
    selection(selected)
    server_source.endpoints(plan["endpoints"])
    if len(plan["endpoints"]) != 1 or plan["initializer"] != selected["entryPoint"] + ".main":
        raise ValueError("server bridge requires the exact analyzed initializer and endpoint")
    endpoint = plan["endpoints"][0]
    # Validated identifiers and Java/JSON-compatible ASCII path literals; no
    # application source rewrite, user-supplied Java expression or package switch.
    paths = ", ".join(json.dumps(context["path"]) for context in endpoint["contexts"])
    bind = endpoint["bind"]
    registration = f'{json.dumps(bind["address"])}, {bind["port"]}, {bind["backlog"]}, new String[]{{{paths}}}'
    template = read_file(sdk / "server/templates/Capsule.java").decode()
    for marker in ("/*LSF_INITIALIZER*/", "/*LSF_DECLARED_REGISTRATION*/"):
        if template.count(marker) != 1: raise ValueError("invalid captured server invocation bridge")
    return template.replace("/*LSF_INITIALIZER*/", selected["entryPoint"]).replace("/*LSF_DECLARED_REGISTRATION*/", registration).encode()


def profile(compiler, recipe_inputs: bytes) -> bytes:
    server = snapshot(compiler.sdk / "server")
    runtime = snapshot(compiler.sdk / "runtime")
    return canonical({"schemaVersion": server_source.PROFILE, "id": PROFILE_ID, "language": "java",
        "sourceApis": SOURCE_APIS, "compilerDigest": digest(canonical({"distributions": digest(compiler.compiler_inputs),
            "tools": compiler.materials, "bindings": compiler.binding_digest, "recipe": digest(recipe_inputs),
            "compilerDependencyLock": digest(read_file(compiler.sdk / "feasibility/dependencies.lock.json"))})),
        "adapter": {"kind": "automatic", "digest": digest(inventory(server))},
        "runtimeDigest": digest(inventory(runtime)), "initialization": "fresh-original-entrypoint",
        "target": {"contract": server_source.WEB, "function": "handle", "profile": "buffered-v1"},
        "limits": {"endpoints": 1, "contexts": server_source.MAX_CONTEXTS,
                   "requestBodyBytes": 65536, "responseBodyBytes": 262144, "headers": 64, "headerBytes": 16384},
        "unsupported": UNSUPPORTED})
