"""One explicit data owner retained through initial exit and same-root reopen."""
import os
from pathlib import Path
import re
import secrets
import shutil
import stat

from tools.optimization_evidence.common import canonical, fields, hash_file, read_json, require, sha256, uint
from . import model

MARKER_SCHEMA = "latent.optimization.catalog-data-owner.v1"
REOPEN_SCHEMA = "latent.optimization.catalog-reopen.v1"
CATALOG_PATH = "data/deployments/catalog.json"
MAX_TREE_BYTES = 16 * 1024**3
MAX_TREE_FILES = 400016
MAX_TREE_DIRECTORIES = 100016


def reserve(root, required):
    observed = os.statvfs(root)
    available = observed.f_bavail * observed.f_frsize
    require(not required or available >= MAX_TREE_BYTES, "catalog-native-filesystem-reserve")
    return {"source": "statvfs-f_bavail-times-f_frsize", "available_bytes": str(available),
            "required_bytes": str(MAX_TREE_BYTES if required else 0),
            "scope": "native-filesystem-available-not-host-backing-capacity"}


def close_tree(root):
    """One post-exit walk; no sampling-loop scan or generated-content archive."""
    root = Path(root)
    root_stat = root.lstat()
    require(stat.S_ISDIR(root_stat.st_mode) and not root.is_symlink(), "catalog-close-root-type")
    pending, files, directories, logical, allocated, maximum = [(root, 0)], 0, 1, 0, 0, 0
    allocated_available = hasattr(root_stat, "st_blocks")
    while pending:
        current, depth = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                # Windows DirEntry's cached stat omits the volume identity.
                info = os.stat(entry.path, follow_symlinks=False) if os.name == "nt" else entry.stat(follow_symlinks=False)
                require(not entry.is_symlink() and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                        and info.st_dev == root_stat.st_dev, "catalog-close-tree-escape-or-type")
                if stat.S_ISDIR(info.st_mode):
                    directories += 1
                    require(depth < 8 and directories <= MAX_TREE_DIRECTORIES, "catalog-close-directory-bound")
                    pending.append((Path(entry.path), depth + 1))
                else:
                    require(stat.S_ISREG(info.st_mode), "catalog-close-tree-special-file")
                    files += 1
                    logical += info.st_size
                    maximum = max(maximum, info.st_size)
                    require(files <= MAX_TREE_FILES and logical <= MAX_TREE_BYTES and info.st_size <= 1024**3,
                            "catalog-close-file-bound")
                    if allocated_available:
                        allocated += info.st_blocks * 512
    return {"scope": "one-post-exit-generated-root-walk-before-removal", "regular_files": str(files),
            "directories_including_root": str(directories), "logical_file_bytes": str(logical),
            "allocated_file_bytes": str(allocated) if allocated_available else None,
            "maximum_file_bytes": str(maximum), "complete": True,
            "symlinks_or_special_files": False, "cross_device_entries": False}


def remove_owned(root, parent, expected_identity):
    root, parent = Path(root), Path(parent).resolve()
    require(root.resolve().parent == parent and root.name.startswith("catalog-data-owned-")
            and identity(root, expected_identity["marker"]) == expected_identity, "catalog-cleanup-target-crossed")
    shutil.rmtree(root)


def marker(selected, commit, *, nonce=None):
    value = {"schema": MARKER_SCHEMA, "nonce": secrets.token_hex(16) if nonce is None else nonce,
             "group": model.group_id(selected), "variant": selected["variant"], "shape": selected["shape"],
             "repetition": selected["repetition"], "source_commit": commit}
    validate_marker(value, selected, commit)
    return value


def validate_marker(value, selected, commit):
    fields(value, "schema nonce group variant shape repetition source_commit")
    require(value["schema"] == MARKER_SCHEMA and isinstance(value["nonce"], str)
            and re.fullmatch("[0-9a-f]{32}", value["nonce"]) is not None
            and isinstance(commit, str) and re.fullmatch("[0-9a-f]{40}", commit) is not None,
            "catalog-data-marker-format")
    require(type(value["repetition"]) is int
            and value == {**value, "group": model.group_id(selected), "variant": selected["variant"],
                          "shape": selected["shape"], "repetition": selected["repetition"],
                          "source_commit": commit}, "catalog-data-marker-selection")
    return value


def create(root, value):
    encoded = canonical(value) + b"\n"
    with (Path(root) / "owner.json").open("xb") as destination:
        destination.write(encoded)
    return identity(root, value)


def identity(root, value):
    root = Path(root)
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode) and not root.is_symlink(), "catalog-data-root-type")
    path = root / "owner.json"
    require(not path.is_symlink() and read_json(path, 4096) == value, "catalog-data-marker-crossed")
    checksum, _ = hash_file(path, 4096)
    return {"device": str(info.st_dev), "inode": str(info.st_ino), "marker_sha256": checksum, "marker": value}


def post_exit(root, value, initial_process, initial_raw):
    root = Path(root)
    catalog = root / CATALOG_PATH
    require(not catalog.is_symlink() and catalog.resolve().is_relative_to(root.resolve()),
            "catalog-persisted-path-crossed")
    checksum, size = hash_file(catalog, 1024**3)
    require(size > 0, "catalog-persisted-empty")
    return {"schema": REOPEN_SCHEMA, "data_identity": identity(root, value),
            "initial_process": {key: initial_process[key] for key in ("process_id", "start_time_ticks")},
            "catalog": {"path": CATALOG_PATH, "bytes": str(size), "sha256": checksum},
            "initial_raw": initial_raw}


def validate_identity(value, selected, commit):
    fields(value, "device inode marker_sha256 marker")
    uint(value["device"])
    require(uint(value["inode"]) > 0, "catalog-data-inode-missing")
    validate_marker(value["marker"], selected, commit)
    # The parent writes the marker once using this exact byte representation.
    require(value["marker_sha256"] == sha256(canonical(value["marker"]) + b"\n"),
            "catalog-data-marker-byte-binding")
    return value
