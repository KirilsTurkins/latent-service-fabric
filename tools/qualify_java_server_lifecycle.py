#!/usr/bin/env python3
"""Real shared-ingress lifecycle gate using prebuilt, authenticated inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_server_lifecycle import RevisionControls
from tools.java_server_node import run
from tools.dev_workflow.common import require
from tools.phase3_resource_identity import file_identity
from tools.phase2_operator_process import read_json, write_json


def ordinary_tuple(path, binaries):
    observed = read_json(path)
    require(observed.get("status") == "passed" and observed.get("features") == []
            and observed.get("tupleRole") == "ordinary-defaults"
            and observed.get("hostAbiProfile") == "lsf-host-abi-phase3-v5"
            and observed.get("wasmtimeVersion") == "48.0.4", "server-lifecycle-genuine-default-tuple-required")
    for name, binary in binaries.items():
        product = observed["binaries"][name]
        actual = file_identity(binary, 512 * 1024 * 1024)
        expected = product.get("actualExecutableSha256", product.get("sha256"))
        require(actual["sha256"].removeprefix("sha256:") == expected.removeprefix("sha256:")
                and actual["bytes"] == product["bytes"], "server-lifecycle-native-product-mismatch")
        if "actualFeatures" in product:
            require(not set(product["actualFeatures"]) & {"development-test-node", "development-outbound-streams"},
                    "server-lifecycle-development-product-not-default")
    return {"receipt": file_identity(path), "sourceHead": observed["head"], "sourceTree": observed["tree"],
            "tupleRole": observed["tupleRole"], "hostAbiProfile": observed["hostAbiProfile"],
            "wasmtimeVersion": observed["wasmtimeVersion"], "binaries": observed["binaries"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "node", "tls-tool", "native-tuple", "first-fixture", "first-build", "second-fixture", "second-build", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--peer-port", type=int, required=True,
                        help="Exact finite loopback port captured in both ordinary Java sources")
    args = parser.parse_args(argv)
    inputs = {"latent": args.binary, "latentd": args.node, "capsule_authoring": args.tls_tool}
    native = ordinary_tuple(args.native_tuple, inputs)
    observer = RevisionControls(args.second_fixture, args.second_build,
                                second_body=b"Revision-two", peer_port=args.peer_port)
    try:
        result = run(args.binary, args.node, args.first_fixture, args.first_build, args.output,
                     tls_tool=args.tls_tool, tls=True, lifecycle=observer)
    finally:
        if args.output.is_dir():
            identity = {"before": native}
            try:
                identity["after"] = ordinary_tuple(args.native_tuple, inputs)
                require(identity["after"] == native, "server-lifecycle-native-input-changed")
            finally:
                write_json(args.output / "native-tuple-observation.json", identity)
    result["nativeTuple"] = native
    write_json(args.output / "conformance.json", result)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
