"""Three pristine catalogs, populated only through the real management CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path

from tools.artifact_identity_runner.files import reference, write_json
from tools.artifact_identity_runner.helpers import command
from tools.optimization_evidence.common import require
from tools.optimization_runner.fixtures import cli_config
from . import fixtures, resources
from .applications import Application
from .model import DENSITIES, PREFIX


def prepare(campaign):
    result = {}
    for density in DENSITIES:
        campaign.reserve_active("lsf", density, seed=True)
        directory = campaign.root / "seeds" / str(density)
        directory.mkdir(parents=True)
        app = Application(campaign, f"seed-d{density}", "lsf", density)
        require(app.ready_inspect["HostConfig"]["NetworkMode"] == "container:" + campaign.controller_id,
                "docker-seed-network-namespace")
        config = cli_config(directory, app.endpoint, "cli.json")
        calls = []

        def invoke(name, arguments):
            log = directory / (name + ".json.log")
            argv = [str(campaign.build_root / "binaries/latent"), "--config", str(config), "--output", "json", *arguments]
            campaign.progress("seed-command-attempt", {"density": density, "name": name, "argv": argv})
            process = command(argv, log, 15, campaign.repository, campaign.fleet.deadline,
                              dict(os.environ), maximum=2 * 1024**2)
            value = json.loads(log.read_bytes())
            require(value.get("category") == "success", "docker-seed-management-failed")
            calls.append({"name": name, "arguments": arguments, "process": process,
                          "log": reference(log, campaign.root), "result": value})
            campaign.progress("seed-command-completed", {"density": density, **calls[-1]})
            return value

        before = invoke("inventory-before", ["node", "get", "optimization-node"])["data"]["inventory"]
        require(before["health"]["ready"] is True, "docker-seed-not-ready")
        for index in range(density):
            fixture = campaign.build_root / "fixtures"
            invoke(f"publish-{index}", ["release", "publish", "--manifest", str(fixture / f"capsule-{index}.json"),
                                       "--component", str(fixture / f"component-{index}.wasm"),
                                       "--contracts", str(fixture / "contracts.json")])
            invoke(f"apply-{index}", ["deployment", "apply", str(fixture / f"deployment-{index}.json")])
        after = invoke("inventory-after", ["node", "get", "optimization-node"])["data"]["inventory"]
        require(after["health"]["ready"] is True and after["cacheSummary"]["entries"] == "0"
                and all(row["granted"] == "0" and row["active"] == row["queueDepth"] == 0 for row in after["cellCapacity"]),
                "docker-seed-guest-work-or-active-owners")
        owner = app.finish()
        derived = resources.validate(app.output, arm="lsf", density=density, container_id=app.container_id,
                                     ready_inspect=owner["ready_inspect"], final_inspect=owner["final"]["inspect"],
                                     expected_snapshots=0, expected_connections=None)
        stop = {"container_id": app.container_id, "exit_code": owner["final"]["inspect"]["State"]["ExitCode"],
                "running": owner["final"]["inspect"]["State"]["Running"],
                "child_reaped": derived["shutdown"]["child_reaped"], "output_closed": derived["shutdown"]["output_closed"],
                "copy_tasks_joined": derived["shutdown"]["copy_tasks_joined"], "invokes": 0}
        receipt = fixtures.seal_template(app.data, density=density, stop_receipt=stop)
        value = {"schema": PREFIX + "seed.v1", "density": density, "owner": owner, "calls": calls,
                 "before": before, "after": after, "template": receipt,
                 "template_path": app.data.relative_to(campaign.root).as_posix(), "resources": derived}
        write_json(directory / "seed.json", value)
        campaign.setup.append(value)
        result[density] = {"path": app.data, "receipt": receipt, "record": value}
        campaign.reserve(64 * 1024**2)
    return result
