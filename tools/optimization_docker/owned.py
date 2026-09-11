"""Explicit Docker identities, bounded API journal, and owned container cleanup."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import time
from urllib.parse import quote

from tools.artifact_identity_runner.files import write_json
from tools.optimization_evidence.common import require
from .model import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES, PREFIX, resources

LABEL = "latent.benchmark.owner"
ROLE = "latent.benchmark.role"


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()


def stamp():
    return str(time.monotonic_ns())


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "docker-full-id")
    return value


def mount(volume, subpath, destination, readonly=False):
    require(isinstance(subpath, str) and subpath and not subpath.startswith("/")
            and ".." not in Path(subpath).parts, "docker-volume-subpath")
    return {"Type": "volume", "Source": volume, "Target": destination, "ReadOnly": readonly,
            "VolumeOptions": {"NoCopy": True, "Subpath": subpath}}


def configuration(image, command, *, arm, density, network, mounts, owner, role, interactive=False):
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image) is not None, "docker-pinned-image")
    limits = resources(arm, density)
    return {"Image": image, "Cmd": command, "Labels": {LABEL: owner, ROLE: role},
            "Hostname": role, "OpenStdin": interactive, "StdinOnce": False,
            "AttachStdin": interactive, "AttachStdout": True, "AttachStderr": True, "Tty": False,
            "StopSignal": "SIGTERM", "StopTimeout": 30,
            "HostConfig": {"NetworkMode": network, "AutoRemove": False, "ReadonlyRootfs": True,
                           "CpuPeriod": limits["cpu_period"], "CpuQuota": limits["cpu_quota"],
                           "Memory": limits["memory"], "MemorySwap": limits["memory_swap"],
                           "PidsLimit": limits["pids_limit"], "CapDrop": ["ALL"],
                           "SecurityOpt": ["no-new-privileges"], "Ulimits": [
                               {"Name": "nofile", "Soft": 1024, "Hard": 1024}],
                           "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16777216"},
                           "LogConfig": {"Type": "local", "Config": {"max-size": "8m", "max-file": "1"}},
                           "Mounts": mounts},
            "NetworkingConfig": {"EndpointsConfig": {network: {"Aliases": [role]}}}}


class Fleet:
    def __init__(self, engine, directory: Path, owner: str, deadline: int):
        require(re.fullmatch(r"[a-z0-9-]{1,48}", owner) is not None, "docker-owner-name")
        self.engine, self.root, self.owner, self.deadline = engine, directory, owner, deadline
        self.journal = (directory / "engine.ndjson").open("xb")
        self.journal_bytes = self.calls = 0
        self.containers, self.pending_names, self.network = {}, {}, None
        self.controller = None
        self.used_roles, self.network_attempted = set(), False
        self.cleanup_rows = []

    def call(self, method, path, body=None, *, expected=(200,), timeout=30, cleanup=False):
        require(cleanup or time.monotonic_ns() < self.deadline, "docker-collection-deadline")
        row = {"ordinal": self.calls, "method": method, "path": path, "request": body, "response": None,
               "receipt": None, "error": None}
        self.calls += 1
        require(self.calls <= 20_000, "docker-api-call-bound")
        try:
            value, receipt = self.engine.request(method, path, body, expected=expected, timeout=timeout)
            row.update(response=value, receipt=receipt)
            return value, row
        except BaseException as error:
            row.update(error=type(error).__name__, receipt=getattr(error, "receipt", None))
            raise
        finally:
            raw = getattr(self.engine, "last_body", b"")
            row["response_bytes_base64"] = base64.b64encode(raw).decode("ascii")
            data = encoded(row)
            require(self.journal_bytes + len(data) <= MAX_FILE_BYTES, "docker-api-journal-bound")
            self.journal.write(data)
            self.journal.flush()
            self.journal_bytes += len(data)

    def create_network(self):
        name = self.owner + "-bridge"
        self.call("GET", "/networks/" + name, expected=(404,))
        body = {"Name": name, "CheckDuplicate": True, "Driver": "bridge", "Internal": True,
                "Attachable": False, "EnableIPv6": False, "Labels": {LABEL: self.owner, ROLE: "bridge"}}
        self.network_attempted = True
        try:
            value, _ = self.call("POST", "/networks/create", body, expected=(201,))
            self.network = identifier(value["Id"])
        finally:
            # Reconcile a create whose response was lost by its unique name and labels.
            value, _ = self.call("GET", "/networks/" + name, expected=(200, 404), cleanup=True)
            if isinstance(value, dict) and value.get("Labels") == body["Labels"] and value.get("Name") == name:
                self.network = identifier(value["Id"])
        require(self.network is not None, "docker-network-create")
        value, _ = self.call("GET", "/networks/" + self.network)
        require(value["Driver"] == "bridge" and value["Internal"] is True and not value["Containers"],
                "docker-private-empty-bridge")
        return self.network

    def create(self, config, role):
        name = self.owner + "-" + role
        require(len(name) <= 128 and role not in self.used_roles, "docker-container-name")
        self.call("GET", "/containers/" + name + "/json", expected=(404,))
        self.used_roles.add(role)
        self.pending_names[role] = {"name": name, "config": config}
        try:
            value, _ = self.call("POST", "/containers/create?name=" + quote(name), config, expected=(201,))
            container_id = identifier(value["Id"])
            require(not value.get("Warnings"), "docker-container-create-warnings")
            self.containers[container_id] = {"role": role, "name": name, "config": config}
        finally:
            value, _ = self.call("GET", "/containers/" + name + "/json", expected=(200, 404), cleanup=True)
            if isinstance(value, dict) and value.get("Config", {}).get("Labels") == config["Labels"]:
                container_id = identifier(value["Id"])
                self.containers[container_id] = {"role": role, "name": name, "config": config}
        require(any(row["role"] == role for row in self.containers.values()), "docker-container-create")
        self.pending_names.pop(role, None)
        return container_id

    def connect_controller(self, container_id):
        identifier(container_id)
        value, _ = self.call("GET", f"/containers/{container_id}/json")
        require(value["Id"] == container_id and value["State"]["Running"] is True
                and value["Config"]["Labels"].get(LABEL) == "issue111-controller-01",
                "docker-controller-ownership")
        self.controller = container_id
        self.call("POST", f"/networks/{self.network}/connect", {"Container": container_id}, expected=(200,))
        return value

    def inspect(self, container_id, *, cleanup=False):
        identifier(container_id)
        require(container_id in self.containers, "docker-container-not-owned")
        value, _ = self.call("GET", f"/containers/{container_id}/json", cleanup=cleanup)
        row = self.containers[container_id]
        require(value["Id"] == container_id and value["Name"] == "/" + row["name"]
                and value["Config"]["Labels"] == row["config"]["Labels"]
                and value["Image"] == row["config"]["Image"], "docker-inspect-ownership")
        return value

    def start(self, container_id):
        require(container_id in self.containers, "docker-container-not-owned")
        before = stamp()
        _, call = self.call("POST", f"/containers/{container_id}/start", expected=(204,))
        return {"started_nanos": before, "finished_nanos": stamp(), "call": call["ordinal"]}

    def signal(self, container_id, signal):
        require(container_id in self.containers and signal in ("SIGUSR1", "SIGTERM"), "docker-owned-signal")
        _, call = self.call("POST", f"/containers/{container_id}/kill?signal={signal}", expected=(204,))
        return call["ordinal"]

    def finish(self, container_id, *, already_exited=False):
        before = self.inspect(container_id, cleanup=True)
        if before["State"]["Running"] and not already_exited:
            self.call("POST", f"/containers/{container_id}/stop?t=30", expected=(204,), timeout=40, cleanup=True)
        waited, _ = self.call("POST", f"/containers/{container_id}/wait?condition=not-running", timeout=40, cleanup=True)
        final = self.inspect(container_id, cleanup=True)
        require(waited["StatusCode"] == final["State"]["ExitCode"] and not final["State"]["Running"],
                "docker-wait-exit-mismatch")
        return {"wait": waited, "inspect": final}

    def remove(self, container_id):
        value = self.inspect(container_id, cleanup=True)
        require(not value["State"]["Running"], "docker-remove-running-owner")
        self.call("DELETE", f"/containers/{container_id}?v=false&force=false", expected=(204,), cleanup=True)
        _, gone = self.call("GET", f"/containers/{container_id}/json", expected=(404,), cleanup=True)
        self.cleanup_rows.append({"container_id": container_id, "name": value["Name"],
                                  "removed": True, "absence_call": gone["ordinal"],
                                  "exit_code": value["State"]["ExitCode"], "oom_killed": value["State"]["OOMKilled"]})
        del self.containers[container_id]

    def close(self):
        errors = []
        for role, pending in list(self.pending_names.items()):
            try:
                value, call = self.call("GET", "/containers/" + pending["name"] + "/json",
                                        expected=(200, 404), cleanup=True)
                if call["receipt"]["status"] == 200:
                    require(value["Config"]["Labels"] == pending["config"]["Labels"]
                            and value["Name"] == "/" + pending["name"], "docker-lost-create-ownership")
                    container_id = identifier(value["Id"])
                    self.containers[container_id] = {"role": role, **pending}
                del self.pending_names[role]
            except BaseException as error:
                errors.append({"pending_name": pending["name"], "error": type(error).__name__})
        if self.network is None and self.network_attempted:
            try:
                name = self.owner + "-bridge"
                value, call = self.call("GET", "/networks/" + name, expected=(200, 404), cleanup=True)
                if call["receipt"]["status"] == 200:
                    require(value["Labels"] == {LABEL: self.owner, ROLE: "bridge"} and value["Name"] == name,
                            "docker-lost-network-create-ownership")
                    self.network = identifier(value["Id"])
            except BaseException as error:
                errors.append({"pending_network": name, "error": type(error).__name__})
        for container_id in list(self.containers):
            try:
                self.finish(container_id)
                self.remove(container_id)
            except BaseException as error:
                errors.append({"container_id": container_id, "error": type(error).__name__})
        if self.network is not None:
            try:
                if self.controller is not None:
                    self.call("POST", f"/networks/{self.network}/disconnect",
                              {"Container": self.controller, "Force": False}, expected=(200,), cleanup=True)
                value, _ = self.call("GET", "/networks/" + self.network, cleanup=True)
                require(value["Labels"] == {LABEL: self.owner, ROLE: "bridge"} and not value["Containers"],
                        "docker-network-remove-ownership")
                self.call("DELETE", "/networks/" + self.network, expected=(204,), cleanup=True)
                self.call("GET", "/networks/" + self.network, expected=(404,), cleanup=True)
            except BaseException as error:
                errors.append({"network_id": self.network, "error": type(error).__name__})
        self.journal.close()
        value = {"schema": PREFIX + "cleanup.v1", "containers": self.cleanup_rows,
                 "network_id": self.network, "network_removed": self.network is not None and not errors,
                 "errors": errors, "remaining_containers": list(self.containers), "journal_closed": self.journal.closed}
        value["pending_names"] = [row["name"] for row in self.pending_names.values()]
        write_json(self.root / "cleanup.json", value)
        return value
