"""Fresh app owners and observable, signal-bracketed resource windows."""
from __future__ import annotations

import json
from pathlib import Path
import time

from tools.artifact_identity_runner.files import write_json
from tools.optimization_evidence.common import require
from . import fixtures
from .model import SERVICES
from .owned import configuration, mount, stamp


class Application:
    def __init__(self, campaign, role, arm, density, *, template=None, service_index=0):
        self.campaign, self.role, self.arm, self.density = campaign, role, arm, density
        self.output = campaign.root / "owners" / role
        self.output.mkdir(parents=True)
        self.seen = []
        mounts = [campaign.fixture_mount, campaign.volume_mount(self.output, "/output")]
        if arm == "lsf":
            self.data = campaign.root / "data" / role
            if template is None:
                self.data.mkdir(parents=True)
                self.template_copy = None
            else:
                self.template_copy = fixtures.copy_template(template["path"], self.data, template["receipt"])
            mounts.append(campaign.volume_mount(self.data, "/data"))
        else:
            self.data, self.template_copy = None, None
        command = ["--app", arm, "--executable", "/opt/lsf/" + ("latentd" if arm == "lsf" else "optimization-native"),
                   "--output", "/output"]
        command += ["--config", "/fixtures/node.json"] if arm == "lsf" else [
            "--token-file", "/fixtures/token", "--service", SERVICES[service_index]]
        config = configuration(campaign.images[arm]["image_id"], command, arm=arm, density=density,
                               network=campaign.fleet.network, mounts=mounts, owner=campaign.fleet.owner, role=role)
        self.container_id = campaign.fleet.create(config, role)
        self.start = campaign.fleet.start(self.container_id)
        self.ready = self.wait_event("ready", deadline=time.monotonic_ns() + 120 * 10**9)
        self.ready_inspect = campaign.fleet.inspect(self.container_id)
        require(self.ready_inspect["State"]["Running"] and not self.ready_inspect["State"]["OOMKilled"],
                "docker-application-not-running")
        self.owner_ref = "owner-" + self.container_id
        self.endpoint = "http://" + role + ":7070"
        self.app_pid = self.ready["child_pid"]
        self.snapshots = []

    def events(self):
        path = self.output / "events.ndjson"
        if not path.exists():
            return []
        require(path.stat().st_size <= 5 * 1024**2, "docker-wrapper-events-bound")
        data = path.read_bytes()
        lines = data.splitlines(keepends=True)
        rows = [json.loads(line) for line in lines if line.endswith(b"\n")]
        require(len(rows) <= 10, "docker-wrapper-event-count")
        for index, row in enumerate(rows):
            require(row["schema"] == "latent.optimization.container-event.v1" and row["sequence"] == index
                    and row["app"] == self.arm and row["wrapper_pid"] == 1, "docker-wrapper-event-identity")
            if index >= len(self.seen):
                self.seen.append({"sequence": index, "observed_nanos": stamp()})
        return rows

    def wait_event(self, event, *, deadline, snapshot=None):
        while time.monotonic_ns() < min(deadline, self.campaign.fleet.deadline):
            rows = self.events()
            selected = [row for row in rows if row["event"] == event and (
                snapshot is None or row["detail"]["snapshot_index"] == snapshot)]
            if selected:
                require(len(selected) == 1, "docker-wrapper-duplicate-event")
                return selected[0]
            require(not any(row["event"] == "stopped" for row in rows), "docker-wrapper-exited-early")
            time.sleep(0.01)
        raise TimeoutError("docker-wrapper-event-deadline")

    def snapshot(self, index):
        before = stamp()
        call = self.campaign.fleet.signal(self.container_id, "SIGUSR1")
        event = self.wait_event("snapshot", deadline=time.monotonic_ns() + 10 * 10**9, snapshot=index)
        result = {"snapshot_index": index, "signal_before_nanos": before, "call": call,
                  "observed_nanos": stamp(), "event_sequence": event["sequence"]}
        self.snapshots.append(result)
        return result

    def finish(self):
        stopped = self.campaign.fleet.finish(self.container_id)
        rows = self.events()
        require(rows and rows[-1]["event"] == "stopped", "docker-wrapper-missing-stop")
        result = {"role": self.role, "arm": self.arm, "density": self.density,
                  "container_id": self.container_id, "owner_ref": self.owner_ref, "endpoint": self.endpoint,
                  "app_process_id": self.app_pid, "output": self.output.relative_to(self.campaign.root).as_posix(),
                  "start": self.start, "ready_inspect": self.ready_inspect, "final": stopped,
                  "event_observations": self.seen, "snapshots": self.snapshots, "template_copy": self.template_copy,
                  "data_inventory": fixtures.inventory(self.data) if self.data is not None else None}
        self.campaign.fleet.remove(self.container_id)
        return result


def idle_window(applications, stage):
    require(stage in ("ready", "served", "final"), "docker-idle-stage")
    index = {"ready": 1, "served": 3, "final": 5}[stage]
    started = stamp()
    before = [app.snapshot(index) for app in applications]
    sleep_begin = stamp()
    time.sleep(0.25)
    sleep_end = stamp()
    after = [app.snapshot(index + 1) for app in applications]
    return {"stage": stage, "started_nanos": started, "before": before,
            "sleep_begin_nanos": sleep_begin, "sleep_end_nanos": sleep_end,
            "after": after, "finished_nanos": stamp()}
