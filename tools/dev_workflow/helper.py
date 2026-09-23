"""Linux side of the developer protocol, shipped inside the verified helper zip."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import pwd
import re
import sys

from . import build, paths, project, protocol, snapshot, state
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


def client(root: Path) -> tuple[Client, Journal]:
    layout, current = installation(root)
    config = decode(paths.read(layout.node.parent, layout.node.name))
    return Client(current / "bin/latent", layout.client, root), Journal(root, config["nodeId"], "examples")


def install(root: Path, arguments: dict) -> dict:
    from tools.native_runtime import lifecycle, verify
    from tools.native_runtime.layout import Layout
    members(arguments, {"releaseDirectory", "version", "publisherPolicy", "trustedRoot", "verifier",
                        "profile", "allowCandidate", "consent", "port"}, {"trustPolicy"})
    require(arguments["consent"] is True, "explicit-runtime-install-consent-required")
    require(arguments["profile"] in {"local-experimental-v1", "external-capsule-v1"}, "explicit-node-profile-required")
    trust = verify.PublisherTrust(Path(arguments["publisherPolicy"]), Path(arguments["trustedRoot"]),
                                  Path(arguments["verifier"]), arguments["allowCandidate"])
    with verify.release(Path(arguments["releaseDirectory"]), arguments["version"], trust) as release:
        return lifecycle.install(Layout.local(root / "runtime"), release, profile=arguments["profile"],
            policy=Path(arguments["trustPolicy"]) if arguments.get("trustPolicy") else None,
            port=arguments["port"], start=False, enable=False, upgrade=False, resume=False,
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


def deploy(root: Path) -> dict:
    saved = state.load(root, "project.json")
    source, descriptor = Path(saved["source"]), saved["descriptor"]
    receipt = decode(paths.read(source, "build-receipt.json"))
    require(receipt["source"] == saved["snapshot"] and receipt["recipe"] == saved["trust"], "stale-build-receipt")
    cli, journal = client(root)
    artifacts = descriptor["artifacts"]
    for name in ("component", "capsule", "contracts", "deployment"):
        require(digest(paths.read(source, artifacts[name], 64 * 1024 * 1024)) == receipt["artifacts"][name],
                "built-artifact-modified-before-deploy")
    node = decode(paths.read(root / "runtime/config", "node.json"))
    require(descriptor["tenant"] == "examples", "project-tenant-does-not-match-workspace-credential")
    if node["supplyChain"]["mode"] == "trusted-local":
        published = journal.execute("release", {"source": saved["snapshot"], "expectedGeneration": "0"},
            lambda operation: cli.call("release", "publish", "--manifest", source / artifacts["capsule"],
                "--component", source / artifacts["component"], "--contracts", source / artifacts["contracts"],
                "--operation-id", operation, "--expected-generation", "0"))
    else:
        require("packageRoot" in artifacts and "evidence" in artifacts, "signed-package-handoff-required")
        published = journal.execute("release", {"source": saved["snapshot"], "expectedGeneration": "0"},
            lambda operation: cli.call("release", "publish-package", source / artifacts["packageRoot"],
                "--evidence", source / artifacts["evidence"], "--operation-id", operation, "--expected-generation", "0"))
    admitted = successful(published)
    publication = admitted["release"]["publication"]["id"]
    deployment = decode(paths.read(source, artifacts["deployment"]))
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
        "expectedGeneration": generation, "expectedStateVersion": version}, lambda operation:
        cli.call("deployment", "apply", root / "selected-deployment.json", "--expected-generation", generation,
                 "--operation-id", operation, "--expected-state-version", version))
    result = successful(applied)
    retained = {"source": saved["snapshot"], "publication": publication,
                "generation": result["deployment"]["generation"], "deployment": name}
    state.atomic(root, "last-deployment.json", retained)
    return retained


def dispatch(request: dict) -> dict:
    operation, arguments = request["operation"], request["arguments"]
    if operation == "hello":
        members(arguments, set())
        return protocol.hello()
    root = state.workspace(root_directory(), request["workspace"], create=operation == "install")
    if operation in {"status", "logs", "down", "up"}:
        from . import service
        members(arguments, set())
        if operation == "up":
            with state.lock(root):
                return service.start(root, Path(sys.argv[0]).absolute())
        try:
            return service.request(root, operation)
        except (FileNotFoundError, ConnectionRefusedError):
            prior = state.load(root, "lifecycle.json") if (root / "lifecycle.json").exists() else {"state": "stopped"}
            require(prior["state"] == "stopped", "supervisor-disconnected-cleanup-unknown")
            return {"state": "stopped", "dataRetained": True}
    with state.lock(root):
        if operation == "install":
            return install(root, arguments)
        if operation == "doctor":
            from tools.native_runtime import checks
            members(arguments, set())
            return checks.preflight(installation(root)[0])
        if operation == "snapshot":
            return sync(root, arguments)
        if operation == "build":
            members(arguments, {"toolRoot"})
            saved = state.load(root, "project.json")
            return build.execute(root, Path(saved["source"]), saved["descriptor"], Path(arguments["toolRoot"]),
                                 trusted=saved["trust"], cli=installation(root)[1] / "bin/latent")
        if operation == "deploy":
            members(arguments, set())
            return deploy(root)
        if operation == "recover":
            members(arguments, set())
            cli, journal = client(root)
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
    from . import scenarios
    members(arguments, {"environment", "selection"})
    require(arguments["environment"] == "node", "linux-test-cannot-fallback-to-portable")
    # A test workspace is deliberately named at creation, rather than silently
    # republishing over the user's current development deployment.
    require(root.name.startswith("test-"), "explicit-disposable-test-workspace-required")
    saved = state.load(root, "project.json")
    source, descriptor = Path(saved["source"]), saved["descriptor"]
    cases = []
    for name in descriptor["scenarios"]:
        document = scenarios.validate(decode(paths.read(source, name)), "node")
        cases.extend(document["scenarios"])
    cli, journal = client(root)
    def invoke(case, raw):
        require(case["service"] == descriptor["service"], "scenario-service-outside-test-project")
        path = root / "test-input.json"
        if path.exists():
            paths.read(root, path.name, 1048576)
            path.unlink()
        paths.write_new(path, raw)
        return journal.execute("invoke", {"case": case["id"], "inputSha256": digest(raw)}, lambda activation:
            cli.call("invoke", "--service", case["service"], "--contract", case["contract"], "--function", case["function"],
                "--input", path, "--media-type", case["mediaType"], "--activation-id", activation,
                "--rpc-timeout-ms", str(case["timeoutMillis"])))
    layout, current = installation(root)
    import platform
    node = decode(paths.read(layout.node.parent, layout.node.name))
    build_receipt = state.load(root, "last-build.json")["receipt"]
    report = scenarios.run({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}, source, "node",
        arguments["selection"], invoke, {"source": build_receipt["source"], "artifacts": build_receipt["artifacts"],
        "runtime": decode(paths.read(current, "release-source.json")), "node": node["nodeId"],
        "profile": node["securityProfile"], "os": "linux", "architecture": platform.machine(), "kernel": platform.release()},
        supported={"context", "log", "clock", "fresh-state", "fuel", "memory"})
    report["cleanup"] = "invocation-results-received-node-retained"
    state.atomic(root, "test-report.json", report)
    return report


def create_user() -> int:
    from . import process
    require(os.geteuid() == 0, "wsl-user-provision-requires-owned-image-root")
    value = decode(sys.stdin.buffer.read(8193), 8192)
    members(value, {"workspace", "user", "helperSha256"})
    require(re.fullmatch(r"lsfd-[a-f0-9]{12}", value["user"]), "invalid-owned-user")
    require(digest(paths.read(Path(sys.argv[0]).parent, Path(sys.argv[0]).name)) == value["helperSha256"], "helper-image-mismatch")
    try:
        pwd.getpwnam(value["user"])
    except KeyError:
        pass
    else:
        raise DevError("refuse-adopting-existing-linux-user")
    result = process.run(["/usr/sbin/useradd", "--create-home", "--user-group", "--shell", "/usr/sbin/nologin",
                          "--home-dir", "/home/" + value["user"], value["user"]], Path("/"), timeout=10)
    require(result.returncode == 0, "owned-linux-user-creation-failed")
    user = pwd.getpwnam(value["user"])
    Path(user.pw_dir).chmod(0o700)
    print(encode({"user": value["user"], "uid": user.pw_uid}).decode(), end="")
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "supervise":
        from .service import supervise
        return supervise(Path(sys.argv[2]))
    if len(sys.argv) == 2 and sys.argv[1] == "create-user":
        return create_user()
    require(len(sys.argv) == 2 and sys.argv[1] == "rpc", "helper-protocol-required")
    request = protocol.validate_request(decode(sys.stdin.buffer.read(MAX_SNAPSHOT * 2 + 1), MAX_SNAPSHOT * 2))
    try:
        result = protocol.response(request, dispatch(request))
    except DevError as error:
        result = protocol.response(request, {}, code=error.code, uncertain=error.uncertain)
    except Exception:
        result = protocol.response(request, {}, code="helper-operation-failed", uncertain=request["operation"] not in
                                   {"hello", "doctor", "status", "logs"})
    sys.stdout.buffer.write(encode(result))
    return 0
