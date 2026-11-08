#!/usr/bin/env python3
"""Install the verified Linux x86_64 wit-bindgen CLI used by the contract gate."""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import platform
import sys
import tarfile
import time
import urllib.error
import urllib.request

VERSION = "0.62.0"
ARCHIVE_SHA256 = "3e81cc6523729f7532b4aa7968648a04abf0c711b7d1677150e9121f4e6458fe"
URL = (f"https://github.com/bytecodealliance/wit-bindgen/releases/download/v{VERSION}/"
       f"wit-bindgen-{VERSION}-x86_64-linux.tar.gz")
# GitHub's asset ID for this exact release file. Its bytes must still pass the
# same pinned archive digest and executable checks as the primary URL.
ASSET_URL = "https://api.github.com/repos/bytecodealliance/wit-bindgen/releases/assets/555672356"
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


def download_archive() -> bytes:
    deadline = time.monotonic() + 90

    def read_before_deadline(request):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("wit-bindgen download bound exceeded")
        archive = bytearray()
        with urllib.request.urlopen(request, timeout=min(30, remaining)) as response:
            while True:
                block = response.read(65536)
                if time.monotonic() > deadline:
                    raise ValueError("wit-bindgen download bound exceeded")
                if not block:
                    break
                archive.extend(block)
                if len(archive) > MAX_ARCHIVE:
                    raise ValueError("wit-bindgen download bound exceeded")
        return bytes(archive)

    try:
        return read_before_deadline(URL)
    except urllib.error.HTTPError as error:
        if error.code != 504:
            raise
        error.close()
        reason = "HTTP 504"
    except TimeoutError:
        # The response context has closed and any partially read bytes are
        # discarded before the fixed asset is fetched under the same deadline.
        reason = "timeout"
    print(f"wit-bindgen release download encountered {reason}; trying pinned release asset API",
          file=sys.stderr)
    request = urllib.request.Request(ASSET_URL, headers={
        "Accept": "application/octet-stream",
        "User-Agent": "latent-service-fabric-ci",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return read_before_deadline(request)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("this installer supports only the pinned Linux CI profile")
    data = binary(download_archive())
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / "wit-bindgen"
    with destination.open("xb") as output:
        output.write(data)
    destination.chmod(0o755)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
