"""Stage authenticated offline compiler inputs inside one owned build attempt."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import tarfile

from tools.dev_workflow import paths
from tools.dev_workflow.common import require

ZIG_VERSION = "0.16.0"
ZIG_SHA256 = "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00"
ZIG_BYTES = 55478392


def unpack_zig(archive: Path, destination: Path, check) -> Path:
    """The original, hash-pinned archive is retained; no links or install hooks."""
    require(not destination.exists(), "guest-linker-staging-must-be-fresh")
    require(paths.digest_file(archive.parent, archive.name, ZIG_BYTES, check=check)
            == ("sha256:" + ZIG_SHA256, ZIG_BYTES), "guest-linker-archive-digest")
    destination.mkdir(mode=0o700)
    prefix = "zig-x86_64-linux-" + ZIG_VERSION
    seen, total = set(), 0
    with paths.opened(archive.parent, archive.name) as descriptor, os.fdopen(os.dup(descriptor), "rb") as source:
        with tarfile.open(fileobj=source, mode="r:xz") as package:
            for ordinal, entry in enumerate(package):
                check()
                require(ordinal < 24000 and (entry.isfile() or entry.isdir()), "guest-linker-entry-limit-or-type")
                require(entry.name == prefix or entry.name.startswith(prefix + "/"), "guest-linker-archive-root")
                if entry.name == prefix:
                    require(entry.isdir(), "guest-linker-archive-root")
                    continue
                relative = paths.relative(entry.name[len(prefix) + 1:].rstrip("/"))
                alias = paths.alias(relative)
                require(alias not in seen, "guest-linker-entry-alias")
                seen.add(alias)
                total += entry.size
                require(0 <= entry.size <= 256 * 1024 * 1024 and total <= 512 * 1024 * 1024,
                        "guest-linker-expanded-limit")
                target = destination / relative
                if entry.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with package.extractfile(entry) as data, target.open("xb") as output:
                    copied = 0
                    while raw := data.read(1024 * 1024):
                        check()
                        copied += len(raw)
                        require(copied <= entry.size, "guest-linker-expanded-limit")
                        output.write(raw)
                    require(copied == entry.size, "guest-linker-entry-size")
                target.chmod(0o700 if relative == "zig" else 0o600)
    return destination / "zig"


def stage_registry(source: Path, destination: Path, check) -> None:
    require(not destination.exists(), "guest-cargo-cache-must-be-fresh")
    def copy_file(original, target):
        check()
        original = Path(original)
        paths.regular(original.lstat())
        return shutil.copyfile(original, target)
    # The controller has already checked every source against the tool inventory.
    shutil.copytree(source, destination, copy_function=copy_file)
    # A distributed prefix may be read-only. Cargo's private index/cache copy
    # must accept its own locks and extraction without changing the source.
    for current, _directories, names in os.walk(destination):
        check()
        Path(current).chmod(0o700)
        for name in names:
            (Path(current) / name).chmod(0o600)
    check()


def linker(zig: Path, cache: Path) -> Path:
    """Private fixed compiler launcher; application text is never shell code."""
    result = cache / "host-linker"
    result.write_text("#!/bin/sh\nexport ZIG_GLOBAL_CACHE_DIR=" + shlex.quote(str(cache / "zig-global"))
        + " ZIG_LOCAL_CACHE_DIR=" + shlex.quote(str(cache / "zig-local")) + "\nexec "
        + shlex.quote(str(zig)) + ' cc -target x86_64-linux-gnu.2.39 "$@"\n', encoding="utf-8")
    result.chmod(0o700)
    return result
