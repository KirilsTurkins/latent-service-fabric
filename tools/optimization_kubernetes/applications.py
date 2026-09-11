"""Fresh real Pods with original wrapper output and identity-checked signals."""
from __future__ import annotations

import json
from pathlib import Path
import time

from tools.artifact_identity_runner.files import write_json
from tools.optimization_docker import fixtures
from tools.optimization_docker.owned import stamp
from tools.optimization_evidence.common import require
from . import model, node


class Application:
    def __init__(self, campaign, pair, group, index):
        self.campaign = campaign
        self.arm, self.density = group["arm"], group["density"]
        self.role = model.application_role(pair, group["ordinal"], self.arm, index)
        self.output = campaign.root / "owners" / self.role
        self.output.mkdir(parents=True)
        self.remote_output = campaign.prepare_directory("owners/" + self.role)
        self.template_copy = None
        remote_data = None
        if self.arm == "lsf":
            seed = campaign.seeds[self.density]
            data = campaign.root / "inputs/data" / self.role
            self.template_copy = fixtures.copy_template(seed["path"], data, seed["template"])
            remote_data = campaign.prepare_directory("data/" + self.role, data)
        command = ["--app", self.arm, "--executable", "/opt/lsf/" + (
            "latentd" if self.arm == "lsf" else "optimization-native"), "--output", "/output"]
        command += ["--config", "/fixtures/node.json"] if self.arm == "lsf" else [
            "--token-file", "/fixtures/token", "--service", model.SERVICES[index]]
        self.manifest = model.pod(campaign.images[self.arm], command, arm=self.arm, density=self.density,
            owner=campaign.owner, run_id=campaign.run_id, role=self.role, fixtures=campaign.remote_fixtures,
            output=self.remote_output, data=remote_data)
        write_json(self.output / "manifest.json", self.manifest)
        self.buffer, self.offset, self.events, self.event_observations = bytearray(), 0, [], []
        self.snapshots, self.observations = [], []
        self.record = {"role": self.role, "arm": self.arm, "density": self.density,
            "manifest": self.manifest, "template_copy": self.template_copy,
            "remote_output": self.remote_output, "remote_data": remote_data,
            "directory": self.output.relative_to(campaign.root).as_posix()}

    def create(self):
        self.created = self.campaign.create_pod(self.manifest)
        self.uid = self.created["pod"]["metadata"]["uid"]
        self.record["create"] = self.created

    def ready(self):
        self.pod_ready, call = self.campaign.wait_pod(self.role, "running")
        require(self.pod_ready["metadata"]["uid"] == self.uid, "kubernetes-application-pod-replaced")
        self.container_id = self.pod_ready["status"]["containerStatuses"][0]["containerID"].removeprefix("containerd://")
        self.cri_ready, cri_call = self.campaign.worker.json(["crictl", "inspect", self.container_id])
        event = self.wait_event("ready")
        self.app_pid = event["child_pid"]
        self.owner_ref = "owner-" + self.container_id
        raw, identity_call = self.campaign.worker.command(["cat", f"/proc/{self.cri_ready['info']['pid']}/stat"])
        head, separator, tail = raw.decode().rpartition(") ")
        require(separator and head.startswith(str(self.cri_ready["info"]["pid"]) + " ("),
                "kubernetes-application-host-pid")
        self.start_ticks = tail.split()[19]
        self.record.update(pod_ready=self.pod_ready, ready_call=call, cri_ready=self.cri_ready,
            cri_ready_call=cri_call, identity_call=identity_call, start_time_ticks=self.start_ticks,
            app_process_id=self.app_pid, owner_ref=self.owner_ref, container_id=self.container_id)
        self.campaign.progress("application-ready", self.record)

    def read_events(self):
        raw, call = self.campaign.worker.command(["tail", "-c", "+" + str(self.offset + 1),
                                                  self.remote_output + "/events.ndjson"])
        self.offset += len(raw)
        require(self.offset <= 10 * 512 * 1024, "kubernetes-wrapper-event-byte-bound")
        self.buffer.extend(raw)
        while (end := self.buffer.find(b"\n")) >= 0:
            require(end + 1 <= 512 * 1024 and len(self.events) < 10, "kubernetes-wrapper-event-line-bound")
            line = bytes(self.buffer[:end + 1])
            del self.buffer[:end + 1]
            value = json.loads(line)
            require(value["schema"] == "latent.optimization.container-event.v1"
                    and value["sequence"] == len(self.events) and value["app"] == self.arm
                    and value["wrapper_pid"] == 1, "kubernetes-wrapper-event-identity")
            self.events.append(value)
            self.event_observations.append({"sequence": value["sequence"], "observed_nanos": stamp(), "call": call})
        return self.events

    def wait_event(self, event, snapshot=None):
        until = time.monotonic() + (40 if event == "stopped" else 15)
        while time.monotonic() < until:
            rows = self.read_events()
            matches = [row for row in rows if row["event"] == event and (
                snapshot is None or row["detail"]["snapshot_index"] == snapshot)]
            if matches:
                require(len(matches) == 1, "kubernetes-wrapper-duplicate-event")
                return matches[0]
            require(not rows or rows[-1]["event"] != "stopped", "kubernetes-wrapper-stopped-early")
            time.sleep(0.01)
        raise TimeoutError("kubernetes-wrapper-event-deadline")

    def signal(self, name):
        return self.campaign.worker.command(["sh", self.campaign.observer, "signal",
            str(self.cri_ready["info"]["pid"]), self.container_id, self.start_ticks, name])[1]

    def snapshot(self, index):
        started = stamp()
        call = self.signal("USR1")
        event = self.wait_event("snapshot", index)
        observed = stamp()
        raw, node_call = self.campaign.worker.command(["sh", self.campaign.observer, "observe",
            str(self.cri_ready["info"]["pid"]), self.container_id, self.start_ticks])
        facts = node.observation(raw, index, observed, stamp())
        self.observations.append(facts)
        row = {"snapshot_index": index, "signal_before_nanos": started, "call": call,
               "observed_nanos": observed, "event_sequence": event["sequence"], "node_call": node_call,
               "node_finished_nanos": facts["finished_nanos"]}
        self.snapshots.append(row)
        self.campaign.progress("application-snapshot", {"container_id": self.container_id, **row})
        return row

    def finish(self):
        signal_call = self.signal("TERM")
        event = self.wait_event("stopped")
        require(event["detail"]["clean"] is True and not self.buffer, "kubernetes-wrapper-not-clean")
        pod, call = self.campaign.wait_pod(self.role, "succeeded")
        cri, cri_call = self.campaign.worker.json(["crictl", "inspect", self.container_id])
        download = self.campaign.download_directory(self.remote_output, self.output / "raw")
        original = (self.output / "raw/events.ndjson").read_bytes()
        require(len(original) == self.offset and [json.loads(line) for line in original.splitlines()] == self.events,
                "kubernetes-wrapper-downloaded-events-changed")
        self.record.update(pod_final=pod, final_call=call, cri_final=cri, cri_final_call=cri_call,
            stop_signal_call=signal_call, snapshots=self.snapshots, observations=self.observations,
            event_observations=self.event_observations, download=download,
            raw_directory=(self.output / "raw").relative_to(self.campaign.root).as_posix())
        self.record["delete"] = self.campaign.delete_pod(pod)
        write_json(self.output / "parent.json", self.record)
        return self.record


def idle_window(applications, stage):
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
