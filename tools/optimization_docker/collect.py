"""Finite Docker comparison; all workload and cleanup evidence remains local."""
from __future__ import annotations

import os
import base64
from pathlib import Path
import platform
import re
import shutil
import time

from tools.artifact_identity_runner.files import fingerprint, reference, retain, write_json
from tools.optimization_evidence.common import canonical, read_json, require, sha256
from tools.optimization_revision_runner.build import source
from . import build, fixtures, model, seeds
from .applications import Application, idle_window
from .engine import Engine
from .owned import Fleet, encoded, mount, stamp
from .session import Session


class Campaign:
    def __init__(self, args, repository):
        self.repository = repository.resolve()
        self.root, self.build_root = args.output.resolve(), args.build_root.resolve()
        self.profile, self.run_id, self.volume = args.profile, args.run_id, args.volume
        require(platform.system() == "Linux" and re.fullmatch(r"[a-z0-9-]{1,24}", self.run_id), "docker-linux-run-id")
        require(not self.root.exists() and self.root.is_relative_to(Path("/bench"))
                and self.build_root.is_relative_to(Path("/bench"))
                and not self.root.is_relative_to(self.build_root) and not self.build_root.is_relative_to(self.root),
                "docker-fresh-owned-output")
        self.source = source(self.repository)
        require(self.source["commit"] == args.source_ref, "docker-collector-source-ref")
        self.build = build.validate_receipt(read_json(self.build_root / "docker-builds.json"), self.build_root)
        self.images = read_json(self.build_root / "images.json")["images"]
        require(set(self.images) == {"lsf", "native", "client"}, "docker-image-set")
        self.root.mkdir(parents=True)
        with (self.root / "progress.ndjson").open("xb"):
            pass
        self.progress_count = self.progress_bytes = 0
        names = build.input_names(self.repository)
        self.collector_inputs, self.collector_build_inputs = {}, {}
        for name in names:
            if name.endswith(".py"):
                self.collector_inputs[name] = retain(self.repository / name, self.root / "collector/source" / name, self.root)
            else:
                digest, size = fingerprint(self.repository / name)
                self.collector_build_inputs[name] = {"sha256": digest, "bytes": str(size)}
        expected = {name: {"sha256": row["sha256"], "bytes": row["bytes"]}
                    for name, row in self.build["inputs"].items() if not name.endswith(".py")}
        require(self.collector_build_inputs == expected, "docker-build-non-python-inputs-changed")
        self.started = stamp()
        self.plan = model.plan(self.profile)
        write_json(self.root / "plan.json", self.plan)
        self.engine = Engine()
        self.fleet = Fleet(self.engine, self.root, self.run_id, int(self.started) + self.plan["collection_timeout_seconds"] * 10**9)
        self.attached, self.groups, self.clients = [], [], []
        self.fixture_mount = self.volume_mount(self.build_root / "fixtures", "/fixtures", True)
        self.controller_id = args.controller_id
        self.setup = []
        self.environment = {}

    def volume_mount(self, path, destination, readonly=False):
        return mount(self.volume, path.relative_to(Path("/bench")).as_posix(), destination, readonly)

    def progress(self, kind, value):
        data = encoded({"ordinal": self.progress_count, "observed_nanos": stamp(), "kind": kind, "value": value})
        require(self.progress_count < 20_000 and len(data) <= 2 * 1024**2
                and self.progress_bytes + len(data) <= 32 * 1024**2, "docker-progress-bound")
        with (self.root / "progress.ndjson").open("ab") as stream:
            stream.write(data)
        self.progress_count += 1
        self.progress_bytes += len(data)

    def reserve(self, additional):
        inventory = fixtures.inventory(self.root)
        require(int(inventory["bytes"]) + additional <= model.MAX_TOTAL_BYTES, "docker-evidence-total-bound")

    def reserve_active(self, arm, density, *, seed=False):
        owners = density if arm == "native" else 1
        wrapper = owners * (10 * 512 * 1024 + 2 * 256 * 1024)
        journals = model.MAX_FILE_BYTES - self.fleet.journal_bytes + 32 * 1024**2 - self.progress_bytes
        client = model.MAX_CLIENT_BYTES + 2 * 1024**2
        helpers = (2 * density + 2) * (2 * 1024**2 + 4096) if seed else 0
        # The fixed import-free guest does not receive a filesystem capability.
        # Include copied catalog data and parent metadata outside child streams.
        self.reserve(wrapper + journals + client + helpers + 64 * 1024**2)

    def observe_environment(self, stage):
        # Controller /proc describes the shared Linux VM, never a Windows host PID.
        raw = {}
        for name in ("stat", "meminfo", "loadavg", "pressure/cpu", "pressure/memory", "pressure/io"):
            path = Path("/proc") / name
            try:
                with path.open("rb") as stream:
                    data = stream.read(64 * 1024 + 1)
                require(len(data) <= 64 * 1024, "docker-environment-file-bound")
                raw[name] = {"value": data.decode(), "unavailable_reason": None}
            except OSError as error:
                raw[name] = {"value": None, "unavailable_reason": type(error).__name__}
        return {"stage": stage, "observed_nanos": stamp(), "raw": raw}

    def execute(self):
        failure = None
        cleanup = None
        try:
            version, _ = self.fleet.call("GET", "/version")
            info, _ = self.fleet.call("GET", "/info")
            require(info["OSType"] == "linux" and info["CgroupVersion"] == "2"
                    and all(info[key] is True for key in ("MemoryLimit", "SwapLimit", "CpuCfsPeriod", "CpuCfsQuota")),
                    "docker-required-linux-controls")
            require(not info.get("Warnings"), "docker-engine-warnings")
            self.environment = {"engine_version": version, "engine_info": info,
                                "engine_negotiation": {"response": self.engine.version,
                                    "receipt": self.engine.version_receipt,
                                    "response_bytes_base64": base64.b64encode(self.engine.version_body).decode("ascii")},
                                "controller_platform": platform.uname()._asdict(), "observations": []}
            for kind, expected in self.images.items():
                actual, _ = self.fleet.call("GET", "/images/" + expected["image_id"] + "/json")
                require(actual["Id"] == expected["image_id"] and actual["Config"] == expected["config"]
                        and actual["RootFS"] == expected["rootfs"], "docker-image-changed")
            self.fleet.create_network()
            self.environment["controller"] = self.fleet.connect_controller(self.controller_id)
            volume, _ = self.fleet.call("GET", "/volumes/" + self.volume)
            require(volume["Name"] == self.volume and volume["Labels"] == {"latent.benchmark.owner": "issue111-controller-01"}
                    and any(row["Type"] == "volume" and row.get("Name") == self.volume
                            and row["Destination"] == "/bench" and row["RW"] is True
                            for row in self.environment["controller"]["Mounts"]), "docker-owned-data-volume")
            self.environment["volume"] = volume
            self.environment["observations"].append(self.observe_environment("before-seeds"))
            templates = seeds.prepare(self)
            self.setup = [templates[density]["record"] for density in model.DENSITIES]
            for pair in range(self.plan["repetitions"]):
                self.reserve(model.MAX_CLIENT_BYTES + 128 * 1024**2)
                client = Session(self, pair)
                for group in model.groups(self.profile, pair):
                    self.group(pair, group, client, templates)
                self.clients.append(client.finish())
            self.environment["observations"].append(self.observe_environment("after-clients"))
            require(source(self.repository) == self.source, "docker-collector-source-changed")
        except BaseException as error:
            failure = {"type": type(error).__name__, "reason": str(error)[:2048]}
        finally:
            attachments = []
            for attached in self.attached:
                try:
                    attachments.append(attached.close())
                except BaseException as error:
                    attachments.append({"error": type(error).__name__})
            cleanup = self.fleet.close()
            write_json(self.root / "suite.json", {"schema": model.PREFIX + "suite.v1",
                       "profile": self.profile, "run_id": self.run_id, "plan": self.plan, "source": self.source,
                       "collection_path": str(self.root), "build_path": str(self.build_root),
                       "collector_inputs": self.collector_inputs,
                       "collector_build_inputs": self.collector_build_inputs,
                       "build_source": self.build["source"], "build_receipt": reference(self.build_root / "docker-builds.json", self.build_root),
                       "images": self.images, "volume": self.volume, "started_nanos": self.started,
                       "finished_nanos": stamp(), "environment": self.environment, "setup": self.setup,
                       "groups": self.groups, "clients": self.clients, "failed_attachments": attachments,
                       "failure": failure, "cleanup": cleanup})
        self.reserve(0)
        return 0 if failure is None and not cleanup["errors"] else 1

    def group(self, pair, group, client, templates):
        begin = stamp()
        arm, density, ordinal = group["arm"], group["density"], group["ordinal"]
        self.reserve_active(arm, density)
        applications = []
        for index in range(1 if arm == "lsf" else density):
            role = f"p{pair}-g{ordinal}-{arm}-{index}"
            applications.append(Application(self, role, arm, density,
                                            template=templates[density] if arm == "lsf" else None, service_index=index))
        targets = []
        for index in range(density):
            app = applications[0 if arm == "lsf" else index]
            targets.append({"service": model.SERVICES[index], "endpoint": app.endpoint,
                            "owner_ref": app.owner_ref, "app_process_id": app.app_pid})
        environment = self.observe_environment(f"pair-{pair}-group-{ordinal}-before")
        client.command("begin-group", ordinal, targets=targets)
        client.command("inventory", ordinal, barrier="ready")
        windows = [idle_window(applications, "ready")]
        client.observe(f"group-{ordinal}-ready")
        for phase in group["phases"]:
            client.command("phase", ordinal, phase=phase["ordinal"])
            if phase["ordinal"] == 0:
                client.command("inventory", ordinal, barrier="served")
                windows.append(idle_window(applications, "served"))
                client.observe(f"group-{ordinal}-served")
        client.command("inventory", ordinal, barrier="final")
        windows.append(idle_window(applications, "final"))
        client.observe(f"group-{ordinal}-final")
        client.command("finish-group", ordinal)
        owners = [app.finish() for app in applications]
        for app, owner in zip(applications, owners):
            owner["data_cleanup"] = None
            if app.data is not None:
                expected = (self.root / "data" / app.role).absolute()
                require(app.data.resolve() == expected and expected.is_relative_to(self.root / "data")
                        and app.container_id not in self.fleet.containers
                        and fixtures.inventory(expected) == owner["data_inventory"], "docker-owned-data-cleanup")
                absence = next(row["absence_call"] for row in self.fleet.cleanup_rows
                               if row["container_id"] == app.container_id)
                shutil.rmtree(expected)
                owner["data_cleanup"] = {"path": expected.relative_to(self.root).as_posix(),
                                         "inventory_sha256": sha256(canonical(owner["data_inventory"])),
                                         "container_absence_call": absence, "removed": not expected.exists()}
        result = {"pair": pair, "group": ordinal, "arm": arm, "density": density,
                  "started_nanos": begin, "finished_nanos": stamp(), "targets": targets,
                  "owners": owners, "windows": windows, "environment_before": environment,
                  "environment_after": self.observe_environment(f"pair-{pair}-group-{ordinal}-after")}
        self.groups.append(result)
        write_json(self.root / f"group-{pair}-{ordinal}.json", result)
        require(time.monotonic_ns() - int(begin) <= 600 * 10**9, "docker-group-deadline")
        self.reserve(64 * 1024**2)
        print(f"completed pair={pair} group={ordinal} arm={arm} density={density}", flush=True)


def execute(args, repository):
    return Campaign(args, repository).execute()
