"""Run an explicitly trusted recipe on one immutable source snapshot."""
from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import platform

from . import diagnostics, paths, process, project, snapshot, state
from .common import DevError, HOST_ABI, MAX_DOCUMENT, decode, digest, encode, require


def execute(root: Path, source: Path, descriptor: dict, tool_root: Path, *, trusted: str, cli: Path) -> dict:
    project.validate(descriptor)
    require(trusted == project.trust_identity(descriptor), "workspace-recipe-trust-required")
    record = decode(paths.read(source, "snapshot.json"))
    from .snapshot import validate
    validate(record)
    # Recheck every source byte on the Linux filesystem before executing.
    for item in record["files"]:
        require(digest(paths.read(source, item["path"])) == item["sha256"], "snapshot-modified-before-build")
    host = ("windows" if os.name == "nt" else "linux") + "-" + ("x86_64" if platform.machine().lower() == "amd64" else platform.machine())
    recipe = descriptor["build"]
    require(host in recipe["hostTargets"], "guest-compiler-host-unsupported-select-explicit-build-alternative")
    output = source / recipe["outputRoot"]
    require(not output.exists(), "stale-build-output-rejected")
    working = source / recipe["workingDirectory"]
    with paths.directory(working), ExitStack() as stack:
        tools = {}
        for tool in recipe["tools"]:
            stack.enter_context(paths.opened(tool_root, tool["path"]))
            require(digest(paths.read(tool_root, tool["path"], 256 * 1024 * 1024)) == tool["sha256"], "guest-tool-digest-mismatch")
            tools[tool["name"]] = tool_root / tool["path"]
        environment = process.environment(source)
        environment["PATH"] = os.pathsep.join(sorted({str(path.parent) for path in tools.values()})) + os.pathsep + os.defpath
        # No inherited compiler wrappers, production keys or developer HOME.
        environment.update({"CARGO_HOME": str(source / "build-cache/cargo"), "CARGO_TARGET_DIR": str(output / "cargo"),
                            "GOCACHE": str(source / "build-cache/go"), "GOMODCACHE": str(source / "build-cache/modules"),
                            "NPM_CONFIG_CACHE": str(source / "build-cache/npm"), "DOTNET_CLI_HOME": str(source / "build-cache/dotnet")})
        command = [str(tools[recipe["argv"][0]]), *recipe["argv"][1:]]
        result = process.run(command, working, env=environment, timeout=recipe["timeoutSeconds"],
                             maximum=recipe["maximumOutputBytes"])
    observed_diagnostics = diagnostics.collect(result.stdout, result.stderr, source, working,
                                               {item["path"] for item in record["files"]})
    state.atomic(root, "build-diagnostics.json", {"source": record["identity"], "diagnostics": observed_diagnostics})
    if result.returncode != 0:
        raise DevError("guest-build-failed-last-deployment-retained", diagnostics=observed_diagnostics)
    after, _content = snapshot.observe(source, descriptor["inputRoots"], tuple(descriptor["exclude"]))
    require(after["identity"] == record["identity"], "source-or-generated-bindings-changed-during-build")
    artifacts = descriptor["artifacts"]
    component = paths.read(source, artifacts["component"], 64 * 1024 * 1024)
    require(component[:8] == b"\0asm\x0d\0\x01\0", "build-output-is-not-component-model")
    capsule = decode(paths.read(source, artifacts["capsule"], MAX_DOCUMENT))
    require(capsule.get("component", {}).get("digest") == digest(component), "built-component-digest-mismatch")
    checked = process.run([str(cli), "--output", "json", "validate", "capsule", str(source / artifacts["capsule"])], source)
    require(checked.returncode == 0, "built-capsule-validation-failed")
    identities = {name: digest(paths.read(source, file, 64 * 1024 * 1024)) for name, file in artifacts.items()
                  if name not in {"packageRoot"}}
    receipt = {"schemaVersion": "latent.dev.build.v1", "source": record["identity"], "recipe": trusted,
               "host": host, "target": "wasm-component", "hostAbi": HOST_ABI, "artifacts": identities,
               "tools": recipe["tools"], "template": descriptor["template"], "authority": "observed-local-build",
               "diagnostics": observed_diagnostics}
    paths.write_new(source / "build-receipt.json", encode(receipt))
    state.atomic(root, "last-build.json", {"sourceDirectory": str(source), "receipt": receipt})
    return receipt
