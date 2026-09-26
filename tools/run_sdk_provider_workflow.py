#!/usr/bin/env python3
"""Run one language-native SDK participant against a separately owned real node."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Client, WorkflowError, bounded_receipt, file_digest, read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_management_scenario import TENANT, configure_provider_node, publish_and_deploy_guests
from tools.sdk_provider_scenario import LANGUAGES, participant_input, publish_callee, run_participant, start_provider, stop_provider


def identity(args, client):
    paths = {"node": args.node, "cli": args.cli, "fixture": args.fixture_root / "fixture.json"}
    for index, value in enumerate(args.participant):
        path = Path(value)
        if path.is_absolute() and path.is_file():
            paths[f"participant{index}"] = path
    require("participant0" in paths, "sdk-explicit-executable-required")
    return {name: file_digest(path, 1024 * 1024 * 1024, client.cancellation, client.deadline)
            for name, path in paths.items()}


def verify_retention(client, result):
    for activation in result["activationIds"]:
        value = client.call("activation", "get", activation)["data"]
        require(value["activationId"] == activation and value.get("terminalState") is not None,
                "sdk-activation-not-retained-terminal")
    value = client.call("policy", "operation", "--operation-id", result["operationId"])["data"]
    require(value["receipt"]["operationId"] == result["operationId"], "sdk-operation-not-retained")


def run(args):
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix="lsf-sdk-provider-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        directories = {name: root / name for name in ("node", "operator", "sdk", "control")}
        for directory in directories.values():
            directory.mkdir(mode=0o700)
        client = Client(args.cli, directories["operator"], cancellation, time.monotonic() + 240)
        identities = identity(args, client)
        provider, port = start_provider(client, directories["control"])
        node = None
        try:
            config = configure_provider_node(directories["node"], args.fixture_root, port)
            settings = read_json(config)
            settings["retention"]["terminalTtlMillis"] = 120000
            config = directories["node"] / "sdk-node.json"
            write_json(config, settings)
            node = connect(client, args.node, directories["node"], config, TENANT, 1)
            targets = publish_and_deploy_guests(client, args.fixture_root, node, port)
            targets["callee"] = publish_callee(client, args.fixture_root)
            input_path = participant_input(directories["sdk"], directories["control"], args.language,
                                           node.startup_record["endpoint"], targets, port)
            result = run_participant(client, directories["sdk"], args.participant, input_path, args.language)
            verify_retention(client, result)
            stop(client, node)
            shutdown = stopped_record(node)
            require(shutdown["record"]["report"]["providers"]["clean"] is True, "sdk-node-provider-reclamation")
            node = None
            upstream = stop_provider(provider)
            return {"schemaVersion": "latent.sdk.provider.workflow.evidence.v1", "language": args.language,
                    "scope": "separate-node-authenticated-provider-guests", "identities": identities,
                    "participant": result, "upstream": upstream, "nodeShutdown": shutdown,
                    "guestFixture": read_json(args.fixture_root / "fixture.json"),
                    "operatorSetupCommands": client.calls, "browserQualified": False, "installedBundleQualified": False}
        finally:
            if node is not None:
                node.close()
            provider.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--language", choices=sorted(LANGUAGES), required=True)
    parser.add_argument("participant", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    require(sys.platform == "linux", "sdk-provider-workflow-platform")
    args.cli = args.cli.resolve(strict=True)
    args.node = args.node.resolve(strict=True)
    args.fixture_root = args.fixture_root.resolve(strict=True)
    if args.participant and args.participant[0] == "--":
        args.participant.pop(0)
    print(bounded_receipt(run(args)))


if __name__ == "__main__":
    try:
        main()
    except WorkflowError as failure:
        print(str(failure), file=sys.stderr)
        raise SystemExit(1)
    except (KeyError, OSError, TypeError, ValueError):
        print("sdk-provider-workflow-invalid-input-or-response", file=sys.stderr)
        raise SystemExit(1)
