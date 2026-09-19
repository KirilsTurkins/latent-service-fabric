"""Install only reviewed, digest-pinned upstream scanner assets; no shared cache."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import sys
import tarfile
import time
import urllib.request
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.security_common import POLICY, SecurityError, decode_json, digest, read_file, require, run

MAX_DOWNLOAD_BYTES = 96 * 1024 * 1024
MAX_BINARY_BYTES = 192 * 1024 * 1024


def tool_lock() -> dict:
    document = decode_json(read_file(POLICY, "tools.json"))
    require(isinstance(document, dict) and document.get("schema") == 1, "invalid-tools-policy")
    require(set(document["tools"]) == {"cargo-audit", "gitleaks", "zizmor"}, "invalid-tool-set")
    for identity in document["tools"].values():
        require(re.fullmatch(r"[0-9a-f]{40}", identity["commit"]) is not None, "invalid-tool-commit")
        require(identity["repository"] in {"rustsec/rustsec", "gitleaks/gitleaks", "zizmorcore/zizmor"},
                "unreviewed-tool-upstream")
        for asset in identity["assets"].values():
            require(re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]) is not None, "invalid-tool-digest")
            require(re.fullmatch(r"[0-9a-f]{64}", asset["binary_sha256"]) is not None, "invalid-binary-digest")
    return document


def platform_key() -> str:
    require(platform.machine().lower() in {"amd64", "x86_64"}, "unsupported-scanner-architecture")
    require(sys.platform in {"win32", "linux"}, "unsupported-scanner-platform")
    return "windows-x64" if os.name == "nt" else "linux-x64"


def download(url: str) -> bytes:
    require(url.startswith("https://github.com/"), "unreviewed-download-origin")
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "lsf-security-baseline/1"})
    payload = bytearray()
    with urllib.request.urlopen(request, timeout=20) as response:
        require(response.status == 200 and response.url.startswith("https://"), "download-status")
        while chunk := response.read1(65536):
            payload.extend(chunk)
            require(len(payload) <= MAX_DOWNLOAD_BYTES, "download-size-limit")
            require(time.monotonic() - started < 120, "download-time-limit")
    return bytes(payload)


def extract_binary(payload: bytes, asset_name: str, binary_name: str) -> bytes:
    if asset_name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = [entry for entry in archive.infolist() if PurePosixPath(entry.filename).name == binary_name]
            require(len(members) == 1, "archive-binary-count")
            member = members[0]
            require(not member.is_dir() and member.file_size <= MAX_BINARY_BYTES, "archive-binary-size")
            require((member.external_attr >> 16) & 0o170000 != 0o120000, "archive-binary-link")
            with archive.open(member) as stream:
                binary = stream.read(MAX_BINARY_BYTES + 1)
    else:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members = [entry for entry in archive.getmembers() if PurePosixPath(entry.name).name == binary_name]
            require(len(members) == 1, "archive-binary-count")
            member = members[0]
            require(member.isfile() and member.size <= MAX_BINARY_BYTES, "archive-binary-size-or-link")
            stream = archive.extractfile(member)
            require(stream is not None, "missing-archive-binary")
            with stream:
                binary = stream.read(MAX_BINARY_BYTES + 1)
    require(0 < len(binary) <= MAX_BINARY_BYTES, "archive-binary-size")
    return binary


def install(tool: str, destination: Path) -> dict:
    identity = tool_lock()["tools"][tool]
    asset = identity["assets"][platform_key()]
    url = f"https://github.com/{identity['repository']}/releases/download/{identity['tag']}/{asset['name']}"
    payload = download(url)
    require(digest(payload) == asset["sha256"], "download-digest-mismatch")
    binary_name = tool + (".exe" if os.name == "nt" else "")
    binary = extract_binary(payload, asset["name"], binary_name)
    require(digest(binary) == asset["binary_sha256"], "archive-binary-digest-mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / binary_name
    require(not target.exists() and not target.is_symlink(), "scanner-destination-exists")
    with target.open("xb") as stream:
        stream.write(binary)
    target.chmod(0o700)
    receipt = {"tool": tool, "version": identity["version"], "commit": identity["commit"],
               "archive_sha256": asset["sha256"], "binary_sha256": digest(binary)}
    (destination / f"{tool}.identity.json").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    verify_tool(tool, destination)
    return receipt


def verify_tool(tool: str, destination: Path) -> Path:
    identity = tool_lock()["tools"][tool]
    asset = identity["assets"][platform_key()]
    receipt = decode_json(read_file(destination, f"{tool}.identity.json"))
    binary_name = tool + (".exe" if os.name == "nt" else "")
    require(receipt["archive_sha256"] == asset["sha256"] and receipt["commit"] == identity["commit"],
            "scanner-identity-mismatch")
    require(digest(read_file(destination, binary_name, MAX_BINARY_BYTES)) == asset["binary_sha256"],
            "scanner-binary-mismatch")
    binary = (destination / binary_name).resolve()
    _, output = run([str(binary), "version" if tool == "gitleaks" else "--version"], destination, timeout=15)
    expected = identity["version"] if tool == "gitleaks" else f"{tool} {identity['version']}"
    require(output.decode("utf-8").strip() == expected, "scanner-version-mismatch")
    return binary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True, choices=("cargo-audit", "gitleaks", "zizmor"))
    parser.add_argument("--destination", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        print(json.dumps(install(arguments.tool, arguments.destination.resolve()), sort_keys=True))
        return 0
    except (SecurityError, OSError, ValueError, KeyError) as error:
        print(f"Security installer failed: {error if isinstance(error, SecurityError) else 'invalid-or-unavailable-tool'}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
