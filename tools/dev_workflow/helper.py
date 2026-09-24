"""Linux side of the developer protocol, shipped inside the verified helper zip."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import pwd
import re
import sys

from . import build, effects, paths, project, protocol, snapshot, state
from .client import Client, successful
from .common import DevError, MAX_SNAPSHOT, decode, digest, encode, members, require
from .journal import Journal


def root_directory() -> Path:
    require(sys.platform == "linux" and os.geteuid() != 0, "unprivileged-linux-helper-required")
    home = Path(pwd.getpwuid(os.geteuid()).pw_dir)
    root = home / ".lsf-dev"
    if not root.exists():
        paths.new_directory(root)
    paths.private_root(root)
    return root


def installation(root: Path):
    from tools.native_runtime.layout import Layout
    from tools.native_runtime import checks
    layout = Layout.local(root / "runtime")
    return layout, checks.current(layout)


def client(root: Path, *, deadline: float | None = None) -> tuple[Client, Journal]:
    layout, current = installation(root)
    config = decode(paths.read(layout.node.parent, layout.node.name))
    return Client(current / "bin/latent", layout.client, root, deadline=deadline), Journal(root, config["nodeId"], "examples",
        settle=lambda operation, result: effects.settle(root, operation, result))


def install(root: Path, arguments: dict) -> dict:
    from tools.native_runtime import lifecycle, verify
    from tools.native_runtime.layout import Layout
    members(arguments, {"releaseDirectory", "version", "publisherPolicy", "trustedRoot", "verifier",
                        "profile", "allowCandidate", "consent", "port"}, {"trustPolicy", "resume"})
    require(arguments["consent"] is True, "explicit-runtime-install-consent-required")
    require(arguments["profile"] in {"local-experimental-v1", "external-capsule-v1"}, "explicit-node-profile-required")
    require(type(arguments.get("resume", False)) is bool, "explicit-installer-resume-required")
    require(Path("/usr/bin/python3").is_file(), "native-installer-system-python-required")
    trust = verify.PublisherTrust(Path(arguments["publisherPolicy"]), Path(arguments["trustedRoot"]),
                                  Path(arguments["verifier"]), arguments["allowCandidate"])
    with verify.release(Path(arguments["releaseDirectory"]), arguments["version"], trust) as release:
        return lifecycle.install(Layout.local(root / "runtime"), release, profile=arguments["profile"],
            policy=Path(arguments["trustPolicy"]) if arguments.get("trustPolicy") else None,
            port=arguments["port"], start=False, enable=False, upgrade=False, resume=arguments.get("resume", False),
            acknowledge=arguments["profile"] == "local-experimental-v1", approved_compiler=None)


def sync(root: Path, arguments: dict) -> dict:
    members(arguments, {"snapshot", "content", "project", "trustedRecipe"})
    descriptor = project.validate(arguments["project"])
    require(arguments["trustedRecipe"] == project.trust_identity(descriptor), "workspace-recipe-trust-required")
    record = arguments["snapshot"]
    snapshot.validate(record)
    require(isinstance(arguments["content"], dict), "snapshot-content-object")
    content = {}
    for name, raw in arguments["content"].items():
        require(isinstance(raw, str) and len(raw) <= 24 * 1024 * 1024, "snapshot-file-transfer-limit")
        try:
            content[name] = base64.b64decode(raw, validate=True)
        except ValueError:
            raise DevError("snapshot-base64-invalid") from None
    snapshots = root / "snapshots"
    if not snapshots.exists():
        paths.new_directory(snapshots)
    destination = snapshots / record["identity"][7:]
    if destination.exists():
        require(decode(paths.read(destination, "snapshot.json")) == record, "partial-or-stale-snapshot")
        for item in record["files"]:
            require(digest(paths.read(destination, item["path"])) == item["sha256"], "retained-snapshot-modified")
    else:
        from .cleanup import prune_snapshots
        prune_snapshots(root, incoming=record["identity"])
        require(sum(1 for _ in snapshots.iterdir()) < 4, "snapshot-retention-full-explicit-clean-required")
        snapshot.materialize(destination, record, content)
    state.atomic(root, "project.json", {"descriptor": descriptor, "trust": arguments["trustedRecipe"],
                                        "source": str(destination), "snapshot": record["identity"]})
    return {"snapshot": record["identity"], "sourceBytes": record["bytes"], "files": len(record["files"])}


def deploy(root: Path, *, test_grants: list | None = None, deadline: float | None = None) -> dict:
    saved = state.load(root, "project.json")
    source, receipt = build.accepted(root, saved)
    descriptor = saved["descriptor"]
    cli, journal = client(root, deadline=deadline)
    artifacts = descriptor["artifacts"]
    from . import build_artifacts, build_cache
    import time
    require(paths.digest_file(cli.binary.parent, cli.binary.name, 268435456)[0] == receipt["packager"],
            "runtime-packager-changed-rebuild-required")
    require(build_artifacts.package(cli.binary, source, artifacts, min(time.monotonic() + 30, deadline or float("inf")),
            build_cache.monitor(source.parent), cached=True) == receipt["package"], "built-package-modified-before-deploy")
    node = decode(paths.read(root / "runtime/config", "node.json"))
    signing = None
    if (root / "test-signing-receipt.json").exists():
        from .node_test_signing import selected
        signing = selected(root, receipt)
        require(node["supplyChain"] == {"mode": "enforced", "policyFile": str(root / "test-signing/policy.json")},
                "signed-test-profile-changed")
    require(descriptor["tenant"] == "examples", "project-tenant-does-not-match-workspace-credential")
    if journal.read()["pending"] is not None:
        raise DevError("recover-original-operation-before-new-mutation", uncertain=True)
    prior = state.load(root, "last-publication.json") if (root / "last-publication.json").exists() else None
    publication_input = digest(encode({"mode": node["supplyChain"]["mode"],
        "package": signing["packageDigest"] if signing else receipt["package"]["packageDigest"],
        **{name: receipt["artifacts"][name] for name in ("component", "capsule", "contracts")}}))
    release_intent = {"source": saved["snapshot"], "componentDigest": receipt["artifacts"]["component"],
        "expectedGeneration": "0", "attempt": receipt["attempt"], "buildKey": receipt["buildKey"], "publicationInput": publication_input}
    if prior and prior.get("publicationInput") == publication_input:
        publication = prior["publication"]
    elif node["supplyChain"]["mode"] == "trusted-local":
        published = journal.execute("release", release_intent,
            lambda operation: cli.call("release", "publish", "--manifest", source / artifacts["capsule"],
                "--component", source / artifacts["component"], "--contracts", source / artifacts["contracts"],
                "--operation-id", operation, "--expected-generation", "0"))
        publication = successful(published)["release"]["publication"]["id"]
    else:
        require("packageRoot" in artifacts and "evidence" in artifacts, "signed-package-handoff-required")
        package_root = root / "test-signing" / signing["name"] / "package" if signing else source / artifacts["packageRoot"]
        evidence = root / "test-signing" / signing["name"] / "evidence/index.json" if signing else source / artifacts["evidence"]
        published = journal.execute("release", release_intent,
            lambda operation: cli.call("release", "publish-package", package_root,
                "--evidence", evidence, "--operation-id", operation, "--expected-generation", "0"))
        publication = successful(published)["release"]["publication"]["id"]
    deployment = decode(paths.read(source, artifacts["deployment"]))
    if test_grants is not None:
        require(root.name.startswith("test-") and (root / "test-profile.json").exists(), "disposable-test-grants-only")
        deployment["spec"]["grants"] = test_grants
    deployment["spec"]["publication"] = publication
    name = deployment["metadata"]["name"]
    observation = cli.call("deployment", "get", name, "--operation-snapshot")
    require(observation["outcomeKnown"] and observation["category"] in {"success", "not-found"},
            "deployment-snapshot-unavailable")
    observed = observation["data"]
    generation = observed["deployment"]["generation"] if observed["deployment"] else "0"
    version = observed["stateVersion"]
    require(isinstance(version, str) and version.isdecimal(), "deployment-state-version-required")
    # Only the generation owned by the last successful switch may be replaced.
    last = state.load(root, "last-deployment.json") if (root / "last-deployment.json").exists() else None
    require(generation == (last["generation"] if last else "0"), "concurrent-deployment-change-no-overwrite")
    state.atomic(root, "selected-deployment.json", deployment)
    applied = journal.execute("deployment", {"publication": publication, "source": saved["snapshot"],
        "attempt": receipt["attempt"], "buildKey": receipt["buildKey"], "publicationInput": publication_input,
        "componentDigest": receipt["artifacts"]["component"], "deployment": name,
        "expectedGeneration": generation, "expectedStateVersion": version}, lambda operation:
        cli.call("deployment", "apply", root / "selected-deployment.json", "--expected-generation", generation,
                 "--operation-id", operation, "--expected-state-version", version))
    successful(applied)
    return state.load(root, "last-deployment.json")


def dispatch(request: dict) -> dict:
    operation, arguments = request["operation"], request["arguments"]
    if operation == "hello":
        members(arguments, set())
        return protocol.hello()
    root = state.workspace(root_directory(), request["workspace"], create=operation in {"install", "asset-begin", "purge"})
    from . import build_control
    if operation == "build-status":
        members(arguments, set())
        return build_control.status(root)
    if operation == "cancel-build":
        members(arguments, {"buildId", "reason"})
        return build_control.cancel(root, arguments["buildId"], arguments["reason"])
    if operation in {"status", "logs", "down", "up"}:
        from . import service
        members(arguments, set())
        if operation == "up":
            with state.lock(root):
                return service.start(root, Path(sys.argv[0]).absolute())
        if operation == "down":
            build_control.stop(root)
        try:
            result = service.request(root, operation)
        except (FileNotFoundError, ConnectionRefusedError):
            result = service.disconnected(root)
        if operation == "down":
            result["build"] = build_control.wait_stopped(root)
        if operation == "status":
            from .workflow_status import observe
            result["workflow"] = observe(root)
        return result
    with state.lock(root):
        if operation.startswith("asset-"):
            from .assets import receive
            return receive(root, operation, arguments)
        if operation == "install":
            return install(root, arguments)
        if operation == "install-tools":
            from .tool_install import install as install_tools
            return install_tools(root, arguments)
        if operation == "doctor":
            from tools.native_runtime import checks
            members(arguments, set())
            return checks.preflight(installation(root)[0])
        if operation == "snapshot":
            return sync(root, arguments)
        if operation == "build":
            members(arguments, {"toolRoot", "buildId"})
            saved = state.load(root, "project.json")
            with build_control.session(root, arguments["buildId"]) as control:
                return build.execute(root, Path(saved["source"]), saved["descriptor"], Path(arguments["toolRoot"]),
                                     trusted=saved["trust"], cli=installation(root)[1] / "bin/latent", control=control)
        if operation == "deploy":
            members(arguments, set())
            return deploy(root)
        if operation == "prepare-test":
            from .node_test_profile import prepare
            members(arguments, {"consent", "admission"}, {"toolRoot"})
            installation(root)
            descriptor = state.load(root, "project.json")["descriptor"]
            tool_root = arguments.get("toolRoot")
            if arguments["admission"] == "signed-fixture" and not tool_root:
                from .tool_install import selected_root
                tool_root = selected_root(root, descriptor)
            return prepare(root, descriptor, consent=arguments["consent"], admission=arguments["admission"],
                           tool_root=Path(tool_root) if tool_root else None)
        if operation == "recover":
            members(arguments, set())
            cli, journal = client(root)
            if journal.read()["pending"] is None:
                from .workflow_status import observe
                return {"state": "no-pending-operation", "workflow": observe(root)}
            return journal.recover(cli.lookup)
        if operation == "purge":
            from .cleanup import purge
            members(arguments, {"confirmWorkspace"})
            return purge(root, request["workspace"], arguments["confirmWorkspace"])
        if operation == "test":
            return test(root, arguments)
        if operation == "invoke":
            members(arguments, {"service", "contract", "function", "input", "mediaType"})
            require(isinstance(arguments["input"], str) and len(arguments["input"]) <= 1398104, "invoke-input-limit")
            raw = base64.b64decode(arguments["input"], validate=True)
            input_path = root / "invoke-input.json"
            # Payloads are opaque canonical WIT bytes, not a generic JSON value.
            if input_path.exists():
                paths.read(root, "invoke-input.json", 1048576)
                input_path.unlink()
            paths.write_new(input_path, raw)
            cli, journal = client(root)
            return journal.execute("invoke", {"inputSha256": digest(raw), "service": arguments["service"]},
                lambda activation: cli.call("invoke", "--service", arguments["service"], "--contract", arguments["contract"],
                    "--function", arguments["function"], "--media-type", arguments["mediaType"],
                    "--input", input_path, "--activation-id", activation))
        require(False, "operation-not-yet-qualified")


def test(root: Path, arguments: dict) -> dict:
    from .node_scenarios import run
    return run(root, arguments)


def main() -> int:
    from tools.native_runtime.common import InstallError
    if len(sys.argv) >= 2 and sys.argv[1] == "supervise":
        from .service import supervise
        return supervise(Path(sys.argv[2]))
    if len(sys.argv) == 2 and sys.argv[1] in {"create-user", "user-status", "remove-user"}:
        from .guest_users import main as users
        return users(sys.argv[1])
    require(len(sys.argv) == 2 and sys.argv[1] == "rpc", "helper-protocol-required")
    request = protocol.validate_request(decode(sys.stdin.buffer.read(MAX_SNAPSHOT * 2 + 1), MAX_SNAPSHOT * 2))
    try:
        result = protocol.response(request, dispatch(request))
    except DevError as error:
        result = protocol.response(request, {"diagnostics": error.diagnostics} if error.diagnostics else {},
                                   code=error.code, uncertain=error.uncertain)
    except InstallError as error:
        code = str(error)
        # The installer owns fixed diagnostics. Never render arbitrary stderr or
        # dynamic file contents as an error, and preserve interrupted mutation state.
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,100}", code):
            code = "native-installer-input-or-host-check-failed"
        result = protocol.response(request, {}, code=code, uncertain=request["operation"] in {"install", "purge"})
    except Exception:
        result = protocol.response(request, {}, code="helper-operation-failed", uncertain=request["operation"] not in
                                   {"hello", "doctor", "status", "logs"})
    sys.stdout.buffer.write(encode(result))
    return 0
