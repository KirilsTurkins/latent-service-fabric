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
import urllib.error
import urllib.parse
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


# Immutable, separately reviewed fallbacks for the exact pinned Linux scanners.
# Archive and executable identities are still checked by install/verify_tool.
ZIZMOR_LINUX_URL = ("https://github.com/zizmorcore/zizmor/releases/download/v1.30.1/"
                    "zizmor-x86_64-unknown-linux-gnu.tar.gz")
ZIZMOR_LINUX_ASSET = "https://api.github.com/repos/zizmorcore/zizmor/releases/assets/552067642"
ZIZMOR_LINUX_ASSET_BYTES = 9_169_512
CARGO_AUDIT_LINUX_URL = ("https://github.com/rustsec/rustsec/releases/download/cargo-audit/v0.22.2/"
                         "cargo-audit-x86_64-unknown-linux-gnu-v0.22.2.tgz")
CARGO_AUDIT_LINUX_ASSET = "https://api.github.com/repos/rustsec/rustsec/releases/assets/439291614"
CARGO_AUDIT_LINUX_ASSET_BYTES = 6_554_209


class _AssetRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward the API credential or follow an unrelated asset host."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        require(target.scheme == "https" and target.hostname == "release-assets.githubusercontent.com"
                and target.port in (None, 443) and target.username is None and target.password is None,
                "unreviewed-asset-redirect")
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        require(redirected is not None and all(key.lower() != "authorization"
                for key, _ in redirected.header_items()), "asset-redirect-credential")
        return redirected


def _read_download(request, started: float, opener) -> bytes:
    payload = bytearray()
    with opener(request, timeout=20) as response:
        require(response.status == 200 and response.url.startswith("https://"), "download-status")
        while chunk := response.read1(65536):
            payload.extend(chunk)
            require(len(payload) <= MAX_DOWNLOAD_BYTES, "download-size-limit")
            require(time.monotonic() - started < 120, "download-time-limit")
    return bytes(payload)


def download(url: str) -> bytes:
    require(url.startswith("https://github.com/"), "unreviewed-download-origin")
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "lsf-security-baseline/1"})
    try:
        return _read_download(request, started, urllib.request.urlopen)
    except (TimeoutError, urllib.error.URLError) as failure:
        # Never retry integrity/size failures, unrelated HTTP errors, other
        # tools, or work without the scoped credential. Discard partial bytes.
        if isinstance(failure, urllib.error.HTTPError):
            transient = failure.code == 504
        elif isinstance(failure, urllib.error.URLError):
            transient = isinstance(failure.reason, TimeoutError)
        else:
            transient = True
        if url == ZIZMOR_LINUX_URL:
            asset_url, asset_bytes = ZIZMOR_LINUX_ASSET, ZIZMOR_LINUX_ASSET_BYTES
        elif url == CARGO_AUDIT_LINUX_URL:
            asset_url, asset_bytes = CARGO_AUDIT_LINUX_ASSET, CARGO_AUDIT_LINUX_ASSET_BYTES
        else:
            asset_url, asset_bytes = None, None
        token = os.environ.get("GH_TOKEN") if asset_url and transient else None
        if not token:
            raise
        if isinstance(failure, urllib.error.HTTPError):
            failure.close()
        request = urllib.request.Request(asset_url, headers={
            "Accept": "application/octet-stream", "User-Agent": "lsf-security-baseline/1"})
        # urllib drops unredirected headers before following a redirect; the
        # handler also validates the next host and checks the copied headers.
        request.add_unredirected_header("Authorization", "Bearer " + token)
        opener = urllib.request.build_opener(_AssetRedirect()).open
        payload = _read_download(request, started, opener)
        require(len(payload) == asset_bytes, "download-size-mismatch")
        return payload


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
