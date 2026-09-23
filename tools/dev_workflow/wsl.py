"""A recorded WSL2 distro; no global/default distribution or kernel changes."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import secrets

from . import backend, paths, process, state
from .common import DevError, decode, digest, encode, members, require, sha


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


def provision(root: Path, image: Path, expected_sha256: str, *, consent: bool) -> dict:
    require(consent, "explicit-wsl-provision-consent-required")
    doctor()
    paths.private_root(root)
    with state.lock(root, "wsl.lock"):
        require(not (root / "wsl.json").exists(), "wsl-provision-already-recorded-inspect-status")
        require(digest(paths.read(image.parent, image.name, 1024 * 1024 * 1024)) == sha(expected_sha256),
                "wsl-verified-image-mismatch")
        distribution = "LSF-Dev-" + secrets.token_hex(8)
        require(distribution not in registrations(), "wsl-distribution-collision")
        directory = root / distribution
        paths.new_directory(directory)
        record = {"schemaVersion": "latent.dev.wsl.v1", "distribution": distribution,
                  "directory": str(directory), "imageSha256": expected_sha256,
                  "registration": None, "state": "provisioning", "workspaces": {}}
        state.atomic(root, "wsl.json", record)
        try:
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
    record = state.load(root, "wsl.json")
    observed = _owned(record)
    return {"distribution": record["distribution"], "state": record["state"],
            "registered": True, "wslVersion": observed["version"], "workspaces": sorted(record["workspaces"])}


def workspace(root: Path, name: str, helper_sha256: str) -> dict:
    from .common import identifier
    identifier(name)
    with state.lock(root, "wsl.lock"):
        record = state.load(root, "wsl.json")
        _owned(record)
        require(record["state"] == "provisioned", "wsl-provisioning-needs-recovery")
        workspaces = record["workspaces"]
        if name not in workspaces:
            require(len(workspaces) < 8, "wsl-workspace-count-limit")
            user = "lsfd-" + secrets.token_hex(6)
            # The root provisioning helper is part of the already verified guest image.
            value = {"workspace": name, "user": user, "helperSha256": sha(helper_sha256)}
            workspaces[name] = {**value, "state": "creating"}
            state.atomic(root, "wsl.json", record)
            completed = process.run([backend.wsl_executable(), "--distribution", record["distribution"],
                "--user", "root", "--exec", "/usr/bin/python3", "-I", backend.HELPER, "create-user"], root,
                stdin=encode(value), timeout=30, maximum=8192)
            require(completed.returncode == 0 and decode(completed.stdout).get("user") == user,
                    "wsl-workspace-provision-failed-no-adoption")
            workspaces[name]["state"] = "ready"
            state.atomic(root, "wsl.json", record)
        require(workspaces[name]["state"] == "ready", "wsl-workspace-creation-uncertain")
        return {"kind": "wsl2", "distribution": record["distribution"],
                "user": workspaces[name]["user"], "helperSha256": helper_sha256}


def purge(root: Path, confirmation: str) -> dict:
    with state.lock(root, "wsl.lock"):
        record = state.load(root, "wsl.json")
        require(confirmation == record["distribution"], "confirm-exact-owned-wsl-distribution")
        _owned(record)
        require(not record["workspaces"], "purge-each-workspace-before-wsl-removal")
        completed = process.run([backend.wsl_executable(), "--unregister", record["distribution"]], root,
                                timeout=60, maximum=65536)
        require(completed.returncode == 0 and record["distribution"] not in registrations(), "wsl-purge-unconfirmed")
        record["state"] = "purged"
        state.atomic(root, "wsl.json", record)
        return {"state": "purged", "distribution": record["distribution"]}
