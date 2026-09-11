"""One persistent client, exactly sixty-one control commands, and flushed acks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from tools.artifact_identity_runner.files import write_json
from tools.optimization_evidence.common import require
from .model import CLIENT_PREFIX
from .owned import configuration, encoded, stamp


class Session:
    def __init__(self, campaign, pair):
        self.campaign, self.pair = campaign, pair
        self.root = campaign.root / "clients" / str(pair)
        self.root.mkdir(parents=True)
        self.plan = {"schema": CLIENT_PREFIX + "plan.v1", "run_id": campaign.run_id,
                     "profile": campaign.profile, "pair": pair, "token_file": "/fixtures/token"}
        write_json(self.root / "plan.json", self.plan)
        self.digest = "sha256:" + hashlib.sha256((self.root / "plan.json").read_bytes()).hexdigest()
        self.commands, self.acknowledgements, self.observations = [], [], []
        for name in ("parent-commands.ndjson", "parent-acks.ndjson"):
            with (self.root / name).open("xb"):
                pass
        self.events_offset = 0
        role = f"client-p{pair}"
        config = configuration(campaign.images["client"]["image_id"],
                               ["--session", "/output/plan.json", "--output", "/output"],
                               arm="client", density=1, network=campaign.fleet.network,
                               mounts=[campaign.fixture_mount, campaign.volume_mount(self.root, "/output")],
                               owner=campaign.fleet.owner, role=role, interactive=True)
        self.container_id = campaign.fleet.create(config, role)
        self.attach = campaign.engine.attach(self.container_id, self.root / "stdout.ndjson", self.root / "stderr.bin")
        campaign.attached.append(self.attach)
        self.start = campaign.fleet.start(self.container_id)
        self.ready = self.wait_ack("ready")
        self.ready_inspect = campaign.fleet.inspect(self.container_id)
        self.observe("ready")

    def wait_ack(self, event):
        while True:
            ack = json.loads(self.attach.next_line(timeout=120))
            received = stamp()
            require(ack["schema"] == CLIENT_PREFIX + "ack.v1" and ack["plan_sha256"] == self.digest
                    and ack["process_id"] == 1, "docker-client-ack-identity")
            row = {"ack": ack, "received_nanos": received}
            self.acknowledgements.append(row)
            with (self.root / "parent-acks.ndjson").open("ab") as stream:
                stream.write(encoded(row))
            require(len(self.acknowledgements) <= 70, "docker-client-ack-count")
            if "event_record" in ack:
                ref = ack["event_record"]
                require(ref["path"] == "events.jsonl" and int(ref["offset"]) == self.events_offset
                        and 0 < int(ref["bytes"]) <= 2 * 1024**2, "docker-client-event-reference")
                with (self.root / "events.jsonl").open("rb") as stream:
                    stream.seek(self.events_offset)
                    data = stream.read(int(ref["bytes"]))
                require(len(data) == int(ref["bytes"]) and "sha256:" + hashlib.sha256(data).hexdigest() == ref["sha256"],
                        "docker-client-event-hash")
                record = json.loads(data)
                self.events_offset += len(data)
                require(record["event"] == ack["event"] and record["command_ordinal"] == ack["command_ordinal"],
                        "docker-client-event-ack-binding")
            else:
                record = None
            require(ack["event"] != "failed", "docker-client-failed")
            if ack["event"] == event:
                return record
            require(ack["event"] == "first-response", "docker-client-unexpected-ack")

    def command(self, command, group=None, *, phase=None, barrier=None, targets=None):
        ordinal = len(self.commands)
        require(ordinal < 61, "docker-client-command-bound")
        value = {"schema": CLIENT_PREFIX + "command.v1", "ordinal": ordinal, "plan_sha256": self.digest,
                 "command": command, "group": group, "phase": phase, "barrier": barrier, "targets": targets}
        line = encoded(value).decode()
        self.commands.append({"line": line, "sent_nanos": stamp()})
        with (self.root / "parent-commands.ndjson").open("ab") as stream:
            stream.write(encoded(self.commands[-1]))
        self.attach.send_line(line[:-1])
        expected = {"begin-group": "group-ready", "inventory": "inventory", "phase": "phase-complete",
                    "finish-group": "group-finished", "finish": "complete"}[command]
        record = self.wait_ack(expected)
        if record is not None:
            require(record["command_ordinal"] == ordinal, "docker-client-command-ack-order")
        return record

    def observe(self, stage):
        value, call = self.campaign.fleet.call("GET", f"/containers/{self.container_id}/stats?stream=false&one-shot=true")
        self.observations.append({"stage": stage, "call": call["ordinal"], "observed_nanos": stamp(), "stats": value})

    def finish(self):
        self.command("finish")
        stopped = self.campaign.fleet.finish(self.container_id, already_exited=True)
        # Consume stream EOF before closing its owned socket and log files.
        try:
            self.attach.next_line(timeout=10)
            raise ValueError("docker-client-output-after-complete")
        except EOFError:
            pass
        attachment = self.attach.close()
        self.campaign.attached.remove(self.attach)
        value = {"pair": self.pair, "container_id": self.container_id, "plan": self.plan,
                 "directory": self.root.relative_to(self.campaign.root).as_posix(), "start": self.start,
                 "ready_inspect": self.ready_inspect, "final": stopped, "attach": attachment,
                 "commands": self.commands, "acknowledgements": self.acknowledgements,
                 "observations": self.observations}
        write_json(self.root / "parent.json", value)
        self.campaign.fleet.remove(self.container_id)
        return value
