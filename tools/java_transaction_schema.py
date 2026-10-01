#!/usr/bin/env python3
"""Capture ordinary Java schema variants; publication review remains host-owned."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_capsule_project import create as author
from tools.rust_capsule_project import ROOT, digest, read_file, read_json
from tools.transaction_guest_project import HTTP_BODY, HTTP_REQUIREMENTS, TEMPLATE, put_once_requirements
from tools.transaction_guest_variants import replace_once

VARIANTS = ("legacy-v1", "compatible-v2", "writer-v2")
EFFECTS = ("event", "put-once")
DEFINITIONS = {
    "v1": "sha256:bd60ba56c67d2a016b07c61418fa5530a71ce4fec0555e262c6a98ff79138a1f",
    "v2": "sha256:5465983620116dc20476955ea815d665e2868421f6bed705760f12225bada6eb",
}
SOURCE = "src/dev/latent/app/Capsule.java"
CODEC = "src/dev/latent/app/AggregateCodec.java"


def definitions() -> dict[str, bytes]:
    result = {version: read_file(ROOT / "contracts/state" / ("application-aggregate-" + version + ".schema.json"))
              for version in DEFINITIONS}
    if any(digest(raw) != DEFINITIONS[version] for version, raw in result.items()):
        raise ValueError("authoritative aggregate schema definition changed")
    return result


def source_variant(original: str, variant: str) -> str:
    if variant not in VARIANTS:
        raise ValueError("unknown Java transaction schema variant")
    if variant == "legacy-v1":
        return original
    start = original.index("    private static Long count(")
    end = original.index("    @Override", start)
    old = original[start:end]
    # Match the original stored format explicitly before making this application
    # edit. The maintained SDK, exports and canonical resource owners stay intact.
    if "payload.bytes().length != 8" not in old or "return count;" not in old:
        raise ValueError("controlled aggregate reader source drift")
    selected = replace_once(original, old,
        "    private static Long count(Option<Bindings.LatentStateKeyValueVersionedValue> value) {\n"
        "        if (!value.isSome()) return 0L;\n"
        "        var payload = value.value().value();\n"
        "        if (!payload.metadata().isEmpty()) return null;\n"
        "        return AggregateCodec.decode(payload.mediaType(), payload.bytes(), true);\n"
        "    }\n")
    write_v2 = "true" if variant == "writer-v2" else "false"
    selected = replace_once(selected,
        '    private static final String MEDIA = "application/vnd.lsf.aggregate-v1";',
        "    private static final boolean WRITE_V2 = " + write_v2 + ";\n"
        "    private static final String MEDIA = AggregateCodec.mediaType(WRITE_V2);")
    return replace_once(selected,
        "            byte[] bytes = new byte[8]; for (int i = 0; i < 8; i++) bytes[i] = (byte)(next >>> (8 * i));",
        "            byte[] bytes = AggregateCodec.encode(next, WRITE_V2);")


def create(directory: Path, variant: str, name: str = "transaction-java-aggregate", *, effect: str = "event") -> Path:
    if variant not in VARIANTS:
        raise ValueError("unknown Java transaction schema variant")
    if effect not in EFFECTS:
        raise ValueError("unknown Java transaction effect variant")
    schema = definitions()
    original = read_file(ROOT / "sdk/java-guest/templates/transactional-aggregate.java")
    source = source_variant(original.decode(), variant).encode()
    if effect == "put-once":
        source = replace_once(source.decode(),
            '            new Intent("approved-event", "event", payload).stage(command).value();',
            '            var effectPayload = new Bindings.LatentStateKeyValueValue(\n'
            '                new byte[]{' + ','.join(str(value) for value in HTTP_BODY) + '}, "application/octet-stream", List.of());\n'
            '            new Intent("qualified-http", "put-once", effectPayload).stage(command).value();').encode()
    project = author(directory, TEMPLATE, name)
    (project / SOURCE).write_bytes(source)
    if variant != "legacy-v1":
        (project / CODEC).write_bytes(read_file(ROOT / "examples/java-transaction-schema/AggregateCodec.java"))
    owner = read_json(project / "capsule-project.json")
    owner["version"] = {"legacy-v1": "1.0.0", "compatible-v2": "1.1.0", "writer-v2": "2.0.0"}[variant]
    if effect == "put-once":
        owner["limits"]["effectCount"] = 1
    (project / "capsule-project.json").write_bytes(json.dumps(owner, indent=2).encode() + b"\n")
    lock = read_json(project / "sdk-lock.json")
    lock["template"]["sourceDigest"] = digest(source)
    (project / "sdk-lock.json").write_bytes(json.dumps(lock, indent=2).encode() + b"\n")
    writer = "v2" if variant == "writer-v2" else "v1"
    binding = read_json(project / "transaction-binding.json")
    binding["stateSchema"] = DEFINITIONS[writer]
    (project / "transaction-binding.json").write_bytes(json.dumps(binding, indent=2).encode() + b"\n")
    if effect == "put-once":
        requirements = put_once_requirements(owner, read_file(project / "transaction-binding.json"))
        (project / HTTP_REQUIREMENTS).write_bytes(json.dumps(requirements, indent=2).encode() + b"\n")
    (project / "state-schema.json").write_bytes(schema[writer])
    captured = project / "schemas"
    captured.mkdir()
    for version, raw in schema.items():
        (captured / ("application-aggregate-" + version + ".schema.json")).write_bytes(raw)
    inputs = {"schemaVersion": "latent.java.application-schema-inputs.v1", "variant": variant, "effect": effect,
        "readers": sorted([DEFINITIONS["v1"]] if variant == "legacy-v1" else DEFINITIONS.values()),
        "writers": [DEFINITIONS[writer]], "sourceDigest": digest(source),
        "publicationReviewGranted": False, "componentCompiled": False, "stateExecutionQualified": False}
    (project / "application-schema-inputs.json").write_bytes(json.dumps(inputs, indent=2).encode() + b"\n")
    return project


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    parser.add_argument("--name", default="transaction-java-aggregate")
    parser.add_argument("--effect", choices=EFFECTS, default="event")
    args = parser.parse_args()
    print(create(args.project, args.variant, args.name, effect=args.effect))


if __name__ == "__main__":
    main()
