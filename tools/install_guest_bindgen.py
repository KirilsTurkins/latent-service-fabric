#!/usr/bin/env python3
"""Install the verified Linux x86_64 wit-bindgen CLI used by the contract gate."""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import platform
import tarfile
import time
import urllib.request

VERSION = "0.60.0"
ARCHIVE_SHA256 = "6dc887e6d66a183d196885ff611e7f0a7db64db189f95c18f2a65fcf65d3651b"
URL = (f"https://github.com/bytecodealliance/wit-bindgen/releases/download/v{VERSION}/"
       f"wit-bindgen-{VERSION}-x86_64-linux.tar.gz")
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_BINARY = 64 * 1024 * 1024


def binary(archive: bytes) -> bytes:
    if len(archive) > MAX_ARCHIVE or hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("wit-bindgen archive identity mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        matches = []
        for index, member in enumerate(source):
            if index >= 32 or member.size > MAX_BINARY:
                raise ValueError("wit-bindgen archive bound exceeded")
            if Path(member.name).name == "wit-bindgen":
                if not member.isfile() or not 0 < member.size <= MAX_BINARY:
                    raise ValueError("wit-bindgen executable is not a bounded regular file")
                matches.append(member)
        if len(matches) != 1:
            raise ValueError("wit-bindgen executable is ambiguous or missing")
        stream = source.extractfile(matches[0])
        assert stream is not None
        data = stream.read(MAX_BINARY + 1)
        if len(data) != matches[0].size:
            raise ValueError("wit-bindgen executable size mismatch")
        return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("this installer supports only the pinned Linux CI profile")
    deadline = time.monotonic() + 90
    archive = bytearray()
    with urllib.request.urlopen(URL, timeout=30) as response:
        while block := response.read(65536):
            archive.extend(block)
            if len(archive) > MAX_ARCHIVE or time.monotonic() > deadline:
                raise ValueError("wit-bindgen download bound exceeded")
    data = binary(bytes(archive))
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / "wit-bindgen"
    with destination.open("xb") as output:
        output.write(data)
    destination.chmod(0o755)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
