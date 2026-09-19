"""Lock every selected Go module and generator dependency without running package code."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "sdk" / "go"
LOCK = SDK / "dependencies.lock.json"
MODULE = "latent.dev/sdk/go"
TOOL_MODULES = {
    "google.golang.org/grpc/cmd/protoc-gen-go-grpc": "google.golang.org/grpc/cmd/protoc-gen-go-grpc",
    "google.golang.org/protobuf/cmd/protoc-gen-go": "google.golang.org/protobuf",
}


def go_environment() -> dict[str, str]:
    return dict(os.environ, GOTOOLCHAIN="local", GOWORK="off", GOENV="off",
                GOFLAGS="-mod=readonly", GOPROXY="https://proxy.golang.org",
                GOSUMDB="sum.golang.org", GOPRIVATE="", GONOPROXY="", GONOSUMDB="")


def run_go(arguments: list[str], directory: Path) -> str:
    result = subprocess.run(["go", *arguments], cwd=directory, env=go_environment(),
                            check=True, capture_output=True, text=True, timeout=180)
    if len(result.stdout) > 2 * 1024 * 1024:
        raise ValueError("Go module inventory exceeds its 2 MiB bound")
    return result.stdout


def pinned_version() -> str:
    baseline = tomllib.loads((ROOT / "tools" / "toolchain.toml").read_text(encoding="utf-8"))
    version = baseline["sdk"]["go"]
    if run_go(["env", "GOVERSION"], SDK).strip() != f"go{version}":
        raise ValueError(f"Go dependency generation requires repository-pinned Go {version}")
    return version


def normalized(data: bytes) -> bytes:
    result = data.replace(b"\r\n", b"\n")
    if b"\r" in result:
        raise ValueError("Go manifests must use LF or CRLF line endings")
    return result


def decode_records(output: str) -> list[dict]:
    records = []
    decoder = json.JSONDecoder()
    position = 0
    while position < len(output):
        if output[position].isspace():
            position += 1
            continue
        record, position = decoder.raw_decode(output, position)
        if not isinstance(record, dict) or len(records) == 256:
            raise ValueError("invalid or oversized Go module inventory")
        records.append(record)
    return records


def checksum(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("h1:"):
        raise ValueError("every selected Go module requires both checksums")
    digest = base64.b64decode(value[3:], validate=True)
    if len(digest) != 32 or base64.b64encode(digest).decode("ascii") != value[3:]:
        raise ValueError("noncanonical Go module checksum")
    return value


def make_lock(records: list[dict], manifest: dict, version: str,
              module_data: bytes, sum_data: bytes) -> dict:
    selected = {}
    mains = []
    for record in records:
        if "Replace" in record or "Error" in record:
            raise ValueError("module replacement or unresolved dependency is not supported")
        if record.get("Main"):
            mains.append(record)
            continue
        path = record.get("Path")
        release = record.get("Version")
        if not isinstance(path, str) or not path or path in selected:
            raise ValueError("missing or duplicate selected module path")
        if not isinstance(release, str) or not release.startswith("v"):
            raise ValueError("every selected dependency requires an exact module version")
        selected[path] = {"path": path, "version": release,
                          "sum": checksum(record.get("Sum")),
                          "goModSum": checksum(record.get("GoModSum"))}
    if len(mains) != 1 or mains[0].get("Path") != MODULE or mains[0].get("GoVersion") != version:
        raise ValueError("main module and Go version must match the repository profile")
    if manifest.get("Module", {}).get("Path") != MODULE or manifest.get("Go") != version:
        raise ValueError("unexpected Go module manifest identity")
    if manifest.get("Replace") or manifest.get("Exclude"):
        raise ValueError("dependency replacements and exclusions are unsupported")
    directives = [entry["Path"] for entry in manifest.get("Tool", [])]
    if sorted(directives) != sorted(TOOL_MODULES):
        raise ValueError("generator tool directives do not match the maintained profile")
    for requirement in manifest.get("Require", []):
        if requirement["Path"] not in selected:
            raise ValueError("required module is missing from the selected graph")
    tools = []
    for path, module in sorted(TOOL_MODULES.items()):
        if module not in selected:
            raise ValueError("generator module is missing from the selected graph")
        tools.append({"path": path, "module": module, "version": selected[module]["version"]})
    return {
        "schemaVersion": 1,
        "module": MODULE,
        "goVersion": version,
        "manifestSha256": hashlib.sha256(normalized(module_data)).hexdigest(),
        "sumSha256": hashlib.sha256(normalized(sum_data)).hexdigest(),
        "modules": [selected[path] for path in sorted(selected)],
        "tools": tools,
    }


def resolved_lock() -> dict:
    version = pinned_version()
    module_data = normalized((SDK / "go.mod").read_bytes())
    sum_data = normalized((SDK / "go.sum").read_bytes())
    target = SDK / "target"
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dependency-graph-", dir=target) as directory:
        temporary = Path(directory)
        (temporary / "go.mod").write_bytes(module_data)
        (temporary / "go.sum").write_bytes(sum_data)
        run_go(["mod", "download", "-json", "all"], temporary)
        records = decode_records(run_go(["list", "-m", "-json", "all"], temporary))
        manifest = json.loads(run_go(["mod", "edit", "-json"], temporary))
        if (normalized((temporary / "go.mod").read_bytes()) != module_data or
                normalized((temporary / "go.sum").read_bytes()) != sum_data):
            raise ValueError("incomplete Go checksums: run go mod download all before locking")
    return make_lock(records, manifest, version, module_data, sum_data)


def serialized(document: dict) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def check_lock(document: dict, actual: bytes) -> None:
    if normalized(actual) != serialized(document):
        raise ValueError("Go dependency lock differs from the complete resolved graph")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    document = resolved_lock()
    if arguments.check:
        check_lock(document, LOCK.read_bytes())
    else:
        LOCK.write_bytes(serialized(document))
    action = "checked" if arguments.check else "generated"
    print(f"{action} Go dependency lock: {len(document['modules'])} modules, "
          f"{len(TOOL_MODULES)} unified tools, Go {document['goVersion']}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as failure:
        print(f"Go dependency locking failed: {failure}", file=sys.stderr)
        raise SystemExit(1)
