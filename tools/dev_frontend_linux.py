"""Observe the Linux frontend's collected native libraries and retain their terms."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sysconfig

from tools.dev_workflow.common import digest, encode, require


def collect(output: Path) -> dict:
    root = output / "dist/latent-dev"
    # PyInstaller may deduplicate files with symlinks. Only links wholly inside
    # this newly built distribution may be materialized; the bundle has no links.
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            source = path.resolve(strict=True)
            require(source.is_relative_to(root) and source.is_file(), "frontend-link-outside-build")
            raw = source.read_bytes()
            path.unlink()
            path.write_bytes(raw)
    toc = output / "work/latent-dev/COLLECT-00.toc"
    require(toc.stat().st_size <= 4 * 1024 * 1024, "frontend-collection-limit")
    entries = ast.literal_eval(toc.read_text())
    require(isinstance(entries, tuple) and len(entries) == 1 and isinstance(entries[0], list),
            "frontend-collection-format")
    libraries, packages = [], {}
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    python_library = (Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("LDLIBRARY")).resolve()
    for entry in entries[0]:
        require(isinstance(entry, tuple) and len(entry) == 3 and all(isinstance(x, str) for x in entry),
                "frontend-collection-entry")
        name, original, kind = entry
        if kind not in {"BINARY", "EXTENSION"}:
            require(kind in {"DATA", "EXECUTABLE", "SYMLINK"}, "frontend-collection-kind")
            continue
        source = Path(original).resolve(strict=True)
        destination = root / "_internal" / name
        require(source.is_file() and destination.is_file() and destination.resolve().is_relative_to(root),
                "frontend-native-library-path")
        checksum = digest(destination.read_bytes())
        require(digest(source.read_bytes()) == checksum, "frontend-native-library-changed")
        if source == python_library or source.is_relative_to(stdlib / "lib-dynload"):
            owner = "CPython"
        else:
            require(source.is_relative_to("/usr/lib") or source.is_relative_to("/lib"),
                    "frontend-native-library-owner-unknown")
            owner = package_owner(Path(original), source)
            if owner not in packages:
                packages[owner] = package_terms(owner, output)
        libraries.append({"path": "bin/_internal/" + name, "sha256": checksum, "owner": owner})
        require(len(libraries) <= 128 and len(packages) <= 32, "frontend-native-inventory-limit")
    require(libraries and packages, "frontend-native-inventory-empty")
    # Package copyright files refer to these distro-provided common texts.
    for source in sorted(Path("/usr/share/common-licenses").iterdir()):
        resolved = source.resolve(strict=True)
        require(resolved.is_relative_to("/usr/share/common-licenses") and resolved.is_file(),
                "frontend-common-license-path")
        shutil.copyfile(resolved, output / "licenses" / ("common-" + source.name + ".txt"))
    family, version = platform.libc_ver()
    require(family == "glibc" and version, "frontend-linux-glibc-required")
    observation = {"nativeLibraries": libraries, "nativePackages": list(packages.values()),
                   "hostRequirements": {"os": "linux", "architecture": "x86_64", "libc": family,
                                        "minimumLibcVersion": version},
                   "buildOsRelease": Path("/etc/os-release").read_text()}
    inventory = output / "python-inventory.json"
    value = json.loads(inventory.read_bytes())
    value.update(observation)
    inventory.write_bytes(encode(value))
    return observation


def package_owner(original: Path, resolved: Path) -> str:
    for candidate in dict.fromkeys((original, resolved)):
        result = subprocess.run(["dpkg-query", "-S", str(candidate)], capture_output=True, timeout=10)
        if result.returncode == 0:
            owners = {line.rsplit(": ", 1)[0] for line in result.stdout.decode().splitlines()
                      if line.endswith(": " + str(candidate))}
            require(len(owners) == 1, "frontend-ambiguous-library-owner")
            return owners.pop()
    require(False, "frontend-native-package-owner-missing")


def package_terms(name: str, output: Path) -> dict:
    version = subprocess.check_output(["dpkg-query", "-W", "-f=${Version}", name], timeout=10).decode()
    source = (Path("/usr/share/doc") / name.split(":")[0] / "copyright").resolve(strict=True)
    require(source.is_relative_to("/usr/share/doc") and source.is_file(), "frontend-native-license-path")
    raw = source.read_bytes()
    destination = "licenses/linux-" + name.replace(":", "-") + ".txt"
    (output / destination).write_bytes(raw)
    return {"name": name, "version": version, "licenseFile": destination, "licenseSha256": digest(raw)}
