"""Standalone Windows/Linux developer frontend; no operator CLI dependency."""
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import platform
import sys
import time

from . import backend, bundle, paths, project, protocol, snapshot, state, wsl
from .common import DevError, MAX_DEPLOY_SECONDS, MAX_START_SECONDS, decode, digest, encode, identifier, members, require


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="latent-dev", description="Explicit, bounded LSF application development")
    result.add_argument("--state-root", type=Path, help="private controller state outside project sources")
    result.add_argument("--editor-diagnostics", action="store_true", help="also print mapped compiler locations to stderr")
    commands = result.add_subparsers(dest="group", required=True)
    dev = commands.add_parser("dev").add_subparsers(dest="command", required=True)
    doctor = dev.add_parser("doctor", help="read-only prerequisite observation; executes no project recipe")
    doctor.add_argument("--workspace", help="inspect the selected node identity, filesystem and actual profile")
    editor = dev.add_parser("editor", help="write explicit VS Code process tasks; existing tasks are preserved")
    editor.add_argument("--workspace", required=True)
    editor.add_argument("--project", type=Path, required=True)
    editor.add_argument("--frontend", type=Path, required=True, help="absolute path to the authenticated standalone frontend")
    editor.add_argument("--tool-root", help="explicit Linux guest tools; defaults to the installed workspace selection")
    container = dev.add_parser("devcontainer", help="write opt-in container files from an authenticated Linux frontend bundle")
    container.add_argument("--project", type=Path, required=True)
    container.add_argument("--bundle", required=True)
    container.add_argument("--consent-files", action="store_true", help="write reviewed files; never build or start a container")
    configure = dev.add_parser("connect", help="select a separately provisioned owned backend")
    configure.add_argument("--workspace", required=True)
    configure.add_argument("--backend-config", type=Path, required=True)
    trust = dev.add_parser("trust", help="explicitly trust the selected project's current build recipe")
    trust.add_argument("--workspace", required=True)
    trust.add_argument("--project", type=Path, required=True)
    init = dev.add_parser("init", help="materialize an authenticated language-owned template")
    init.add_argument("destination", type=Path)
    init.add_argument("--bundle", required=True)
    init.add_argument("--template", required=True)
    init.add_argument("--template-sha256", required=True)
    verify = dev.add_parser("acquire", help="verify a preprovisioned offline developer bundle into the private cache")
    for option in ("bundle-directory", "publisher-policy", "trusted-root", "verifier"):
        verify.add_argument("--" + option, type=Path, required=True)
    verify.add_argument("--verifier-sha256", required=True)
    verify.add_argument("--version", required=True)
    verify.add_argument("--target", choices=sorted(bundle.TARGETS), required=True)
    verify.add_argument("--allow-candidate", action="store_true")
    provision = dev.add_parser("provision", help="import only a verified tool-owned WSL2 image")
    provision.add_argument("--bundle", required=True)
    provision.add_argument("--consent-provision", action="store_true")
    attach = dev.add_parser("wsl-workspace", help="create an isolated Linux user in the managed WSL distro")
    attach.add_argument("--workspace", required=True)
    attach.add_argument("--helper-sha256", required=True)
    dev.add_parser("wsl-status", help="observe the exact owned WSL registration and workspace states")
    for name in ("wsl-recover", "wsl-purge"):
        command = dev.add_parser(name)
        command.add_argument("--confirm-distribution", required=True)
    for name in ("install", "install-tools", "up", "status", "logs", "down", "purge", "build", "build-status", "deploy", "recover", "invoke", "test", "prepare-test"):
        command = dev.add_parser(name)
        command.add_argument("--workspace", required=True)
        if name == "prepare-test":
            command.add_argument("--consent-test-fixtures", action="store_true")
            command.add_argument("--fixtures", type=Path, help="explicit reviewed node fixture configuration")
            command.add_argument("--admission", choices=("trusted-local", "signed-fixture"), required=True)
            command.add_argument("--tool-root", help="Linux pinned tool inventory containing the reviewed test signer")
        if name == "install":
            command.add_argument("--runtime-inputs", type=Path, required=True,
                                 help="explicit guest-side installer inputs and profile, with consent")
        if name == "install-tools":
            command.add_argument("--tool-inputs", type=Path, required=True,
                                 help="offline compiler bundle and independent publisher/verifier inputs, with consent")
        if name in {"build", "up"}:
            command.add_argument("--project", type=Path)
            command.add_argument("--tool-root", help="verified guest tool inventory directory")
        if name == "up":
            command.add_argument("--watch", action="store_true")
            command.add_argument("--test-select", action="append", default=[], help="focused post-deploy cases in a test- workspace")
        if name == "purge":
            command.add_argument("--confirm-workspace", required=True)
        if name == "invoke":
            for field in ("service", "contract", "function"):
                command.add_argument("--" + field, required=True)
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--media-type", default="application/vnd.latent.wit-values.v1+json")
        if name == "test":
            command.add_argument("--environment", choices=("node", "portable"), required=True)
            command.add_argument("--select", action="append", default=[])
            command.add_argument("--project", type=Path)
            command.add_argument("--artifacts", type=Path)
            command.add_argument("--portable-bundle")
            command.add_argument("--controlled-development", action="store_true")
    return result


