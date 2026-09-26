"""Generate the Node client descriptor from the authoritative selected RPCs."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "sdk/typescript-client/src/node/protocol/generated.ts"


def generated(protoc):
    version = subprocess.run([protoc, "--version"], capture_output=True, check=True, timeout=10)
    if version.stdout.strip() != b"libprotoc 31.1":
        raise ValueError("expected the locked protoc-bin-vendored 3.2.0 compiler (libprotoc 31.1)")
    profile = json.loads((ROOT / "sdk/profile/client-profile.json").read_text(encoding="utf-8"))
    sources = sorted(profile["sources"])
    digest = hashlib.sha256()
    for source in sources:
        if not source.startswith("api/proto/latent/") or ".." in source:
            raise ValueError("invalid selected protocol source")
        content = (ROOT / source).read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
        digest.update(source.encode() + b"\0" + content + b"\0")
    with tempfile.TemporaryDirectory(prefix="lsf-node-protocol-") as temporary:
        output = Path(temporary) / "descriptor.bin"
        subprocess.run([
            protoc, "--proto_path=" + str(ROOT / "api/proto"),
            "--descriptor_set_out=" + str(output), "--include_imports",
            *(source.removeprefix("api/proto/") for source in sources),
        ], cwd=ROOT, check=True, capture_output=True, timeout=30)
        data = output.read_bytes()
        if not 0 < len(data) <= 65536:
            raise ValueError("descriptor size outside the fixed bound")
    encoded = base64.b64encode(data).decode("ascii")
    return (
        'import { Buffer } from "node:buffer";\n\n'
        f'export const sourceDigest = "sha256:{digest.hexdigest()}";\n'
        f'export const descriptorBytes = Buffer.from("{encoded}", "base64");\n'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protoc", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = generated(args.protoc)
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != content:
            raise SystemExit("Node RPC descriptors differ from the authoritative protocol")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
