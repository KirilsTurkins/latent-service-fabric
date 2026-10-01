#!/usr/bin/env python3
"""Bounded operator inspection of one real, owned durable JetStream fixture."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import socket
import ssl
import sys

from nats_test_support import Client


class DeferredClient(Client):
    def qualification(self):
        context = ssl.create_default_context(cafile=str(self.ca))
        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as raw:
            with context.wrap_socket(raw, server_hostname="127.0.0.1") as stream:
                with stream.makefile("rb") as reader:
                    line = reader.readline(8193)
                    if len(line) > 8192 or not line.startswith(b"INFO ") or not line.endswith(b"\r\n"):
                        raise RuntimeError("bounded authenticated broker identity missing")
                    version = json.loads(line[5:])["version"]
        if version != "2.14.6":
            raise RuntimeError("unqualified pinned broker software version")
        response = self.request("$JS.API.STREAM.INFO.DURABLE", {})
        if "error" in response:
            raise RuntimeError("qualified fixture stream missing")
        return {"formatVersion": 1, "serverVersion": version,
                "streamCreated": response["created"], "maximumMessages": 64,
                "maximumBytes": 1048576, "maximumAgeMillis": 0,
                "maximumMessageBytes": 65536}

    def reset(self):
        self.request("$JS.API.STREAM.DELETE.DURABLE", {})
        response = self.request("$JS.API.STREAM.CREATE.DURABLE", {
            "name": "DURABLE", "subjects": ["lsf.deferred.allowed"],
            "storage": "file", "num_replicas": 1, "retention": "limits",
            "discard": "new", "max_msgs": 64, "max_bytes": 1048576,
            "max_msg_size": 65536, "max_age": 0, "duplicate_window": 30000000000,
            "deny_delete": True, "deny_purge": True})
        if "error" in response:
            raise RuntimeError("finite durable stream creation failed")

    def run(self, operation):
        if operation == "setup":
            self.prepare()
            print(json.dumps(self.qualification(), separators=(",", ":")))
        elif operation in ("reset", "recreate"):
            self.reset()
            print(json.dumps(self.qualification(), separators=(",", ":")))
        elif operation == "qualification":
            print(json.dumps(self.qualification(), separators=(",", ":")))
        elif operation == "info":
            print(json.dumps(self.request("$JS.API.STREAM.INFO.DURABLE", {})))
        elif operation == "message":
            response = self.request("$JS.API.STREAM.MSG.GET.DURABLE", {"seq": 1})
            message = response["message"]
            print(json.dumps({"subject": message["subject"], "sequence": message["seq"],
                              "payload": base64.b64decode(message["data"], validate=True).decode("ascii"),
                              "headers": base64.b64decode(message["hdrs"], validate=True).decode("ascii")}))
        else:
            raise RuntimeError("unapproved durable fixture control")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise RuntimeError("exact fixture control arguments required")
    DeferredClient(int(sys.argv[1]), Path(sys.argv[2])).run(sys.argv[3])