def default_root() -> Path:
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "LatentDev"
    return Path.home() / ".latent-dev"


def _root(path: Path | None, *, create: bool = True) -> Path:
    selected = (path or default_root()).absolute()
    if create and not selected.exists():
        paths.new_directory(selected)
    paths.private_root(selected)
    return selected


def _backend(root: Path, name: str):
    workspace = state.workspace(root, name)
    config = state.load(workspace, "backend.json")
    return workspace, backend.Backend(config, name, workspace)


def _build(workspace: Path, connection, source: Path, tool_root: str, *, editor_diagnostics: bool = False,
           selected: tuple[str, str] | None = None) -> dict:
    from .build_client import run
    return run(workspace, connection, source, tool_root, editor_diagnostics=editor_diagnostics, selected=selected)


def watch(workspace: Path, connection, source: Path, tool_root: str, *, editor_diagnostics: bool = False,
          check_session=lambda: None, test_selection=None) -> dict:
    from .watch import run
    return run(workspace, connection, source, tool_root, build=_build, emit=emit,
               editor_diagnostics=editor_diagnostics, check_session=check_session, test_selection=test_selection)


def foreground_up(args, workspace: Path, connection) -> dict:
    from tools.build_process_signals import owned_cancellation
    from .foreground import lease
    require(not (workspace / "purged.json").exists(), "workspace-purged-create-new-workspace")
    if args.watch:
        require(args.project is not None, "watch-project-required")
        if args.tool_root is None:
            from .tool_install import selected_root
            selected_root(workspace, project.load(args.project.absolute())[0])
        require(not args.test_select or args.workspace.startswith("test-"), "focused-watch-tests-require-test-workspace")
    else:
        require(not getattr(args, "test_select", []), "test-selection-requires-watch")
    with state.lock(workspace, "foreground.lock"), owned_cancellation() as cancellation, lease(connection) as check:
        start_dispatched = False
        try:
            with state.lock(workspace):
                start_dispatched = True
                ready = connection.call("up", {}, timeout=MAX_START_SECONDS + 15)
            emit({"event": "ready", "workspace": args.workspace, "result": ready})
            if args.watch:
                return watch(workspace, connection, args.project, args.tool_root,
                             editor_diagnostics=args.editor_diagnostics, check_session=check, test_selection=args.test_select)
            while True:
                cancellation.check()
                check()
                observed = connection.call("status", {})
                if observed.get("state") != "ready":
                    return observed
                time.sleep(2)
        finally:
            if start_dispatched:
                with cancellation.defer():
                    stopped = connection.call("down", {})
                    emit({"event": "foreground-stopped", "workspace": args.workspace, "cleanup": stopped})


