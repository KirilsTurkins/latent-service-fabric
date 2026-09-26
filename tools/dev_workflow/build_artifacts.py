"""Package compiled bytes with the installed operator, preserving exact identities."""
from pathlib import Path
import time

from . import paths, process
from .common import MAX_DOCUMENT, decode, digest, require, sha


def invoke(cli: Path, source: Path, arguments: list[str], deadline: float, check) -> dict:
    remaining = deadline - time.monotonic()
    require(remaining > 0, "build-deadline-exceeded")
    result = process.run([str(cli), "--output", "json", *arguments], source,
                         timeout=remaining, check=check)
    require(result.returncode == 0, "built-artifact-validation-or-packaging-failed")
    value = decode(result.stdout)
    require(value.get("schemaVersion") == "latent.cli.result.v1" and value.get("category") == "success"
            and value.get("outcomeKnown") is True and isinstance(value.get("data"), dict), "packager-response-invalid")
    return value["data"]


def identities(source: Path, artifacts: dict) -> dict:
    return {name: paths.digest_file(source, file, 64 * 1024 * 1024)[0]
            for name, file in artifacts.items() if name != "packageRoot"}


def package(cli: Path, source: Path, artifacts: dict, deadline: float, check, *, cached: bool) -> dict:
    component = paths.read(source, artifacts["component"], 64 * 1024 * 1024)
    require(component[:8] == b"\0asm\x0d\0\x01\0", "build-output-is-not-component-model")
    capsule = decode(paths.read(source, artifacts["capsule"], MAX_DOCUMENT))
    require(capsule.get("component", {}).get("digest") == digest(component), "built-component-digest-mismatch")
    invoke(cli, source, ["validate", "capsule", str(source / artifacts["capsule"])], deadline, check)
    destination = source / artifacts["packageRoot"]
    if not cached:
        require(not destination.exists(), "compiler-must-not-assemble-package")
        manifest = source / artifacts["packageSource"]
        invoke(cli, source, ["package", "build", "--source", str(manifest), "--input-root", str(manifest.parent),
                            "--output-dir", str(destination)], deadline, check)
    result = invoke(cli, source, ["package", "inspect", str(destination)], deadline, check)
    sha(result.get("packageDigest"))
    require(result.get("componentDigest") == digest(component) and result.get("trustEvaluated") is False
            and result.get("executionAuthorized") is False, "assembled-package-identity-mismatch")
    return result


def verify_receipt(source: Path, descriptor: dict, receipt: dict) -> None:
    require(identities(source, descriptor["artifacts"]) == receipt["artifacts"], "built-artifact-modified-before-use")
