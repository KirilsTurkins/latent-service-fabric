"""Measured real Angular invocations using the maintained protected T1 helpers."""
from __future__ import annotations

import base64
import hashlib
import json
import time

from tools.phase2_operator_process import Process, require
from tools.phase3_resource_node import ResourceClient, sample
from tools.phase3_resource_profile import LIMITS, digest, integer
from tools.phase3_web_scenario import MEDIA, invocation_arguments, selected_client_asset


def outcome(value):
    error = value.get("error") or {}
    return {"category": value["category"], "outcomeKnown": value["outcomeKnown"],
            "requestDispatched": value["requestDispatched"], "code": error.get("code"),
            "grpcCode": error.get("grpcCode"), "message": error.get("message"),
            "activationId": value["data"].get("activationId")}


def rendered(value, record, publication):
    require(value["category"] == "success" and value["outcomeKnown"], "resource-render-outcome")
    payload = value["data"]["payload"]
    require(payload["encoding"] == "base64" and payload["mediaType"] == MEDIA
            and len(payload["data"]) <= 262144, "resource-render-payload")
    values = json.loads(base64.b64decode(payload["data"], validate=True))
    require(isinstance(values, list) and len(values) == 1 and values[0]["status"] == 200,
            "resource-render-response")
    html = base64.b64decode(values[0]["body-base64"], validate=True).decode("utf-8")
    require("ngh=" in html and "workflow-operator" in html
            and "lsf-private-server-fixture-234" not in html, "resource-real-angular-output")
    selected_client_asset(record, publication, html)
    selected = value["data"]["resolvedRevision"]
    require(selected["publicationId"] == publication and selected["releaseDigest"] == record["componentDigest"],
            "resource-render-selected-identity")
    return {"htmlSha256": "sha256:" + hashlib.sha256(html.encode()).hexdigest(),
            "htmlBytes": len(html.encode()), "selectedPublication": publication}


class RenderClient(ResourceClient):
    def call(self, *arguments, **keywords):
        invocation = "invoke" in arguments
        expected = keywords.pop("codes", (0,))
        began = time.monotonic_ns()
        value = super().call(*arguments, codes=(0, 3, 4, 5, 130) if invocation else expected, **keywords)
        if invocation:
            activation = arguments[arguments.index("--activation-id") + 1]
            row = {"activation": activation, "kind": "render", "heat": self.heat,
                   "elapsedNanos": str(time.monotonic_ns() - began), "result": outcome(value),
                   "processReaped": True}
            self.observations.append(row)
            code = {"success": 0, "declared-error": 3, "platform-failure": 4,
                    "transport-failure": 5, "interrupted": 130}[value["category"]]
            require(code in expected, "resource-angular-call-outcome")
        if len(arguments) >= 3 and arguments[:2] == ("activation", "get"):
            activation = str(arguments[2])
            if value["category"] == "success" and value["data"].get("phase") == "running":
                if activation not in self.sampled_activations:
                    self.sampled_activations.add(activation)
                    observed = sample(self, self.probe, "active", self.dormant, False)
                    require(any(integer(cell["active"]) > 0 for cell in observed["inventory"]["cellCapacity"]),
                            "resource-render-active-cell-not-observed")
                    self.samples.append(observed)
        return value


def spawn(client, record, activation, path="/"):
    require(client.calls < LIMITS["maximumControls"], "resource-control-bound")
    arguments = invocation_arguments(client, record, path, activation)
    command = [client.executable, "--output", "json", "--config", str(client.config),
               "--profile", "operator", *map(str, arguments)]
    process = Process(command, client.directory, client.environment, client.cancellation, maximum=524288)
    client.calls += 1
    process.resource_activation = activation
    process.resource_input_digest = digest({"path": path, "record": record, "activation": activation})
    return process


def finish(client, process, record, publication):
    try:
        completed = process.complete(min(client.deadline, time.monotonic() + 8))
    finally:
        process.close()
    value = json.loads(completed.stdout)
    require(value["schemaVersion"] == "latent.cli.result.v1" and completed.returncode in (0, 3, 4, 5, 130),
            "resource-render-cli-result")
    result = {**outcome(value), "exitCode": completed.returncode,
              "requestedActivationId": process.resource_activation,
              "inputDigest": process.resource_input_digest, "processReaped": process.owner.finished}
    require(result["activationId"] in (None, process.resource_activation), "resource-render-activation")
    if result["category"] == "success":
        result.update(rendered(value, record, publication))
    return result


def prepare_observed(client, publication, result):
    command = [client.executable, "--output", "json", "--config", str(client.config), "--profile", "operator",
               "--rpc-timeout-ms", "300000", "web", "prepare", "--publication", publication,
               "--lifecycle-generation", "1", "--maximum-wait-ms", "300000"]
    began = time.monotonic_ns()
    process = Process(command, client.directory, client.environment, client.cancellation, maximum=32768)
    client.calls += 1
    observation = {"kind": "cold-isolated-preparation", "processId": process.owner.process.pid,
                   "maximumWaitMillis": 300000, "reaped": False,
                   "maximumSamples": result["profile"]["maximumPreparationSamples"],
                   "sampleIntervalMillis": result["profile"]["preparationSampleIntervalMillis"],
                   "samplingScope": "bounded-non-atomic-observations-not-an-exhaustive-memory-peak"}
    result["preparation"] = observation
    try:
        samples, next_sample = 0, began
        while not process.owner.exited():
            client.cancellation.check()
            require(time.monotonic() < client.deadline and time.monotonic_ns() - began < 310_000_000_000,
                    "resource-render-preparation-deadline")
            process.drain()
            client.node.drain()
            if samples < observation["maximumSamples"] and time.monotonic_ns() >= next_sample:
                observed = sample(client, client.probe, "preparation", client.dormant, False)
                result["samples"].append(observed)
                samples += 1
                next_sample = time.monotonic_ns() + observation["sampleIntervalMillis"] * 1_000_000
            time.sleep(0.1)
        completed = process.complete(min(client.deadline, time.monotonic() + 5))
        value = json.loads(completed.stdout)
        observation.update(result=value, exitCode=completed.returncode)
        require(completed.returncode == 0 and value["category"] == "success" and value["outcomeKnown"]
                and value["data"]["prepared"] is True and value["data"]["executionAuthorized"] is False
                and value["data"]["publication"]["id"] == publication, "resource-render-preparation-result")
    finally:
        process.close()
        observation.update(elapsedNanos=str(time.monotonic_ns() - began), reaped=process.owner.finished)