def dispatch(args) -> dict:
    if args.command == "doctor" and not args.workspace:
        if os.name == "nt":
            return wsl.doctor()
        return {"host": sys.platform, "architecture": platform.machine(), "nodeReadiness": "not-checked"}
    root = _root(args.state_root)
    if args.command == "devcontainer":
        from .devcontainer import generate
        require(len(args.bundle) == 64 and all(c in "0123456789abcdef" for c in args.bundle), "bundle-id-required")
        return generate(args.project.absolute(), root / "bundles" / args.bundle, consent=args.consent_files)
    if args.command == "editor":
        from .editor import generate
        return generate(args.project.absolute(), args.frontend.absolute(), root, args.workspace, args.tool_root)
    if args.command == "wsl-status":
        return wsl.status(root)
    if args.command == "wsl-recover":
        return wsl.recover(root, args.confirm_distribution)
    if args.command == "wsl-purge":
        return wsl.purge(root, args.confirm_distribution)
    if args.command == "test" and args.environment == "portable":
        from . import portable
        return portable.run(root, args)
    if args.command == "acquire":
        selected = bundle.authenticate(args.bundle_directory.absolute(), args.publisher_policy.absolute(),
            args.trusted_root.absolute(), args.verifier.absolute(), args.verifier_sha256,
            target=args.target, version=args.version, allow_candidate=args.allow_candidate)
        cache = root / "bundles"
        if not cache.exists():
            paths.new_directory(cache)
        name = selected["archive"]["sha256"][7:]
        with state.lock(root, "bundle.lock"):
            destination = cache / name
            if destination.exists():
                bundle.verify_cache(destination, selected)
            else:
                require(sum(1 for _ in cache.iterdir()) < 8, "verified-cache-full-explicit-removal-required")
                bundle.extract(args.bundle_directory.absolute(), selected, destination)
        return {"bundle": name, "target": selected["target"], "sourceCommit": selected["sourceCommit"], "purpose": "candidate"}
    if args.command in {"provision", "init"}:
        require(len(args.bundle) == 64 and all(c in "0123456789abcdef" for c in args.bundle), "bundle-id-required")
        cache = root / "bundles" / args.bundle
        selected = bundle.cached(cache)
        require(selected["archive"]["sha256"] == "sha256:" + args.bundle, "verified-bundle-cache-identity")
        if args.command == "provision":
            require(selected["target"] == "linux-x86_64-wsl-rootfs", "verified-wsl-image-required")
            entry = next((item for item in selected["files"] if item["path"] == "rootfs.tar"), None)
            require(entry is not None, "verified-wsl-rootfs-missing")
            inventory = next((item for item in selected["files"] if item["path"] == "rootfs-inventory.json"), None)
            require(inventory is not None, "verified-wsl-inventory-missing")
            raw = paths.read(cache, inventory["path"])
            require(digest(raw) == inventory["sha256"], "verified-wsl-inventory-changed")
            return wsl.provision(root, cache / "rootfs.tar", entry["sha256"], decode(raw)["helperSha256"],
                                 consent=args.consent_provision)
        parts = paths.relative(args.template).split("/")
        require(len(parts) in {1, 2}, "language-template-path")
        for part in parts:
            identifier(part)
        if len(parts) == 2:
            require(parts[0] in project.LANGUAGES, "language-template-owner")
        template = cache / "templates" / args.template
        name = "templates/" + args.template + "/template.json"
        entry = next((item for item in selected["files"] if item["path"] == name), None)
        require(entry is not None, "authenticated-template-manifest-required")
        raw = paths.read(template, "template.json")
        require((digest(raw), len(raw)) == (entry["sha256"], entry["size"]), "authenticated-template-manifest-changed")
        manifest = decode(raw)
        require(len(parts) == 1 or manifest["project"]["language"] == parts[0], "language-template-owner")
        return project.scaffold(template, args.destination.absolute(), manifest, args.template_sha256)
    if args.command == "wsl-workspace":
        workspace = state.workspace(root, args.workspace, create=True)
        with state.lock(workspace):
            config = wsl.workspace(root, args.workspace, args.helper_sha256)
            if (workspace / "backend.json").exists():
                require(state.load(workspace, "backend.json") == config, "backend-already-selected-no-implicit-migration")
            else:
                state.atomic(workspace, "backend.json", config)
        return {"workspace": args.workspace, "backend": "wsl2", "user": config["user"]}
    if args.command == "connect":
        config = backend.validate(decode(paths.read(args.backend_config.absolute().parent, args.backend_config.name)))
        workspace = state.workspace(root, args.workspace, create=True)
        with state.lock(workspace):
            require(not (workspace / "backend.json").exists(), "backend-already-selected-no-implicit-migration")
            connection = backend.Backend(config, args.workspace, workspace)
            protocol.negotiate(connection.call("hello", {}))
            state.atomic(workspace, "backend.json", config)
        return {"workspace": args.workspace, "backend": config["kind"]}
    if args.command == "purge" and (root / "wsl.json").exists():
        record = wsl._record(root)
        pending = record["workspaces"].get(args.workspace)
        if pending and pending["state"] in {"creating", "removing"}:
            require(args.confirm_workspace == args.workspace, "confirm-exact-workspace-required")
            workspace = state.workspace(root, args.workspace)
            with state.lock(workspace):
                wsl.remove_workspace(root, args.workspace)
                result = {"workspace": args.workspace, "state": "purged", "sourceTreeRetained": True}
                state.atomic(workspace, "purged.json", result)
            return result
    workspace, connection = _backend(root, args.workspace)
    if args.command == "up":
        return foreground_up(args, workspace, connection)
    if args.command in {"down", "status", "logs", "build-status"} and not (workspace / "purged.json").exists():
        return connection.call(args.command, {})
    with state.lock(workspace):
        if (workspace / "purged.json").exists():
            require(args.command in {"purge", "status"}, "workspace-purged-create-new-workspace")
            if args.command == "purge":
                require(args.confirm_workspace == args.workspace, "confirm-exact-workspace-required")
            return state.load(workspace, "purged.json")
        if args.command == "trust":
            descriptor, _identity = project.load(args.project.absolute())
            state.atomic(workspace, "trust.json", {"project": str(args.project.absolute()), "recipe": project.trust_identity(descriptor)})
            return {"workspace": args.workspace, "trustedRecipe": project.trust_identity(descriptor)}
        if args.command == "install":
            inputs = decode(paths.read(args.runtime_inputs.absolute().parent, args.runtime_inputs.name))
            if "schemaVersion" in inputs:
                from .assets import install_inputs
                inputs = install_inputs(connection, inputs)
            return connection.call("install", inputs, timeout=180)
        if args.command == "install-tools":
            from .tool_install import inputs as tool_inputs
            return tool_inputs(workspace, connection, decode(paths.read(args.tool_inputs.absolute().parent, args.tool_inputs.name)))
        if args.command == "build":
            return _build(workspace, connection, args.project, args.tool_root, editor_diagnostics=args.editor_diagnostics)
        if args.command == "purge":
            require(args.confirm_workspace == args.workspace, "confirm-exact-workspace-required")
            result = connection.call("purge", {"confirmWorkspace": args.confirm_workspace})
            if connection.config["kind"] == "wsl2":
                result["linuxUser"] = wsl.remove_workspace(root, args.workspace)
            state.atomic(workspace, "purged.json", result)
            return result
        if args.command == "invoke":
            return connection.call("invoke", {"service": args.service, "contract": args.contract, "function": args.function,
                "mediaType": args.media_type, "input": base64.b64encode(paths.read(args.input.absolute().parent, args.input.name, 1048576)).decode()})
        if args.command == "test":
            return connection.call("test", {"environment": args.environment, "selection": args.select}, timeout=315)
        if args.command == "deploy":
            return connection.call("deploy", {}, timeout=MAX_DEPLOY_SECONDS + 15)
        if args.command == "prepare-test":
            require(args.workspace.startswith("test-") and args.consent_test_fixtures,
                    "explicit-disposable-test-fixture-consent-required")
            fixtures = {}
            if args.fixtures:
                from .node_fixtures import validate
                path = args.fixtures.absolute()
                fixtures = {"fixtures": validate(decode(paths.read(path.parent, path.name, 256 * 1024), 256 * 1024))}
            return connection.call("prepare-test", {"consent": args.consent_test_fixtures,
                "admission": args.admission, **({"toolRoot": args.tool_root} if args.tool_root else {}), **fixtures},
                timeout=1050 if "localService" in fixtures.get("fixtures", {}) else 90)
        return connection.call(args.command, {})


def emit(result: dict) -> None:
    sys.stdout.buffer.write(encode({"schemaVersion": "latent.dev.result.v1", **result}))
    sys.stdout.buffer.flush()


def main() -> int:
    args = parser().parse_args()
    try:
        result = dispatch(args)
        if result.get("passed") is False:
            emit({"code": "required-tests-failed", "result": result})
            return 3
        emit({"code": "success", "result": result})
        return 0
    except DevError as error:
        emit({"code": error.code, "uncertain": error.uncertain, "diagnostics": error.diagnostics})
        return 5 if error.uncertain else 2
    except KeyboardInterrupt:
        emit({"code": "interrupted-inspect-workspace-status", "uncertain": True})
        return 130
    except (OSError, ValueError, KeyError, TypeError):
        emit({"code": "invalid-or-unavailable-input-inspect-doctor", "uncertain": False})
        return 2
