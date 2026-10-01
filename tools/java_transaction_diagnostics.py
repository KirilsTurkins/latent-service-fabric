#!/usr/bin/env python3
"""Capture a separate post-stage fault capsule; original schema builds stay intact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_transaction_schema import SOURCE, create as create_schema
from tools.rust_capsule_project import ROOT, digest, read_file, read_json
from tools.transaction_guest_project import HTTP_REQUIREMENTS
from tools.transaction_guest_variants import replace_once

HELPER = "src/dev/latent/app/TransactionDiagnostics.java"
SELECTORS = {"trapAfterStage": "4294967293", "loopAfterStage": "4294967294"}


def source_variant(original: str) -> str:
    selected = replace_once(original,
        "    update(Bindings.ExamplesTransactionalAggregateApiUpdateRequest request) {\n",
        "    update(Bindings.ExamplesTransactionalAggregateApiUpdateRequest request) {\n"
        "        TransactionDiagnostics.enter();\n")
    selected = replace_once(selected,
        "BusinessError> query() {\n",
        "BusinessError> query() {\n        TransactionDiagnostics.enter();\n")
    selected = replace_once(selected,
        "    scan(byte[] prefix, Long limit, Option<byte[]> cursor) {\n",
        "    scan(byte[] prefix, Long limit, Option<byte[]> cursor) {\n"
        "        TransactionDiagnostics.enter();\n")
    selected = replace_once(selected, "            long next = old + request.delta();",
        "            long next = old + TransactionDiagnostics.businessDelta(request.delta());")
    return replace_once(selected,
        '            new Intent("qualified-http", "put-once", effectPayload).stage(command).value();\n',
        '            new Intent("qualified-http", "put-once", effectPayload).stage(command).value();\n'
        "            TransactionDiagnostics.afterStage(request.delta());\n")


def create(directory: Path, name: str = "transaction-java-aggregate") -> Path:
    project = create_schema(directory, "legacy-v1", name, effect="put-once")
    original = read_file(project / SOURCE)
    source = source_variant(original.decode()).encode()
    helper = read_file(ROOT / "examples/java-transaction-schema/TransactionDiagnostics.java")
    (project / SOURCE).write_bytes(source)
    (project / HELPER).write_bytes(helper)
    descriptor = read_json(project / "capsule-project.json")
    descriptor["version"] = "1.0.1"
    (project / "capsule-project.json").write_bytes(json.dumps(descriptor, indent=2).encode() + b"\n")
    lock = read_json(project / "sdk-lock.json")
    lock["template"]["sourceDigest"] = digest(source)
    (project / "sdk-lock.json").write_bytes(json.dumps(lock, indent=2).encode() + b"\n")
    schema_inputs = read_json(project / "application-schema-inputs.json")
    schema_inputs["sourceDigest"] = digest(source)
    (project / "application-schema-inputs.json").write_bytes(json.dumps(schema_inputs, indent=2).encode() + b"\n")
    record = {"schemaVersion": "latent.java.transaction-diagnostic-inputs.v1",
        "selectors": SELECTORS, "selectedBusinessDelta": "1", "freshInstanceRequired": True,
        "faultAfter": ["state-put", "captured-put-once-intent"],
        "originalSourceDigest": digest(original), "sourceDigest": digest(source),
        "helperDigest": digest(helper), "worldDigest": digest(read_file(project / "wit/world.wit")),
        "companionDigest": digest(read_file(project / "transaction-binding.json")),
        "requirementsDigest": digest(read_file(project / HTTP_REQUIREMENTS)),
        "componentCompiled": False, "stateExecutionQualified": False,
        "cancellationQualified": False, "fuelExhaustionQualified": False, "freshInstanceQualified": False}
    (project / "transaction-diagnostic-inputs.json").write_bytes(json.dumps(record, indent=2).encode() + b"\n")
    return project


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--name", default="transaction-java-aggregate")
    arguments = parser.parse_args()
    print(create(arguments.project, arguments.name))


if __name__ == "__main__":
    main()
