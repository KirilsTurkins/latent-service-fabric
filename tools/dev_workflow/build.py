"""Run one explicitly trusted recipe in a new, bounded build attempt."""
from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import platform
import time

from . import build_artifacts, build_cache, diagnostics, paths, process, project, snapshot, state
from .common import DevError, HOST_ABI, decode, encode, require


def unchanged(source: Path, descriptor: dict, record: dict) -> None:
    observed, _content = snapshot.observe(source, descriptor["inputRoots"], tuple(descriptor["exclude"]))
    require(observed == record, "source-or-generated-bindings-changed-during-build")


def compile_recipe(root: Path, source: Path, descriptor: dict, record: dict, tools: dict, deadline: float, check) -> list:
    recipe = descriptor["build"]
    output = source / recipe["outputRoot"]
    require(not output.exists(), "stale-build-output-rejected")
    working = source / recipe["workingDirectory"]
    environment = process.environment(source)
    environment["PATH"] = os.pathsep.join(sorted({str(path.parent) for path in tools.values()})) + os.pathsep + os.defpath
    # No inherited compiler wrappers, production keys or developer HOME.
    environment.update({"CARGO_HOME": str(source / "build-cache/cargo"), "CARGO_TARGET_DIR": str(output / "cargo"),
                        "GOCACHE": str(source / "build-cache/go"), "GOMODCACHE": str(source / "build-cache/modules"),
                        "NPM_CONFIG_CACHE": str(source / "build-cache/npm"), "DOTNET_CLI_HOME": str(source / "build-cache/dotnet")})
    remaining = deadline - time.monotonic()
    require(remaining > 0, "build-deadline-exceeded")
    with paths.directory(working):
        result = process.run([str(tools[recipe["argv"][0]]), *recipe["argv"][1:]], working, env=environment,
                             timeout=remaining, maximum=recipe["maximumOutputBytes"], check=check)
    observed = diagnostics.collect(result.stdout, result.stderr, source, working, {item["path"] for item in record["files"]})
    state.atomic(root, "build-diagnostics.json", {"source": record["identity"], "diagnostics": observed})
    if result.returncode != 0:
        raise DevError("guest-build-failed-last-deployment-retained", diagnostics=observed)
    return observed


def execute(root: Path, source: Path, descriptor: dict, tool_root: Path, *, trusted: str, cli: Path, control=None) -> dict:
    project.validate(descriptor)
    require(trusted == project.trust_identity(descriptor), "workspace-recipe-trust-required")
    record = decode(paths.read(source, "snapshot.json"))
    snapshot.validate(record)
    unchanged(source, descriptor, record)
    host = ("windows" if os.name == "nt" else "linux") + "-" + ("x86_64" if platform.machine().lower() == "amd64" else platform.machine())
    recipe = descriptor["build"]
    require(host in recipe["hostTargets"], "guest-compiler-host-unsupported-select-explicit-build-alternative")
    deadline = time.monotonic() + recipe["timeoutSeconds"]
    with ExitStack() as stack:
        tools = {}
        # Recheck pinned binaries even on a cache hit and hold them throughout the operation.
        for tool in recipe["tools"]:
            stack.enter_context(paths.opened(tool_root, tool["path"]))
            require(paths.digest_file(tool_root, tool["path"], 256 * 1024 * 1024)[0] == tool["sha256"], "guest-tool-digest-mismatch")
            tools[tool["name"]] = tool_root / tool["path"]
        stack.enter_context(paths.opened(cli.parent, cli.name))
        packager = paths.digest_file(cli.parent, cli.name, 256 * 1024 * 1024)[0]
        attempt, working, receipt = build_cache.allocate(root, source, record, descriptor, trusted, host, packager)
        if control is not None:
            control.attach(attempt)
        observe_usage = build_cache.monitor(attempt)
        def check():
            if control is not None:
                control.check()
            observe_usage()
        try:
            check()
            if receipt is None:
                build_cache.transition(attempt, "running")
                observed = compile_recipe(root, working, descriptor, record, tools, deadline, check)
                unchanged(working, descriptor, record)
                packaged = build_artifacts.package(cli, working, descriptor["artifacts"], deadline, check, cached=False)
                receipt = {"schemaVersion": "latent.dev.build.v1", "source": record["identity"], "recipe": trusted,
                    "host": host, "target": recipe["target"], "hostAbi": HOST_ABI,
                    "artifacts": build_artifacts.identities(working, descriptor["artifacts"]), "package": packaged,
                    "tools": recipe["tools"], "template": descriptor["template"], "authority": "observed-local-build",
                    "diagnostics": observed, "attempt": attempt.name, "packager": packager,
                    "buildKey": build_cache.identity(record, descriptor, trusted, host, packager)}
                paths.write_new(working / "build-receipt.json", encode(receipt))
            else:
                build_artifacts.verify_receipt(working, descriptor, receipt)
                require(build_artifacts.package(cli, working, descriptor["artifacts"], deadline, check, cached=True)
                        == receipt["package"], "cached-package-modified")
            unchanged(working, descriptor, record)
            unchanged(source, descriptor, record)
            build_cache.usage(attempt)
            check()
            build_cache.transition(attempt, "complete")
            state.atomic(root, "last-build.json", {"sourceDirectory": str(working), "receipt": receipt})
            return receipt
        except BaseException as error:
            # Process.run confirms child reaping before propagating ordinary failure/cancellation.
            uncertain = isinstance(error, DevError) and error.uncertain
            build_cache.transition(attempt, "uncertain" if uncertain else "failed")
            raise


def accepted(root: Path, saved: dict) -> tuple[Path, dict]:
    last = state.load(root, "last-build.json")
    receipt = last["receipt"]
    require(receipt["source"] == saved["snapshot"] and receipt["recipe"] == saved["trust"], "stale-build-receipt")
    source = Path(last["sourceDirectory"])
    require(source == root / "builds" / receipt["attempt"] / "source", "build-attempt-path-mismatch")
    owner = build_cache.owner(source.parent)
    require(owner["state"] == "complete" and owner["key"] == receipt["buildKey"], "build-attempt-not-complete")
    require(decode(paths.read(source, "build-receipt.json")) == receipt, "build-receipt-modified")
    build_artifacts.verify_receipt(source, saved["descriptor"], receipt)
    return source, receipt
