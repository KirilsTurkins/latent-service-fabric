#!/usr/bin/env python3
"""Inspect and select finite listener-free server routes using a scoped CLI."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import server_routes, server_source
from tools.dev_workflow import paths, state
from tools.dev_workflow.client import Client
from tools.dev_workflow.common import DevError, digest, encode
from tools.rust_capsule_project import read_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True, help="Existing maintained latent CLI")
    parser.add_argument("--config", type=Path, required=True, help="Explicit protected operator client profile")
    parser.add_argument("--state", type=Path, required=True, help="Private directory for original-operation receipts")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--timeout", type=int, choices=range(1, 301), default=120, metavar="1..300")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply"):
        command = commands.add_parser(name)
        command.add_argument("--declaration", type=Path, required=True)
        command.add_argument("--component", type=Path, required=True)
        command.add_argument("--source-inputs", type=Path, required=True)
        command.add_argument("--profile", type=Path, required=True)
        command.add_argument("--mounts", type=Path, required=True)
    for name in ("remove", "rollback"):
        commands.add_parser(name).add_argument("names", nargs="+")
    commands.add_parser("recover")
    commands.add_parser("inspect")
    args = parser.parse_args()
    try:
        root = paths.absolute(args.state)
        if not root.exists():
            paths.new_directory(root)
        paths.private_root(root)
        owner = {"tenant": args.tenant, "route": args.route,
                 "clientConfigDigest": digest(read_file(args.config, 262144))}
        cli = Client(args.binary.resolve(strict=True), args.config.resolve(strict=True), root,
                     deadline=time.monotonic() + args.timeout)
        routes = server_routes.Routes(root, cli, owner)
        with state.lock(root, "server-routes.lock"):
            if args.command in {"plan", "apply"}:
                component_digest = digest(read_file(args.component, 64 * 1024 * 1024))
                source_digest = digest(read_file(args.source_inputs, 4 * 1024 * 1024))
                profile_raw = read_file(args.profile, 65536)
                server_source.profile(profile_raw)
                # Validate stale build inputs before contacting the catalog.
                raw = read_file(args.declaration, server_source.MAX_BYTES)
                declaration = server_source.validate(raw, component_digest=component_digest,
                    source_digest=source_digest, profile_digest=digest(profile_raw))
                configuration = read_file(args.mounts, 65536)
                server_source.mounts(configuration, declaration)
                selected = server_routes.observed_pin(cli, args.tenant, args.route, component_digest)
                manifests = server_routes.plan(raw, configuration, selected,
                    source_digest=source_digest, profile_digest=digest(profile_raw))
                result = ({"schemaVersion": server_routes.SCHEMA, "declaration": declaration["identity"],
                           "mountsDigest": digest(configuration), "pin": selected, "triggers": manifests,
                           "executionPermission": False, "atomicMultiRoutePublication": False}
                          if args.command == "plan" else routes.apply(manifests))
            elif args.command == "remove":
                result = routes.remove(args.names)
            elif args.command == "rollback":
                result = routes.rollback(args.names)
            elif args.command == "recover":
                result = routes.recover()
            else:
                result = routes.inspect()
        sys.stdout.buffer.write(encode(result))
        return 0
    except DevError as error:
        sys.stderr.buffer.write(encode({"schemaVersion": server_routes.SCHEMA, "error": error.code,
            "outcomeKnown": not error.uncertain, "executionPermission": False}))
        return 4 if error.uncertain else 2
    except (ValueError, OSError, RuntimeError):
        # No paths, credentials, arbitrary dependency exceptions or server error
        # messages in diagnostics. A retained pending operation stays recoverable.
        sys.stderr.buffer.write(encode({"schemaVersion": server_routes.SCHEMA,
            "error": "server-route-command-failed-inspect-original-operation", "outcomeKnown": False,
            "executionPermission": False}))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
