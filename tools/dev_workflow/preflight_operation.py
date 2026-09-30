"""Read-only preflight on an existing operator or provisioned developer node."""
from __future__ import annotations

from pathlib import Path
import time

from . import paths, preflight
from .client import Client
from .common import require, sha

MAX_SECONDS = 120


def using_client(value: dict, cli: Client, *, directory: Path | None = None) -> dict:
    def observe(component, *, preparation=True):
        target = component["target"]
        arguments = ["--rpc-timeout-ms", "25000", "--tenant", value["tenant"], "route", "target", "--service", target["service"],
                     "--contract", target["contract"], "--function", target["function"],
                     "--route", target["route"], "--revision", target["revision"],
                     "--publication", target["publicationId"]]
        if preparation:
            arguments.extend(("--include-preparation", "--maximum-wait-millis", "20000"))
        return cli.call(*arguments, timeout=30)
    return preflight.run(value, directory=directory, observe=observe)


def standalone(value: dict, binary: Path, expected: str, config: Path, *, directory: Path) -> dict:
    binary, config = paths.absolute(binary), paths.absolute(config)
    sha(expected)
    def verify():
        actual, _ = paths.digest_file(binary.parent, binary.name, 256 * 1024 * 1024)
        require(actual == expected, "preflight-operator-identity-changed")
    verify()
    # Config bytes and their authentication fields belong to the ordinary CLI;
    # they are never copied into the result or a controller journal.
    with paths.opened(config.parent, config.name):
        pass
    cli = Client(binary, config, directory, deadline=time.monotonic() + MAX_SECONDS)
    original = cli.call
    config_digest, _ = paths.digest_file(config.parent, config.name, 1024 * 1024)
    def checked(*arguments, **options):
        verify()
        result = original(*arguments, **options)
        verify()
        current, _ = paths.digest_file(config.parent, config.name, 1024 * 1024)
        require(current == config_digest, "preflight-operator-configuration-changed")
        return result
    cli.call = checked
    return using_client(value, cli, directory=directory)


def packaged(root: Path, value: dict) -> dict:
    from .helper import installation
    layout, current = installation(root)
    cli = Client(current / "bin/latent", layout.client, root,
                 deadline=time.monotonic() + MAX_SECONDS)
    return using_client(value, cli)
