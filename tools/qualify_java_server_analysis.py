#!/usr/bin/env python3
"""Bounded real JDK/AST/kernel checks; no signed-component or ingress claim."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time
import tomllib

if __package__ in {None, ""}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded_result
from tools.java_guest.compiler import sdk_snapshot, source_module, tool_inventory
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, write_json

MAIN = '''package dev.latent.app;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
public final class Server {
    public static void main(String[] arguments) throws Exception {
        var server = HttpServer.create(new InetSocketAddress(8080), 0);
        /*REGISTRATION*/
        server.start();
        /*AFTER*/
    }
    /*EXTRA*/
}
'''
HANDLER = 'exchange -> { exchange.sendResponseHeaders(200, -1); exchange.close(); }'
REGISTER = 'server.createContext("/hey", ' + HANDLER + ');'
REFERENCE = '''import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
public final class Reference {
    public static void main(String[] arguments) throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/hey", exchange -> {
            byte[] body = "Hey!".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            try (var output = exchange.getResponseBody()) { output.write(body); }
        });
        server.createContext("/hey/", exchange -> { exchange.sendResponseHeaders(201, -1); exchange.close(); });
        server.start();
        try (var client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build()) {
            for (String path : new String[]{"/hey", "/heyday", "/hey/", "/hey/child", "/HEY", "/other", "/hey?q=a%2Fb+z&q="}) {
                var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + server.getAddress().getPort() + path))
                    .timeout(Duration.ofSeconds(5)).GET().build();
                var response = client.send(request, HttpResponse.BodyHandlers.ofByteArray());
                int expected = path.startsWith("/hey/") ? 201 : path.startsWith("/hey") ? 200 : 404;
                if (response.statusCode() != expected || expected == 200 && !java.util.Arrays.equals(response.body(), "Hey!".getBytes(StandardCharsets.UTF_8))) {
                    throw new AssertionError("JDK reference matching/body mismatch");
                }
            }
            System.out.println("jdk-reference-cases=7");
        } finally { server.stop(0); }
    }
}
'''


def qualify(output: Path) -> dict:
    output = fresh(output)
    environment = build_environment(output)
    java = shutil.which("java", path=environment.get("PATH"))
    if java is None: raise ValueError("pinned full Java compiler missing")
    java = Path(java).resolve(strict=True)
    javac = java.with_name("javac.exe" if sys.platform == "win32" else "javac")
    tools = tool_inventory({"jdk": java.parent.parent})
    before = sdk_snapshot(ROOT / "sdk/java-guest")
    records = []
    deadline = time.monotonic() + 180
    def command(stage, *arguments, expected=0):
        remaining = min(60, deadline - time.monotonic())
        if remaining <= 0: raise ValueError("server analysis qualification deadline")
        result = run_bounded_result(list(map(str, arguments)), output, environment, timeout_seconds=remaining,
                                    max_output_bytes=1024 * 1024)
        (output / (stage + ".log")).write_bytes(result.stdout + b"\n" + result.stderr)
        records.append({"stage": stage, "exitCode": result.returncode})
        if result.returncode != expected: raise ValueError("server conformance stage failed: " + stage)
        return result.stdout.decode("utf-8")
    report = {"schemaVersion": "lsf.java.server.native-conformance.v1", "status": "in-progress", "authority": "none",
              "signedAdmission": "not-evaluated", "sharedListener": "not-evaluated", "commands": records}
    try:
        version = command("java-version", java, "-version")
        # The launcher prints its exact reviewed version on stderr.
        version = (output / "java-version.log").read_text()
        pins = tomllib.loads(read_file(ROOT / "tools/toolchain.toml").decode())
        source_module(ROOT / "sdk/java-guest/tools/feasibility.py").verify_version("java-version", version, pins["sdk"]["java"])
        classes = output / "kernel-classes"
        classes.mkdir()
        command("kernel-compile", javac, "-proc:none", "--release", "25", "-d", classes,
                *sorted((ROOT / "sdk/java-guest/server/dev").rglob("*.java")), ROOT / "sdk/java-guest/tests/ServerConformance.java")
        kernel = command("kernel-execution", java, "-cp", classes, "dev.latent.guest.server.http.ServerConformance")
        if not kernel.endswith("native-server-kernel-cases=16\n"): raise ValueError("native kernel case inventory changed")
        empty = output / "empty-classpath"
        empty.mkdir()
        source = lambda registration=REGISTER, after="", extra="": MAIN.replace("/*REGISTRATION*/", registration).replace("/*AFTER*/", after).replace("/*EXTRA*/", extra)
        canary = output / "application-host-startup-canary"
        helper = '''package independent.notacatalogue;
import com.sun.net.httpserver.HttpServer;
public final class Router { public static void install(HttpServer server) {
    server.createContext("/hey", exchange -> { exchange.sendResponseHeaders(200, -1); exchange.close(); });
} }
'''
        cases = [
            ("ordinary", source(), None, None),
            ("independent-helper", source("independent.notacatalogue.Router.install(server);"), helper, None),
            ("unused-unsupported-class", source(extra="static void unused() throws Exception { HttpServer.create().getAddress(); }"), None, None),
            ("original-static-initializer-never-run-on-host", source(extra='static { try { java.nio.file.Files.writeString(java.nio.file.Path.of(' + json.dumps(str(canary)) + '), "executed"); } catch (Exception error) { throw new IllegalStateException(error); } }'), None, None),
            ("code-after-start-retained", source(after="after++;", extra="static int after;"), None, None),
            ("dynamic-path", source('server.createContext(System.getenv("ROUTE"), ' + HANDLER + ');'), None, "constant-context-path-required"),
            ("conditional-registration", source('if (arguments.length == 0) { ' + REGISTER + ' }'), None, "dynamic-registration-control-flow-unsupported"),
            ("duplicate-context", source(REGISTER + REGISTER), None, "conflicting-context-registration"),
            ("custom-executor", source(REGISTER + "server.setExecutor(Runnable::run);"), None, "server-member-outside-simple-profile"),
            ("unsupported-handler-member", source('server.createContext("/hey", exchange -> { exchange.getPrincipal(); });'), None, "handler-member-outside-simple-profile"),
            ("encoded-context-path", source(REGISTER.replace('"/hey"', '"/a%2Fb"')), None, "context-path-outside-canonical-profile"),
            ("source-dns-address", source().replace("new InetSocketAddress(8080)", 'new InetSocketAddress("example.invalid", 8080)'), None, "constant-wildcard-or-ipv4-loopback-required"),
            ("live-context-mutation", source(after=REGISTER.replace('"/hey"', '"/later"')), None, "live-context-mutation-unsupported"),
        ]
        observed = []
        for name, content, additional, blocked in cases:
            sources = output / name / "src/dev/latent/app"
            sources.mkdir(parents=True)
            (sources / "Server.java").write_text(content, encoding="utf-8")
            if additional is not None:
                target = sources.parents[2] / "independent/notacatalogue/Router.java"
                target.parent.mkdir(parents=True)
                target.write_text(additional, encoding="utf-8")
            raw = command("analysis-" + name, java, ROOT / "sdk/java-guest/server/analysis/ServerAnalyzer.java",
                          sources.parents[2], "dev.latent.app.Server", empty, expected=2 if blocked else 0)
            result = json.loads(raw)
            if result.get("status") != ("blocked" if blocked else "observed"): raise ValueError("analysis outcome mismatch")
            if blocked and result["diagnostics"][0]["code"] != blocked: raise ValueError("analysis producer diagnostic mismatch")
            if not blocked and result["plan"]["endpoints"][0]["contexts"][0]["path"] != "/hey": raise ValueError("analysis changed captured context")
            if canary.exists(): raise ValueError("application initialization executed on compiler host")
            observed.append({"case": name, "status": result["status"], "code": blocked})
        reference = output / "Reference.java"
        reference.write_text(REFERENCE, encoding="utf-8")
        reference_output = command("jdk-reference", java, reference)
        if not reference_output.endswith("jdk-reference-cases=7\n"): raise ValueError("JDK reference inventory changed")
        if sdk_snapshot(ROOT / "sdk/java-guest") != before or tool_inventory({"jdk": java.parent.parent}) != tools:
            raise ValueError("server conformance SDK or compiler changed")
        report.update(status="observed-native", kernelCases=16, astCases=observed, jdkReferenceCases=7,
                      sdkDigest=digest(inventory(before)), compilerDigest=digest(tools), java=file_identity(java, "java"))
        write_json(output / "conformance.json", report)
        return report
    except BaseException as error:
        report.update(status="failed", reason=str(error) if isinstance(error, ValueError) else type(error).__name__)
        write_json(output / "CONFORMANCE-FAILED.json", report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = qualify(args.output)
    print(json.dumps({key: result[key] for key in ("status", "kernelCases", "jdkReferenceCases")}))


if __name__ == "__main__": main()
