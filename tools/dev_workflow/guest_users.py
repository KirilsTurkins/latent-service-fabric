"""Root-only, recorded Linux user provisioning in the authenticated owned WSL image."""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import re
import sys

from . import paths, process, state
from .common import DevError, decode, encode, identifier, members, require, sha


def validate(value: dict) -> dict:
    members(value, {"workspace", "user", "helperSha256", "nonce"})
    identifier(value["workspace"])
    sha(value["helperSha256"])
    require(isinstance(value["user"], str) and re.fullmatch(r"lsfd-[a-f0-9]{12}", value["user"]), "invalid-owned-user")
    require(isinstance(value["nonce"], str) and re.fullmatch(r"[a-f0-9]{32}", value["nonce"]), "invalid-user-owner-nonce")
    return value


def observed(record: dict):
    value = record["owner"]
    try:
        user = pwd.getpwnam(value["user"])
    except KeyError:
        return None
    require(user.pw_uid >= 1000 and user.pw_gecos == "latent-dev:" + value["nonce"]
            and user.pw_dir == "/home/" + value["user"] and user.pw_shell == "/usr/sbin/nologin", "owned-linux-user-replaced")
    if "uid" in record:
        require(record["uid"] == user.pw_uid, "owned-linux-uid-replaced")
    home = Path(user.pw_dir)
    with paths.directory(home) as descriptor:
        metadata = os.fstat(descriptor)
        require(metadata.st_uid == user.pw_uid, "owned-linux-home-replaced")
        if "homeInode" in record:
            require(record["homeInode"] == [metadata.st_dev, metadata.st_ino], "owned-linux-home-replaced")
    return user


def mark_ready(root: Path, name: str, record: dict) -> dict:
    user = observed(record)
    require(user is not None, "owned-linux-user-absent")
    with paths.directory(Path(user.pw_dir)) as descriptor:
        os.fchmod(descriptor, 0o700)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        record.update(state="ready", uid=user.pw_uid, homeInode=[metadata.st_dev, metadata.st_ino])
    state.atomic(root, name, record)
    return {"user": user.pw_name, "uid": user.pw_uid, "state": "ready"}


def no_processes(uid: int) -> None:
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            lines = (path / "status").read_text().splitlines()
        except (FileNotFoundError, ProcessLookupError):
            continue
        for line in lines:
            if line.startswith("Uid:"):
                require(str(uid) not in line.split()[1:], "owned-linux-user-has-live-processes-stop-first")


def operation(mode: str, value: dict, root: Path) -> dict:
    validate(value)
    name = value["user"] + ".json"
    if mode == "create-user":
        require(not (root / name).exists(), "linux-user-already-recorded-use-recovery")
        try:
            pwd.getpwnam(value["user"])
        except KeyError:
            pass
        else:
            raise DevError("refuse-adopting-existing-linux-user")
        require(not (Path("/home") / value["user"]).exists(), "refuse-adopting-existing-linux-home")
        record = {"owner": value, "state": "creating"}
        state.atomic(root, name, record)
        completed = process.run(["/usr/sbin/useradd", "--create-home", "--user-group", "--shell", "/usr/sbin/nologin",
            "--comment", "latent-dev:" + value["nonce"], "--home-dir", "/home/" + value["user"], value["user"]], root, timeout=10)
        require(completed.returncode == 0, "owned-linux-user-creation-uncertain-use-recovery")
        return mark_ready(root, name, record)
    record = state.load(root, name)
    require(record["owner"] == value, "linux-user-owner-mismatch")
    user = observed(record)
    if mode == "user-status":
        if record["state"] == "creating" and user is not None:
            return mark_ready(root, name, record)
        return {"user": value["user"], "state": record["state"], "present": user is not None}
    require(mode == "remove-user", "guest-user-operation")
    home = Path("/home") / value["user"]
    if record["state"] == "removed":
        require(user is None and not home.exists(), "removed-linux-user-reappeared")
        return {"user": value["user"], "state": "removed"}
    require(record["state"] in {"ready", "removing"}, "recover-linux-user-before-removal")
    if user is not None:
        no_processes(user.pw_uid)
        workspace = home / ".lsf-dev" / value["workspace"]
        from tools.native_runtime import files
        lifecycle = decode(files.read(workspace / "lifecycle.json", owners={0, user.pw_uid}, private=True))
        require(lifecycle["state"] == "purged" and lifecycle.get("reaped") is True, "purge-workspace-before-user-removal")
        record["state"] = "removing"
        state.atomic(root, name, record)
        completed = process.run(["/usr/sbin/userdel", value["user"]], root, timeout=10)
        require(completed.returncode == 0, "owned-linux-user-removal-uncertain")
    else:
        require(record["state"] == "removing", "owned-linux-user-missing-before-removal")
    # Deletion is anchored to this recorded user's exact private home, after
    # its account is gone. No shell paths, PID kills, or other homes are involved.
    if home.exists():
        from tools.native_runtime import files
        with paths.directory(home) as descriptor:
            metadata = os.fstat(descriptor)
            require(record["homeInode"] == [metadata.st_dev, metadata.st_ino]
                    and metadata.st_uid == record["uid"], "owned-linux-home-replaced")
        files.remove_tree(home, maximum=65536)
    record["state"] = "removed"
    state.atomic(root, name, record)
    return {"user": value["user"], "state": "removed"}


def main(mode: str) -> int:
    require(os.geteuid() == 0, "wsl-user-provision-requires-owned-image-root")
    value = decode(sys.stdin.buffer.read(8193), 8192)
    root = Path("/var/lib/latent-dev")
    if not root.exists():
        paths.new_directory(root)
    with state.lock(root, "users.lock"):
        result = operation(mode, value, root)
    sys.stdout.buffer.write(encode(result))
    return 0
