"""Generate only the additive Phase 4 bridge; the stateless bridge stays exact."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
SDK = ROOT / "sdk/java-client"
OUTPUT = SDK / "src/transport/java/dev/latent/sdk/transport/TransactionWire.java"


def upper(name: str) -> str:
    return "".join(part.title() for part in name.split("_"))


def lower(name: str) -> str:
    return name.split("_")[0] + "".join(part.title() for part in name.split("_")[1:])


def generate() -> str:
    contract = json.loads((ROOT / "sdk/profile/transaction-client-contract.json").read_bytes())
    messages, enums, external = contract["messages"], contract["enums"], contract["externalTypes"]
    sources = {}
    for filename, identity in contract["sources"].items():
        source = ROOT / "api/proto" / filename
        if "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest() != identity["sha256"]:
            raise ValueError("transaction bridge descriptor source is stale")
        sources[filename] = source.read_text(encoding="utf-8")
    wire = {}
    for name in messages:
        package = contract["wireNames"][name].strip(".").rsplit(".", 1)[0]
        candidates = [filename for filename, text in sources.items()
                      if f"package {package};" in text and re.search(rf"\bmessage {name}\s*\{{", text)]
        if len(candidates) != 1:
            raise ValueError("transaction bridge message has no exact protobuf owner")
        filename = candidates[0]
        outer = Path(filename).stem.title()
        if re.search(rf"\b(?:message|enum|service) {outer}\b", sources[filename]):
            outer += "OuterClass"
        wire[name] = f"{package}.{outer}.{name}"

    def convert(kind: str, value: str, outbound: bool, wire_type: str = "") -> str:
        if kind == "bytes":
            return f"ByteString.copyFrom({value}.asReadOnlyBuffer())" if outbound else f"{value}.asReadOnlyByteBuffer()"
        if kind in enums:
            return f"{value}.value()" if outbound else f"new Transactions.{kind}({value})"
        if kind in messages or kind in external:
            prefix = "Wire." if kind in external else ""
            if outbound and wire_type == ".latent.invocation.v1.PlatformError":
                return f"Wire.toInvocationPlatformError({value})"
            return f"{prefix}{'toWire' if outbound else 'fromWire'}({value})"
        return value

    lines = ["// Generated from the authoritative Phase 4 transaction descriptors.",
             "package dev.latent.sdk.transport;", "", "import dev.latent.sdk.Transactions;",
             "import com.google.protobuf.ByteString;", "import java.util.Map;", "import java.util.Optional;", "",
             "final class TransactionWire {", "    private TransactionWire() { }", ""]
    for name, fields in messages.items():
        native = wire[name]
        lines += [f"    static {native} toWire(Transactions.{name} value) {{",
                  f"        var result = {native}.newBuilder();"]
        for group in sorted({field["oneof"] for field in fields if "oneof" in field}):
            count = " + ".join(f"(value.{lower(field['name'])}().isPresent() ? 1 : 0)"
                               for field in fields if field.get("oneof") == group)
            lines.append(f'        if ({count} > 1) throw new IllegalArgumentException("contradictory oneof");')
        for field in fields:
            kind, accessor, setter = field["type"], f"value.{lower(field['name'])}()", upper(field["name"])
            suffix = "Value" if kind in enums else ""
            if field.get("map"):
                lines.append(f"        result.putAll{setter}({accessor});")
            elif field.get("repeated"):
                lines.append(f"        for (var item : {accessor}) result.add{setter}{suffix}({convert(kind, 'item', True, field.get('wireType', ''))});")
            elif field.get("optional"):
                lines.append(f"        if ({accessor}.isPresent()) result.set{setter}{suffix}({convert(kind, accessor + '.get()', True, field.get('wireType', ''))});")
            else:
                lines.append(f"        result.set{setter}{suffix}({convert(kind, accessor, True, field.get('wireType', ''))});")
        lines += ["        return result.build();", "    }", "", f"    static Transactions.{name} fromWire({native} value) {{",
                  f"        return new Transactions.{name}("]
        expressions = []
        for field in fields:
            kind, getter = field["type"], upper(field["name"])
            suffix = "Value" if kind in enums else ""
            if field.get("map"):
                expression = f"Map.copyOf(value.get{getter}Map())"
            elif field.get("repeated"):
                expression = f"value.get{getter}List().stream().map(item -> {convert(kind, 'item', False)}).toList()"
            else:
                expression = convert(kind, f"value.get{getter}{suffix}()", False)
                if field.get("optional"):
                    expression = f"value.has{getter}() ? Optional.of({expression}) : Optional.empty()"
            expressions.append("                " + expression)
        lines += [",\n".join(expressions) + ");", "    }", ""]
    return "\n".join(lines + ["}", ""])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    expected = generate()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise ValueError("Java transaction bridge is stale")
    elif args.write:
        OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    else:
        parser.error("choose --check or --write")


if __name__ == "__main__":
    main()
