"""A recorded WSL2 distro; no global/default distribution or kernel changes."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import secrets

from . import backend, paths, process, state
from .common import DevError, decode, encode, members, require, sha


def registrations() -> dict:
    require(os.name == "nt", "wsl-requires-windows")
    import winreg
    result = {}
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Lxss")
    except FileNotFoundError:
        return result
    with key:
        for index in range(256):
            try:
                name = winreg.EnumKey(key, index)
            except OSError as error:
                require(error.winerror == 259, "wsl-registry-enumeration-failed")
                break
            with winreg.OpenKey(key, name) as distro:
                result[winreg.QueryValueEx(distro, "DistributionName")[0]] = {
                    "registration": name,
                    "path": winreg.QueryValueEx(distro, "BasePath")[0],
                    "version": winreg.QueryValueEx(distro, "Version")[0]}
        else:
            require(False, "wsl-distribution-count-limit")
    return result


def doctor() -> dict:
    require(os.name == "nt" and platform.machine().lower() in {"amd64", "x86_64"}, "windows-x86-64-required")
    result = process.run([backend.wsl_executable(), "--version"], Path(os.environ["SystemRoot"]), maximum=8192)
    require(result.returncode == 0, "wsl2-unavailable-install-wsl-and-reboot-explicitly")
    raw = result.stdout
    text = raw.decode("utf-16-le" if b"\0" in raw else "utf-8", errors="strict").strip()
    return {"host": "windows-x86_64", "windows": platform.version(), "wslVersionOutput": text,
            "distributionCount": len(registrations()), "nodeReadiness": "not-checked",
            "kernelChanges": False, "defaultDistributionChanges": False}


def _owned(record: dict) -> dict:
    registrations_now = registrations()
    require(record["distribution"] in registrations_now, "owned-wsl-distribution-missing")
    registration = registrations_now[record["distribution"]]
    observed = Path(registration["path"].removeprefix("\\\\?\\")).absolute()
    require(observed == Path(record["directory"]) and registration["version"] == 2, "wsl-owner-or-version-mismatch")
    if record.get("registration"):
        require(registration["registration"] == record["registration"], "wsl-registration-replaced")
    return registration


def _record(root: Path) -> dict:
    record = state.load(root, "wsl.json")
    require(record.get("schemaVersion") == "latent.dev.wsl.v1"
            and re.fullmatch(r"LSF-Dev-[a-f0-9]{16}", record["distribution"])
            and Path(record["directory"]) == root / record["distribution"], "invalid-owned-wsl-record")
    sha(record["helperSha256"])
    return record


def _user_call(root: Path, record: dict, mode: str, value: dict) -> dict:
    _owned(record)
    completed = process.run([backend.wsl_executable(), "--distribution", record["distribution"], "--user", "root",
        "--exec", *backend.guest_command(backend.GUEST_PYTHON, backend.HELPER, record["helperSha256"], mode)],
        root, stdin=encode(value), timeout=30, maximum=8192)
    if completed.returncode != 0:
        raise DevError("wsl-workspace-operation-unconfirmed-recover", uncertain=mode != "user-status")
    result = decode(completed.stdout)
    require(result.get("user") == value["user"], "wsl-user-response-identity")
    return result


def verify_workspace(root: Path, name: str, config: dict) -> None:
    record = _record(root)
    _owned(record)
    require(record["state"] == "provisioned" and name in record["workspaces"], "unrecorded-wsl-workspace")
    value = record["workspaces"][name]
    require(value["state"] == "ready" and config == {"kind": "wsl2", "distribution": record["distribution"],
            "user": value["owner"]["user"], "helperSha256": record["helperSha256"]}, "wsl-workspace-owner-mismatch")


def provision(root: Path, image: Path, expected_sha256: str, helper_sha256: str, *, consent: bool) -> dict:
    require(consent, "explicit-wsl-provision-consent-required")
    doctor()
    paths.private_root(root)
    with state.lock(root, "wsl.lock"), paths.opened(image.parent, image.name):
        require(not (root / "wsl.json").exists(), "wsl-provision-already-recorded-inspect-status")
        require(paths.digest_file(image.parent, image.name, 1024 * 1024 * 1024)[0] == sha(expected_sha256),
                "wsl-verified-image-mismatch")
        distribution = "LSF-Dev-" + secrets.token_hex(8)
        require(distribution not in registrations(), "wsl-distribution-collision")
        directory = root / distribution
        paths.new_directory(directory)
        record = {"schemaVersion": "latent.dev.wsl.v1", "distribution": distribution,
                  "directory": str(directory), "imageSha256": expected_sha256,
                  "helperSha256": sha(helper_sha256),
                  "registration": None, "state": "provisioning", "workspaces": {}}
        state.atomic(root, "wsl.json", record)
        try:
            # The Windows read handle forbids replacement or writing throughout import.
            result = process.run([backend.wsl_executable(), "--import", distribution, str(directory), str(image),
                                  "--version", "2"], root, timeout=300, maximum=65536)
            require(result.returncode == 0, "wsl-import-failed-inspect-recorded-distribution")
            registration = _owned(record)
            record.update(registration=registration["registration"], state="provisioned")
            state.atomic(root, "wsl.json", record)
            return record
        except BaseException:
            # A timed-out import may have committed. Never repeat it or unregister blindly.
            raise DevError("wsl-import-outcome-uncertain-inspect-status", uncertain=True) from None


def status(root: Path) -> dict:
    record = _record(root)
    if record["state"] == "purged":
        require(record["distribution"] not in registrations(), "purged-wsl-distribution-reappeared")
        return {"distribution": record["distribution"], "state": "purged", "registered": False}
    if record["distribution"] not in registrations():
        return {"distribution": record["distribution"], "state": record["state"], "registered": False,
                "uncertain": record["state"] not in {"purged"}}
    observed = _owned(record)
    return {"distribution": record["distribution"], "state": record["state"],
            "registered": True, "wslVersion": observed["version"],
            "workspaces": {name: value["state"] for name, value in sorted(record["workspaces"].items())}}


def workspace(root: Path, name: str, helper_sha256: str) -> dict:
    from .common import identifier
    identifier(name)
    with state.lock(root, "wsl.lock"):
        record = _record(root)
        _owned(record)
        require(record["state"] == "provisioned", "wsl-provisioning-needs-recovery")
        require(sha(helper_sha256) == record["helperSha256"], "helper-does-not-match-authenticated-image")
        workspaces = record["workspaces"]
        if name not in workspaces:
            require(sum(value["state"] != "removed" for value in workspaces.values()) < 8, "wsl-workspace-count-limit")
            user = "lsfd-" + secrets.token_hex(6)
            # The root provisioning helper is part of the already verified guest image.
            value = {"workspace": name, "user": user, "helperSha256": sha(helper_sha256), "nonce": secrets.token_hex(16)}
            workspaces[name] = {"owner": value, "state": "creating"}
            state.atomic(root, "wsl.json", record)
            result = _user_call(root, record, "create-user", value)
            require(result["state"] == "ready",
                    "wsl-workspace-provision-failed-no-adoption")
            workspaces[name]["state"] = "ready"
            state.atomic(root, "wsl.json", record)
        require(workspaces[name]["state"] == "ready", "wsl-workspace-creation-uncertain")
        return {"kind": "wsl2", "distribution": record["distribution"],
                "user": workspaces[name]["owner"]["user"], "helperSha256": helper_sha256}


def recover(root: Path, confirmation: str) -> dict:
    with state.lock(root, "wsl.lock"):
        record = _record(root)
        require(confirmation == record["distribution"], "confirm-exact-owned-wsl-distribution")
        if record["state"] == "purging" and record["distribution"] not in registrations():
            record["state"] = "purged"
        else:
            observed = _owned(record)
            if record["state"] == "provisioning":
                record.update(state="provisioned", registration=observed["registration"])
            for name, value in record["workspaces"].items():
                if value["state"] in {"creating", "removing"}:
                    actual = _user_call(root, record, "user-status" if value["state"] == "creating" else "remove-user", value["owner"])
                    require(actual["state"] in {"ready", "removed"}, "linux-user-provisioning-incomplete-inspect-owned-image")
                    value["state"] = actual["state"]
                    if actual["state"] == "removed":
                        state.atomic(state.workspace(root, name), "purged.json", {"workspace": name, "state": "purged"})
        state.atomic(root, "wsl.json", record)
    return status(root)


def remove_workspace(root: Path, name: str) -> dict:
    with state.lock(root, "wsl.lock"):
        record = _record(root)
        _owned(record)
        value = record["workspaces"][name]
        require(value["state"] in {"creating", "ready", "removing", "removed"}, "recover-wsl-workspace-before-removal")
        value["state"] = "removing"
        state.atomic(root, "wsl.json", record)
        result = _user_call(root, record, "remove-user", value["owner"])
        require(result["state"] == "removed", "wsl-user-removal-unconfirmed")
        value["state"] = "removed"
        state.atomic(root, "wsl.json", record)
        return result


def purge(root: Path, confirmation: str) -> dict:
    with state.lock(root, "wsl.lock"):
        record = _record(root)
        require(confirmation == record["distribution"], "confirm-exact-owned-wsl-distribution")
        if record["state"] == "purged":
            return status(root)
        _owned(record)
        require(all(value["state"] == "removed" for value in record["workspaces"].values()), "purge-each-workspace-before-wsl-removal")
        record["state"] = "purging"
        state.atomic(root, "wsl.json", record)
        completed = process.run([backend.wsl_executable(), "--unregister", record["distribution"]], root,
                                timeout=60, maximum=65536)
        require(completed.returncode == 0 and record["distribution"] not in registrations(), "wsl-purge-unconfirmed")
        record["state"] = "purged"
        state.atomic(root, "wsl.json", record)
        return {"state": "purged", "distribution": record["distribution"]}
