"""Explicit state value vectors; compilation does not qualify signed execution."""
from pathlib import Path
import json

from tools.java_transaction_schema import SOURCE, create as create_schema
from tools.rust_capsule_project import digest, read_file, read_json
from tools.transaction_guest_variants import replace_once

SELECTORS = {"highBit": "4294967280", "unsignedMaximum": "4294967281"}
UTF8_TEXT = "κλειδί / 値 / 🌍"


def source_variant(original: str) -> str:
    utf8_payload = json.dumps([None, UTF8_TEXT], ensure_ascii=False, separators=(",", ":"))
    java_literal = json.dumps(utf8_payload, ensure_ascii=False)
    source = replace_once(original, "import java.util.List;",
        "import java.util.List;\nimport java.util.Arrays;\nimport java.nio.charset.StandardCharsets;")
    source = replace_once(source, "public final class Capsule implements Bindings.Exports {",
        "public final class Capsule implements Bindings.Exports {\n"
        '    private static final byte[] UTF8_KEY = "aggregate/clé/🌍".getBytes(StandardCharsets.UTF_8);\n'
        '    private static final byte[] ABSENT_KEY = "aggregate/absent/null".getBytes(StandardCharsets.UTF_8);\n'
        '    private static final byte[] UTF8_VALUE = ' + java_literal + '.getBytes(StandardCharsets.UTF_8);\n'
        "    private static int entries;\n"
        '    private static void enter() { if (++entries != 1) throw new IllegalStateException("value-instance-reused"); }')
    source = replace_once(source,
        "    update(Bindings.ExamplesTransactionalAggregateApiUpdateRequest request) {\n",
        "    update(Bindings.ExamplesTransactionalAggregateApiUpdateRequest request) {\n        enter();\n")
    source = replace_once(source, "BusinessError> query() {\n", "BusinessError> query() {\n        enter();\n")
    source = replace_once(source, "    scan(byte[] prefix, Long limit, Option<byte[]> cursor) {\n",
        "    scan(byte[] prefix, Long limit, Option<byte[]> cursor) {\n        enter();\n")
    source = replace_once(source, "            long next = old + request.delta();",
        "            long next = request.delta() == 0xffff_fff0L ? Long.MIN_VALUE\n"
        "                : request.delta() == 0xffff_fff1L ? -1L : old + request.delta();")
    source = replace_once(source, "            command.put(KEY, payload).value();",
        "            command.put(KEY, payload).value();\n"
        '            command.put(UTF8_KEY, new Bindings.LatentStateKeyValueValue(UTF8_VALUE, "application/json", List.of())).value();\n'
        '            if (command.get(ABSENT_KEY).value().isSome()) throw new IllegalStateException("absent-command-value-changed");')
    source = replace_once(source, "            var count = count(stored);",
        "            var count = count(stored);\n"
        "            var text = query.get(UTF8_KEY).value();\n"
        "            if (stored.isSome()) {\n"
        '                if (!text.isSome() || !text.value().value().mediaType().equals("application/json")\n'
        "                    || !text.value().value().metadata().isEmpty()\n"
        "                    || !Arrays.equals(text.value().value().bytes(), UTF8_VALUE))\n"
        '                    throw new IllegalStateException("utf8-state-roundtrip-changed");\n'
        '            } else if (text.isSome()) throw new IllegalStateException("uncommitted-utf8-value");\n'
        '            if (query.get(ABSENT_KEY).value().isSome()) throw new IllegalStateException("absent-query-value-changed");')
    return source


def create(directory: Path, name: str = "transaction-java-aggregate") -> Path:
    project = create_schema(directory, "legacy-v1", name, effect="put-once")
    original = read_file(project / SOURCE)
    source = source_variant(original.decode("utf-8")).encode("utf-8")
    (project / SOURCE).write_bytes(source)
    for filename in ("sdk-lock.json", "application-schema-inputs.json"):
        value = read_json(project / filename)
        if filename == "sdk-lock.json":
            value["template"]["sourceDigest"] = digest(source)
        else:
            value["sourceDigest"] = digest(source)
        (project / filename).write_bytes(json.dumps(value, indent=2).encode()+b"\n")
    descriptor = read_json(project / "capsule-project.json")
    descriptor["version"] = "1.0.2"
    (project / "capsule-project.json").write_bytes(json.dumps(descriptor, indent=2).encode()+b"\n")
    record = {"schemaVersion": "latent.java.transaction-value-inputs.v1", "selectors": SELECTORS,
        "expectedUnsignedValues": {"highBit": "9223372036854775808", "unsignedMaximum": "18446744073709551615"},
        "utf8Text": UTF8_TEXT, "utf8PayloadDigest": digest(json.dumps([None, UTF8_TEXT], ensure_ascii=False,
            separators=(",", ":")).encode()), "absentOptionalRequired": True, "freshInstanceRequired": True,
        "originalSourceDigest": digest(original), "sourceDigest": digest(source),
        "worldDigest": digest(read_file(project / "wit/world.wit")),
        "companionDigest": digest(read_file(project / "transaction-binding.json")),
        "componentCompiled": False, "signedStateExecutionQualified": False,
        "unsignedRoundtripQualified": False, "utf8RoundtripQualified": False,
        "absentOptionalQualified": False}
    (project / "transaction-value-inputs.json").write_bytes(json.dumps(record, indent=2, ensure_ascii=False).encode()+b"\n")
    return project
