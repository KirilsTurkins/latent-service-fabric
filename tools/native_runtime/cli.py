"""No network, package manager, compiler, container, or implicit service start."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys

from . import checks, files, lifecycle, verify
from .common import InstallError, require
from .configuration import EXTERNAL, LOCAL
from .layout import Layout, node_identity


def location(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--system", action="store_true")
    selection.add_argument("--directory", type=Path)


def release_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--release-directory", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--publisher-policy", type=Path, required=True)
    parser.add_argument("--trusted-root", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, default=Path("/usr/bin/gh"))
    parser.add_argument("--allow-candidate", action="store_true", help="explicit CI/evaluation identity, never a release")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    release_arguments(commands.add_parser("verify", help="authenticate a provisioned offline release"))
    install = commands.add_parser("install", help="stage and validate; start/enable only when explicitly requested")
    location(install)
    release_arguments(install)
    install.add_argument("--profile", choices=(LOCAL, EXTERNAL), required=True)
    install.add_argument("--trust-policy", type=Path)
    install.add_argument("--port", type=int, default=50051)
    install.add_argument("--acknowledge-experimental", action="store_true")
    install.add_argument("--start", action="store_true")
    install.add_argument("--enable", action="store_true")
    install.add_argument("--upgrade", action="store_true")
    install.add_argument("--approve-compiler-sha256")
    install.add_argument("--resume", action="store_true")
    for name in ("preflight", "readiness", "status", "remove"):
        command = commands.add_parser(name)
        location(command)
        if name == "preflight":
            command.add_argument("--candidate-version")
    purge = commands.add_parser("purge", help="separate destructive action after removal")
    location(purge)
    purge.add_argument("--confirm-installation", required=True)
    run = commands.add_parser("run-local", help="replace this process with the foreground non-root node")
    run.add_argument("--directory", type=Path, required=True)
    return result


def dispatch(arguments: argparse.Namespace) -> dict:
    require(sys.platform == "linux", "native-installer-requires-linux")
    if arguments.command in {"verify", "install"}:
        trust = verify.PublisherTrust(arguments.publisher_policy, arguments.trusted_root,
                                      arguments.verifier, arguments.allow_candidate)
    if arguments.command == "verify":
        with verify.release(arguments.release_directory, arguments.version, trust) as release:
            return {"schemaVersion": "latent.native-verification.v1", "publisherIdentitySha256": release.publisher,
                    "version": release.metadata["version"], "sourceCommit": release.metadata["sourceCommit"],
                    "archiveSha256": release.metadata["archive"]["sha256"], "authentication": release.authentication}
    layout = Layout.server() if getattr(arguments, "system", False) else Layout.local(arguments.directory)
    if arguments.command == "install":
        with verify.release(arguments.release_directory, arguments.version, trust) as release:
            return lifecycle.install(layout, release, profile=arguments.profile, policy=arguments.trust_policy,
                                     port=arguments.port, start=arguments.start, enable=arguments.enable,
                                     upgrade=arguments.upgrade, resume=arguments.resume,
                                     acknowledge=arguments.acknowledge_experimental,
                                     approved_compiler=arguments.approve_compiler_sha256)
    if arguments.command == "preflight":
        return checks.preflight(layout, arguments.candidate_version)
    if arguments.command == "readiness":
        return checks.readiness(layout)
    if arguments.command == "run-local":
        node_identity(layout)
        with ExitStack() as stack:
            stack.enter_context(files.lock(layout.prefix / "install.lock"))
            running = stack.enter_context(files.lock(layout.prefix / "run.lock", timeout=0))
            require(not os.path.lexists(layout.transaction), "finish-interrupted-installation-before-running")
            state = lifecycle.read_state(layout)
            require(state is not None and state["status"] == "installed", "installed-runtime-required")
            checks.preflight(layout)
            executable = str(checks.current(layout) / "bin" / "latentd")
            os.set_inheritable(running, True)
            os.chdir(layout.data)
            os.execve(executable, [executable, "serve", "--config", str(layout.node)],
                      {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    if arguments.command == "status":
        node_identity(layout)
        with files.lock(layout.prefix / "install.lock"):
            state = lifecycle.read_state(layout)
            require(state is not None, "installation-state-required")
            return {key: state[key] for key in ("schemaVersion", "installationId", "profile", "status", "currentVersion")}
    return lifecycle.remove(layout, purge=arguments.confirm_installation if arguments.command == "purge" else None)


def main() -> int:
    os.umask(0o077)
    arguments = parser().parse_args()
    try:
        result = dispatch(arguments)
    except InstallError as error:
        print(json.dumps({"schemaVersion": "latent.native-error.v1", "diagnostic": str(error)}), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, RecursionError, EOFError):
        print('{"schemaVersion":"latent.native-error.v1","diagnostic":"native-installation-failed-check-protected-paths-and-local-prerequisites"}', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0
