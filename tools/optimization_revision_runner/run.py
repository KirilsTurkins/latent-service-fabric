"""One fresh actual LSF server, using the unchanged #98 client/ownership code."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time

from tools import run_optimization_benchmarks as legacy
from tools.optimization_runner import fixtures
from tools.optimization_runner.processes import OwnedProcess
from .model import run_id


def collect(repetition, variant, selected, binaries, publications, output, target, result):
    directory = output / f"pair-{repetition:02}-{variant}"
    directory.mkdir()
    with tempfile.TemporaryDirectory(prefix="revision-node-owned-", dir=target) as state:
        config = fixtures.node_config(directory, Path(state) / "data")
        result["configuration"] = legacy.ref(config, output)
        legacy.seed(binaries[variant], binaries["cli"], config, publications, directory)
        server = OwnedProcess([str(binaries[variant]), "serve", "--config", str(config)],
                              directory / "server.log", "lsf-server", legacy.timeout(900), legacy.ROOT,
                              overall_deadline_ns=legacy.overall_deadline())
        result["started_micros"] = str(server.started_ns // 1000)
        stopped = None
        try:
            address = legacy.endpoint(server.ready())
            cli_config = fixtures.cli_config(directory, address, "measured-client.json")
            legacy.ready_node(binaries["cli"], cli_config, directory, "measured")
            ready_ns, first_ns = time.monotonic_ns(), None
            for case in selected["cases"]:
                before = directory / f"{case['id']}-cache-before.log"
                began = time.monotonic_ns() // 1000
                legacy.cli(binaries["cli"], cli_config, ["node", "get", "optimization-node"], before)
                current, first = legacy.batch(case, run_id(repetition, variant, case["id"]), "lsf", address,
                                              server, binaries["client"], directory / case["id"], output)
                # Retain a completed client's references before the next observation can fail.
                current["cache_observation"] = None
                result["batches"].append(current)
                after = directory / f"{case['id']}-cache-after.log"
                legacy.cli(binaries["cli"], cli_config, ["node", "get", "optimization-node"], after)
                witness = {"server_process_id": server.child.pid,
                           "start_time_ticks": server.receipt["start_time_ticks"], "endpoint": address,
                           "interval": "before-warmup-through-after-measured-includes-node-get-observation",
                           "started_micros": str(began), "finished_micros": str(time.monotonic_ns() // 1000),
                           "before": legacy.ref(before, output), "after": legacy.ref(after, output)}
                witness_path = directory / case["id"] / "cache-observation.json"
                fixtures.write(witness_path, witness)
                current["cache_observation"] = legacy.ref(witness_path, output)
                if first_ns is None:
                    first_ns = first
                print(f"pair {repetition} {variant} {case['id']} retained", flush=True)
            if first_ns is None or first_ns < ready_ns:
                raise RuntimeError("revision-first-response-unobserved")
            result["lifecycle"] = {
                "process_start_to_ready_micros": str((ready_ns - server.started_ns) // 1000),
                "process_start_to_first_response_observed_micros": str((first_ns - server.started_ns) // 1000),
                "ready_to_first_response_observed_micros": str((first_ns - ready_ns) // 1000),
                "first_response_observation": "parent-received-client-event-upper-bound-includes-client-startup-and-connect",
                "initial_preparation": "included-in-first-call"}
            stopped = server.stop()
            result.update(status="passed", reason=None)
        finally:
            server.close()
            result["finished_micros"] = str(time.monotonic_ns() // 1000)
            fixtures.write(directory / "server-process.json", server.receipt)
            receipts = [json.loads(path.read_bytes()) for path in sorted(directory.glob("*/client-process.json"))]
            # Completed case order is normative, not lexicographic filename order.
            if result["status"] == "passed":
                receipts = [json.loads((output / row["client_process"]["path"]).read_bytes()) for row in result["batches"]]
            fixtures.write(directory / "cleanup.json", {"server": server.receipt, "clients": receipts,
                                                        "server_shutdown": stopped})
            result.update(server_process=legacy.ref(directory / "server-process.json", output),
                          cleanup=legacy.ref(directory / "cleanup.json", output))
    result["data_removed"] = True
