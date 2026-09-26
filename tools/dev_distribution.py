"""Deterministic unsigned developer bundle assembly; identity approval stays external."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat
import zipfile

from tools.dev_workflow import bundle, paths
from tools.dev_workflow.common import HOST_ABI, PROTOCOL, encode, require


def file_digest(path: Path) -> tuple[str, int]:
    path = paths.absolute(path.absolute())
    checksum, size = hashlib.sha256(), 0
    with paths.opened(path.parent, path.name) as descriptor:
        while raw := os.read(descriptor, 1024 * 1024):
            size += len(raw)
            require(size <= bundle.MAX_BUNDLE, "developer-distribution-file-limit")
            checksum.update(raw)
    return "sha256:" + checksum.hexdigest(), size


def frontend_files(root: Path) -> dict:
    """Bind every redistributed frontend byte across native build/assembly jobs."""
    selected = [root / "helper.pyz", root / "python-inventory.json"]
    for directory in (root / "dist/latent-dev", root / "licenses"):
        require(directory.is_dir() and not directory.is_symlink() and not directory.is_junction(),
                "frontend-inventory-directory")
        for parent, directories, names in os.walk(directory, followlinks=False):
            for name in [*directories, *names]:
                path = Path(parent) / name
                require(not path.is_symlink() and not path.is_junction(), "frontend-inventory-links-forbidden")
            selected.extend(Path(parent) / name for name in names)
    require(0 < len(selected) <= bundle.MAX_ENTRIES, "frontend-inventory-entry-limit")
    result = {}
    total = 0
    for path in sorted(selected):
        checksum, size = file_digest(path)
        total += size
        require(total <= bundle.MAX_BUNDLE * 2, "frontend-inventory-byte-limit")
        result[paths.relative(path.relative_to(root).as_posix())] = {"sha256": checksum, "size": size}
    return result


def assemble(payload: Path, output: Path, *, commit: str, version: str, target: str, epoch: int,
             executables: set[str], archive_name: str | None = None) -> dict:
    require(not output.exists(), "new-candidate-directory-required")
    entries = []
    for root, directories, names in os.walk(payload, followlinks=False):
        for name in [*directories, *names]:
            path = Path(root) / name
            require(not path.is_symlink() and not path.is_junction(), "distribution-links-forbidden")
        for name in names:
            path = Path(root) / name
            relative = paths.relative(path.relative_to(payload).as_posix())
            sha256, size = file_digest(path)
            entries.append({"path": relative, "sha256": sha256, "size": size, "executable": relative in executables})
            require(len(entries) <= bundle.MAX_ENTRIES, "developer-distribution-entry-limit")
    entries.sort(key=lambda entry: entry["path"])
    require(executables <= {entry["path"] for entry in entries}, "distribution-executable-missing")
    require(sum(entry["size"] for entry in entries) <= bundle.MAX_BUNDLE * 2, "developer-expanded-byte-limit")
    output.mkdir(parents=True)
    name = paths.relative(archive_name or f"latent-dev-{target}.zip")
    require("/" not in name, "distribution-archive-basename-required")
    stamp = datetime.fromtimestamp(max(epoch, 315532800), timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(output / name, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for record in entries:
            entry = zipfile.ZipInfo(record["path"], stamp)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | (0o755 if record["executable"] else 0o644)) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            with (payload / record["path"]).open("rb") as source, archive.open(entry, "w") as destination:
                checksum, copied = hashlib.sha256(), 0
                while raw := source.read(1024 * 1024):
                    destination.write(raw)
                    checksum.update(raw)
                    copied += len(raw)
                require(copied == record["size"] and "sha256:" + checksum.hexdigest() == record["sha256"],
                        "distribution-input-changed")
    checksum, size = file_digest(output / name)
    value = {"schemaVersion": "latent.dev.bundle.v1", "version": version, "sourceCommit": commit,
             "target": target, "hostAbi": HOST_ABI, "protocol": PROTOCOL,
             "archive": {"name": name, "sha256": checksum, "size": size}, "files": entries,
             "licenses": [entry["path"] for entry in entries if entry["path"].startswith("licenses/")],
             "sbom": "sbom.spdx.json"}
    bundle.manifest(value, target=target, version=version, commit=commit)
    (output / "developer-bundle.json").write_bytes(encode(value))
    inventory = {name: checksum[7:], "developer-bundle.json": file_digest(output / "developer-bundle.json")[0][7:]}
    (output / "SHA256SUMS").write_bytes("".join(f"{sha}  {file}\n" for file, sha in sorted(inventory.items())).encode())
    return value
