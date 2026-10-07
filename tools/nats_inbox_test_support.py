#!/usr/bin/env python3
"""Finite controls for one owned, real TLS JetStream transactional input fixture.

Reuse the maintained bounded authenticated NATS client. This source produces no
simulated broker, node or transaction receipt. Only the exact owned INBOX395
history and two explicitly named consumers can be created/recreated.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from nats_deferred_support import DeferredClient

STREAM = "INBOX395"
SUBJECT = "lsf.trigger.a"
CONSUMERS = ("PROCESS", "REPLACEMENT")
STREAM_CONFIGURATION = {
    "name": STREAM, "subjects": [SUBJECT], "storage": "file",
    "num_replicas": 1, "retention": "limits", "discard": "new",
    "max_msgs": 64, "max_bytes": 1_048_576, "max_msg_size": 32_768,
    "max_age": 0, "duplicate_window": 30_000_000_000,
    "deny_delete": True, "deny_purge": True,
}


class InboxClient(DeferredClient):
    def qualification(self) -> dict:
        # Inherited qualification reads actual TLS broker INFO, pins2.14.6,
        # and observes the original owned outgoing DURABLE history. Do not
        # substitute its stream incarnation for this input stream's birth.
        outgoing = super().qualification()
        response = self.request(f"$JS.API.STREAM.INFO.{STREAM}", {})
        if "error" in response:
            raise RuntimeError("owned transactional input stream missing")
        actual = response.get("config", {})
        if any(actual.get(name) != value for name, value in STREAM_CONFIGURATION.items()):
            raise RuntimeError("transactional input history differs from finite fixture")
        if any(name in actual for name in ("sources", "mirror")):
            raise RuntimeError("transactional input cannot borrow another stream")
        birth = response.get("created")
        if not isinstance(birth, str) or not 1 <= len(birth) <= 128:
            raise RuntimeError("actual input stream incarnation missing")
        return {"formatVersion": 1, "serverVersion": outgoing["serverVersion"],
                "streamCreated": birth, "maximumMessages": 64,
                "maximumBytes": 1_048_576, "maximumAgeMillis": 0,
                "maximumMessageBytes": 32_768}

    def create(self) -> None:
        response = self.request(f"$JS.API.STREAM.CREATE.{STREAM}", STREAM_CONFIGURATION)
        if "error" in response:
            raise RuntimeError("finite input stream creation refused")

    def consumer(self, name: str) -> None:
        if name not in CONSUMERS:
            raise RuntimeError("unowned transactional input consumer")
        response = self.request(f"$JS.API.CONSUMER.DURABLE.CREATE.{STREAM}.{name}", {
            "stream_name": STREAM,
            "config": {"name": name, "durable_name": name, "filter_subject": SUBJECT,
                       "ack_policy": "explicit", "replay_policy": "instant", "deliver_policy": "all",
                       "ack_wait": 3_500_000_000, "max_deliver": 3,
                       "max_waiting": 1, "max_ack_pending": 1, "max_batch": 1,
                       "max_bytes": 10_240, "max_expires": 100_000_000},
        })
        if "error" in response:
            raise RuntimeError("bounded input consumer creation refused")

    def run(self, operation: str) -> None:
        if operation == "create":
            self.create()
            self.consumer("PROCESS")
            response = self.qualification()
        elif operation == "recreate":
            original = self.qualification()
            deleted = self.request(f"$JS.API.STREAM.DELETE.{STREAM}", {})
            if "error" in deleted or deleted.get("success") is not True:
                raise RuntimeError("explicit owned input recreation refused")
            self.create()
            self.consumer("PROCESS")
            response = self.qualification()
            if response["streamCreated"] == original["streamCreated"]:
                raise RuntimeError("input recreation did not change actual incarnation")
        elif operation == "replacement-consumer":
            self.qualification()
            self.consumer("REPLACEMENT")
            response = self.request(f"$JS.API.CONSUMER.INFO.{STREAM}.REPLACEMENT", {})
        elif operation == "qualification":
            response = self.qualification()
        elif operation in ("publish-update", "publish-rejection", "publish-poison"):
            self.qualification()
            payload = ([{"delta": 1, "reject": operation == "publish-rejection"}]
                       if operation != "publish-poison" else ["invalid-update-arity"])
            response = self.request(SUBJECT, payload)
            if "error" in response:
                raise RuntimeError("input publication refused")
        elif operation == "info":
            self.qualification()
            response = {"stream": self.request(f"$JS.API.STREAM.INFO.{STREAM}", {}),
                        "consumer": self.request(f"$JS.API.CONSUMER.INFO.{STREAM}.PROCESS", {})}
        else:
            raise RuntimeError("unapproved transactional input fixture control")
        print(json.dumps(response, separators=(",", ":")))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise RuntimeError("exact owned input fixture control arguments required")
    InboxClient(int(sys.argv[1]), Path(sys.argv[2])).run(sys.argv[3])
