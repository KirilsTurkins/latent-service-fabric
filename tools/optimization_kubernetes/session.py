"""One owned Pod/attach session for the unchanged infrastructure client protocol."""
from __future__ import annotations

import re
import time

from tools.artifact_identity_runner.files import write_json
from tools.optimization_docker.client_evidence import _plan, _read, _sequence
from tools.optimization_docker.owned import encoded, stamp
from tools.optimization_evidence.common import canonical, decode, digest, fields, require, sha256, text, uint
from . import model
from .attach import Attach


class Session:
    def __init__(self, campaign, pair):
        self.campaign, self.pair = campaign, pair
        self.plan = {"schema": model.CLIENT_PREFIX + "plan.v1", "run_id": campaign.run_id,
                     "profile": campaign.profile, "pair": pair, "token_file": "/fixtures/token"}
        self.groups = _plan(self.plan)
        self.sequence = _sequence(self.groups)
        self.role = model.client_role(pair)
        require(campaign.namespace == model.namespace_name(campaign.owner, campaign.run_id),
                "kubernetes-client-namespace")
        self.root = campaign.root / "clients" / str(pair)
        self.root.mkdir(parents=True)
        write_json(self.root / "plan.json", self.plan)
        self.plan_bytes = _read(self.root / "plan.json", 4096)
        self.digest = sha256(self.plan_bytes)
        self.commands, self.acknowledgements, self.observations, self.ack_lines = [], [], [], []
        self.events_offset = self.attempt_bytes = self.command_bytes = 0
        self.attach = None
        self.record = {"pair": pair, "plan": self.plan,
            "directory": (self.root / "raw").relative_to(campaign.root).as_posix(),
            "parent_directory": self.root.relative_to(campaign.root).as_posix()}
        self.started = time.monotonic()
        try:
            # Upload the input before creating journals; client output cannot overwrite them.
            self.remote = campaign.prepare_directory("clients/" + str(pair), self.root)
            require(self.remote == model.host_path(campaign.owner, campaign.run_id, "clients/" + str(pair)),
                    "kubernetes-client-output-owner")
            for name in ("parent-commands.ndjson", "parent-acks.ndjson", "parent-observations.ndjson"):
                (self.root / name).open("xb").close()
            self.manifest = model.pod(campaign.images["client"],
                ["--session", "/output/plan.json", "--output", "/output"], arm="client", density=1,
                owner=campaign.owner, run_id=campaign.run_id, role=self.role,
                fixtures=campaign.remote_fixtures, output=self.remote)
            write_json(self.root / "manifest.json", self.manifest)
            self.record.update(remote_directory=self.remote, manifest=self.manifest)
            self.record["create"] = campaign.create_pod(self.manifest)
            self.uid = self.record["create"]["pod"]["metadata"]["uid"]
            campaign.progress("client-created", self.record)
            self.pod_ready, call = campaign.wait_pod(self.role, "running")
            self._pod(self.pod_ready, "Running")
            self.record["ready"] = {"pod": self.pod_ready, "call": call}
            self.record["initial_log"] = self._initial_log()
            argv = [str(campaign.kubectl), "--kubeconfig", str(campaign.kubeconfig),
                    "--context", "kind-" + campaign.owner,
                    "--server", "https://" + campaign.owner + "-control-plane:6443",
                    "-n", campaign.namespace, "attach", "-i", self.role, "-c", "client", "--quiet=true"]
            self.attach = Attach(argv, self.root)
            campaign.progress("client-attached", {"pair": pair, "argv": argv,
                "process_id": self.attach.child.pid, "start_time_ticks": self.attach.start_ticks})
            self.observe("ready")
        except BaseException as error:
            self._failed(error)
            raise

    def _append(self, name, row):
        with (self.root / name).open("ab") as stream:
            stream.write(encoded(row))

    def _retain(self, name, data):
        with (self.root / name).open("xb") as stream:
            stream.write(data)
        return {"path": (self.root / name).relative_to(self.campaign.root).as_posix(),
                "bytes": str(len(data)), "sha256": sha256(data)}

    def _pod(self, pod, phase):
        require(pod["metadata"]["uid"] == self.uid and pod["metadata"]["name"] == self.role
                and pod["metadata"]["namespace"] == self.campaign.namespace
                and pod["metadata"].get("deletionTimestamp") is None
                and pod["spec"]["nodeName"] == self.campaign.worker_name
                and pod["status"]["phase"] == phase, "kubernetes-client-pod-identity")
        rows = pod["status"]["containerStatuses"]
        require(len(rows) == 1 and rows[0]["name"] == "client"
                and type(rows[0]["restartCount"]) is int and rows[0]["restartCount"] == 0
                and not rows[0].get("lastState"), "kubernetes-client-restarted")
        row = rows[0]
        require(re.fullmatch(r"containerd://[0-9a-f]{64}", row["containerID"]) is not None,
                "kubernetes-client-container-id")
        text(row["imageID"], 512)
        if phase == "Running":
            require(set(row["state"]) == {"running"}, "kubernetes-client-not-running")
            self.container_id, self.image_id = row["containerID"], row["imageID"]
        else:
            require(row["containerID"] == self.container_id and row["imageID"] == self.image_id
                    and set(row["state"]) == {"terminated"}, "kubernetes-client-container-replaced")
            end = row["state"]["terminated"]
            require(type(end["exitCode"]) is int and end["exitCode"] == 0
                    and type(end.get("signal", 0)) is int and end.get("signal", 0) == 0,
                    "kubernetes-client-exit")

    def _logs(self):
        return self.campaign.api.call("GET", "/api/v1/namespaces/" + self.campaign.namespace
            + "/pods/" + self.role + "/log?container=client", json_response=False)

    def _initial_log(self):
        until, calls = time.monotonic() + 120, []
        while True:
            require(time.monotonic() < until and len(calls) < 1200, "kubernetes-client-ready-deadline")
            raw, call = self._logs()
            received = stamp()
            calls.append(call)
            # Every API response, including empties, is retained by the transport journal.
            self.record["initial_log_calls"] = calls
            if raw:
                ref = self._retain("initial-pod-stdout.log", raw)
                self.ready = self._ack(raw, "ready", None, received)
                return {"call": call, "calls": calls, **ref}
            time.sleep(0.1)

    def _ack(self, line, event, ordinal, received=None):
        require(isinstance(line, bytes) and 1 < len(line) <= 4096
                and line.endswith(b"\n") and b"\n" not in line[:-1], "kubernetes-client-ack-line")
        ack = decode(line, 4096)
        row = {"ack": ack, "received_nanos": received or stamp()}
        self.ack_lines.append(line)
        self.acknowledgements.append(row)
        self._append("parent-acks.ndjson", row)
        require(len(self.acknowledgements) <= 68, "kubernetes-client-ack-count")
        base = "schema event command_ordinal process_id plan_sha256 "
        fields(ack, base + ("summary" if event == "complete" else "event_record attempts"))
        require(ack["schema"] == model.CLIENT_PREFIX + "ack.v1"
                and ack["plan_sha256"] == self.digest and type(ack["process_id"]) is int
                and ack["process_id"] == 1 and ack["event"] == event
                and canonical(ack["command_ordinal"]) == canonical(ordinal),
                "kubernetes-client-ack-order-identity")
        if event == "complete":
            self._reference(ack["summary"], "summary.json", 16 * 1024)
        else:
            ref = ack["event_record"]
            fields(ref, "path offset bytes sha256")
            require(ref["path"] == "events.jsonl" and uint(ref["offset"]) == self.events_offset
                    and 0 < uint(ref["bytes"]) <= 2 * 1024**2, "kubernetes-client-event-reference")
            digest(ref["sha256"])
            self.events_offset += uint(ref["bytes"])
            prefix = self._reference(ack["attempts"], "attempts.jsonl", model.MAX_CLIENT_BYTES)
            require(self.attempt_bytes <= prefix, "kubernetes-client-attempt-prefix-order")
            self.attempt_bytes = prefix
            require(self.events_offset + prefix <= model.MAX_CLIENT_BYTES, "kubernetes-client-output-bound")
            if event == "ready":
                require(prefix == 0 and ack["attempts"]["sha256"] == sha256(b""),
                        "kubernetes-client-ready-attempts")
        return ack

    @staticmethod
    def _reference(ref, path, maximum):
        fields(ref, "path bytes sha256")
        size = uint(ref["bytes"])
        require(ref["path"] == path and size <= maximum, "kubernetes-client-file-reference")
        digest(ref["sha256"])
        return size

    def command(self, command, group=None, *, phase=None, barrier=None, targets=None):
        try:
            ordinal = len(self.commands)
            require(ordinal < len(self.sequence) and time.monotonic() - self.started <= 1800
                    and canonical([command, group, phase, barrier]) == canonical(self.sequence[ordinal]),
                    "kubernetes-client-command-order")
            if command == "begin-group":
                require(isinstance(targets, list) and len(targets) == self.groups[group]["density"],
                        "kubernetes-client-target-count")
                for index, target in enumerate(targets):
                    fields(target, "service endpoint owner_ref app_process_id")
                    require(target["service"] == model.SERVICES[index]
                            and type(target["app_process_id"]) is int and target["app_process_id"] > 0,
                            "kubernetes-client-target-identity")
                    text(target["endpoint"], 4096)
                    text(target["owner_ref"], 128)
            else:
                require(targets is None, "kubernetes-client-unexpected-targets")
            value = {"schema": model.CLIENT_PREFIX + "command.v1", "ordinal": ordinal,
                "plan_sha256": self.digest, "command": command, "group": group,
                "phase": phase, "barrier": barrier, "targets": targets}
            line = encoded(value)
            self.command_bytes += len(line)
            require(len(line) <= 64 * 1024 and self.command_bytes <= 1024**2,
                    "kubernetes-client-command-bound")
            row = {"line": line.decode("utf-8"), "sent_nanos": stamp()}
            self.commands.append(row)
            self._append("parent-commands.ndjson", row)
            self.attach.send_line(line)
            if command == "phase" and phase == 0:
                self._ack(self.attach.next_line(timeout=120), "first-response", ordinal)
            expected = {"begin-group": "group-ready", "inventory": "inventory", "phase": "phase-complete",
                        "finish-group": "group-finished", "finish": "complete"}[command]
            return self._ack(self.attach.next_line(timeout=120), expected, ordinal)
        except BaseException as error:
            self._failed(error)
            raise

    def observe(self, stage):
        expected = ["ready"] + [f"group-{group}-{barrier}" for group in range(6)
                                for barrier in ("ready", "served", "final")]
        require(len(self.observations) < len(expected) and stage == expected[len(self.observations)],
                "kubernetes-client-observation-order")
        value = self.campaign.observe_client(self.pod_ready, stage)
        row = {"stage": stage, "observed_nanos": stamp(), "observation": value}
        self.observations.append(row)
        self._append("parent-observations.ndjson", row)
        return row

    def close(self, *, force=True):
        if self.attach is None:
            return None
        try:
            return self.attach.close(force=force)
        finally:
            if self.attach.closed:
                self.record["attach"] = self.attach.receipt
                write_json(self.root / "attachment.json", self.attach.receipt)

    def _failed(self, error):
        self.record.setdefault("failure", type(error).__name__ + ": " + str(error)[:2048])
        try:
            self.close(force=True)
        except BaseException as cleanup_error:
            self.record.setdefault("attach_cleanup_failure", type(cleanup_error).__name__)
        self.record.update(commands=self.commands, acknowledgements=self.acknowledgements,
                           observations=self.observations)
        write_json(self.root / "failure.json", self.record)

    def finish(self):
        try:
            require(len(self.commands) == 60 and len(self.observations) == 19,
                    "kubernetes-client-incomplete-session")
            completed = self.command("finish")
            try:
                self.attach.next_line(timeout=10)
            except EOFError:
                pass
            else:
                raise ValueError("kubernetes-client-output-after-complete")
            attachment = self.close(force=False)
            require(attachment["exit_code"] == 0 and attachment["reaped"] is True
                    and attachment["output_closed"] is True and attachment["forced_kill"] is False
                    and attachment["process_group_gone"] is True and attachment["failure"] is None
                    and attachment["subreaper"]["restored"] is True,
                    "kubernetes-client-attach-not-clean")
            require(len(self.acknowledgements) == 68, "kubernetes-client-incomplete-acks")
            pod, call = self.campaign.wait_pod(self.role, "succeeded")
            self._pod(pod, "Succeeded")
            self.record["final"] = {"pod": pod, "call": call,
                "observation": self.campaign.observe_client(pod, "final")}
            raw, log_call = self._logs()
            self.record["final_log"] = {"call": log_call, **self._retain("final-pod-stdout.log", raw)}
            require(raw == b"".join(self.ack_lines)
                    and _read(self.root / "attach-stdout.ndjson", 1024**2) == b"".join(self.ack_lines[1:]),
                    "kubernetes-client-final-stdout-binding")
            require(not (self.root / "raw").exists(), "kubernetes-client-download-not-fresh")
            self.record["download"] = self.campaign.download_directory(self.remote, self.root / "raw")
            actual_plan = _read(self.root / "raw/plan.json", 4096)
            require(actual_plan == self.plan_bytes, "kubernetes-client-downloaded-plan-changed")
            summary = _read(self.root / "raw/summary.json", 16 * 1024)
            require(sha256(summary) == completed["summary"]["sha256"]
                    and len(summary) == uint(completed["summary"]["bytes"]),
                    "kubernetes-client-downloaded-summary-changed")
            self.record.update(commands=self.commands, acknowledgements=self.acknowledgements,
                observations=self.observations, downloaded_plan={"bytes": str(len(actual_plan)),
                "sha256": sha256(actual_plan), "byte_identical": True})
            write_json(self.root / "before-delete.json", self.record)
            self.campaign.progress("client-complete-before-delete", self.record)
            self.record["delete"] = self.campaign.delete_pod(pod)
            write_json(self.root / "parent.json", self.record)
            return self.record
        except BaseException as error:
            self._failed(error)
            raise
