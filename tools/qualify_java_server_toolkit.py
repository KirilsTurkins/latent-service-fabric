#!/usr/bin/env python3
"""Execute installed Java route commands against real signed shared ingress."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.dev_workflow import build_artifacts, build_provenance, paths, tool_inventory
from tools.dev_workflow.common import decode, digest, encode, require
from tools.java_server_node import run
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.rust_capsule_project import fresh, read_file, read_json, write_json


class InstalledRoutes:
    def __init__(self, directory, cli, owner, *, mounts, tools, build, evidence):
        self.root = directory / "installed-command"
        paths.new_directory(self.root)
        self.cli, self.owner, self.tools, self.build = cli, owner, tools, build
        self.evidence = fresh(evidence)
        self.commands = []
        self.mounts = self.root / "mounts.json"
        self.mounts.write_bytes(encode(mounts))

    def call(self, command, *arguments):
        require(len(self.commands) < 16, "installed-server-command-count")
        remaining = int(self.cli.deadline - time.monotonic())
        require(remaining > 0, "installed-server-original-deadline")
        seconds = min(120, remaining)
        argv = [self.tools / "sdk/bin/python", "-I", "-B", self.tools / "recipe/tools/server_capsule.py",
            "--binary", self.cli.binary, "--config", self.cli.config, "--state", self.root,
            "--tenant", self.owner["tenant"], "--route", self.owner["route"], "--timeout", str(seconds), command, *arguments]
        result = run_bounded_result(list(map(str, argv)), self.root, build_environment(self.root),
                                    min(remaining, seconds + 1), 1048576)
        ordinal = str(len(self.commands) + 1)
        (self.evidence / (ordinal + ".stdout")).write_bytes(result.stdout)
        (self.evidence / (ordinal + ".stderr")).write_bytes(result.stderr)
        self.commands.append({"command": command, "exitCode": result.returncode,
            "stdoutDigest": digest(result.stdout), "stderrDigest": digest(result.stderr)})
        # Retain the original operation before propagating refusal/uncertainty.
        journal = self.root / "server-routes.json"
        if journal.exists():
            (self.evidence / (ordinal + "-journal.json")).write_bytes(read_file(journal, 1048576))
        write_json(self.evidence / (ordinal + "-command.json"), self.commands[-1])
        require(result.returncode == 0, "installed-server-original-command-failed-no-retry")
        return decode(result.stdout, 1048576)

    def apply(self, manifests):
        inputs = ("--declaration", self.build / "server-source.json", "--component", self.build / "component.wasm",
            "--source-inputs", self.build / "source-inputs.json", "--profile", self.build / "server-profile.json",
            "--mounts", self.mounts)
        planned = self.call("plan", *inputs)
        require(planned["triggers"] == manifests and planned["executionPermission"] is False,
                "installed-server-plan-changed-explicit-selection")
        result = self.call("apply", *inputs)
        self.call("inspect")
        return result

    def remove(self, names):
        return self.call("remove", *names)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tools", "native-directory", "native-tuple", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    tools = args.tools.resolve(strict=True)
    template = read_json(tools / "templates/java/greeting/template.json")
    inventory = tool_inventory.check(tools, template["project"], "linux-x86_64")
    binaries = {name: args.native_directory / name for name in ("latent", "latentd", "capsule_authoring")}
    native = ordinary_tuple(args.native_tuple, binaries)
    output = fresh(args.output)
    attempt = fresh(output / "attempt")
    (attempt / "build-cache").mkdir(mode=0o700)
    build = attempt / "output"
    commands = []
    def factory(directory, cli, owner, *, mounts):
        selected = InstalledRoutes(directory, cli, owner, mounts=mounts, tools=tools, build=build,
                                   evidence=output / "installed-operator")
        commands.append(selected.commands)
        return selected
    try:
        python = tools / "sdk/bin/python"
        for stage, arguments in (
            ("create", [tools / "recipe/tools/java_capsule.py", "new-server", attempt / "app", "--name", "my-server"]),
            ("compile", [tools / "recipe/tools/dev_guest_recipe.py", "--language", "java", "--project", attempt / "app", "--output", build]),
        ):
            result = run_bounded_result(list(map(str, [python, "-I", "-B", *arguments])), attempt,
                                        build_environment(attempt), 900, 1048576)
            (output / (stage + ".stdout")).write_bytes(result.stdout)
            (output / (stage + ".stderr")).write_bytes(result.stderr)
            require(result.returncode == 0, "installed-server-" + stage + "-failed-no-retry")
        descriptor = template["project"]
        packaged = build_artifacts.package(binaries["latent"], attempt, descriptor["artifacts"],
                                          time.monotonic() + 120, lambda: None, cached=False)
        packager = paths.digest_file(binaries["latent"].parent, "latent", 256 * 1024 * 1024)[0]
        build_provenance.complete(attempt, descriptor, binaries["latent"], packager, packaged)
        signed = output / "signed"
        signing = run_bounded_result([str(binaries["capsule_authoring"]), "demo-sign", str(signed), str(build)],
                                    output, build_environment(output), 30, 16384)
        (output / "signing.stdout").write_bytes(signing.stdout)
        (output / "signing.stderr").write_bytes(signing.stderr)
        require(signing.returncode == 0, "installed-server-exact-build-signing")
        result = run(binaries["latent"], binaries["latentd"], signed, build, output / "node",
                     tls_tool=binaries["capsule_authoring"], tls=True, routes_factory=factory)
        require(result["status"] == "passed", "installed-server-real-node-failed")
        require(tool_inventory.check(tools, template["project"], "linux-x86_64") == inventory,
                "installed-server-tool-inventory-changed")
        require(ordinary_tuple(args.native_tuple, binaries) == native, "installed-server-native-tuple-changed")
        write_json(output / "qualified.json", {"status": "passed", "scope": "installed-route-command-and-real-shared-listener",
            "toolInventory": inventory, "nativeTuple": native, "commands": commands[0], "httpObservations": len(result["http"]),
            "component": file_identity(build / "component.wasm"), "nodeReceipt": file_identity(output / "node/conformance.json"),
            "qualifier": file_identity(Path(__file__)), "nodeHarness": file_identity(Path(__file__).with_name("java_server_node.py")),
            "publisherAuthenticated": False, "releasePublished": False})
    except BaseException as error:
        write_json(output / "FAILED.json", {"status": "failed", "reason": type(error).__name__, "commands": commands})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
