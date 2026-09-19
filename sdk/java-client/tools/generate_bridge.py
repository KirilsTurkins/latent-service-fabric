import argparse
import difflib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SDK = ROOT / "sdk/java-client"
CONTRACT = json.loads((ROOT / "sdk/profile/contract.json").read_text(encoding="utf-8"))
PROFILE = json.loads((ROOT / "sdk/profile/client-profile.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ROOT / "sdk/profile"))
from generate import read_contract

SOURCE_PROFILE, SOURCE_MESSAGES, SOURCE_ENUMS = read_contract()
if (CONTRACT["operations"] != SOURCE_PROFILE["operations"] or CONTRACT["messages"] != SOURCE_MESSAGES
        or CONTRACT["enums"] != SOURCE_ENUMS):
    raise ValueError("shared contract is stale against authoritative protobuf")
ENUMS = CONTRACT["enums"]
MESSAGES = CONTRACT["messages"]
WIRE = {}
for source, names in PROFILE["sources"].items():
    namespace = "latent.invocation.v1" if "invocation/" in source else "latent.control.v1"
    outer = Path(source).stem.title()
    if re.search(rf"\b(?:message|enum|service) {outer}\b", (ROOT / source).read_text(encoding="utf-8")):
        outer += "OuterClass"
    for name in names:
        if name in MESSAGES:
            WIRE[name] = f"{namespace}.{outer}.{name}"


def upper(name):
    return "".join(part.title() for part in name.split("_"))


def lower(name):
    return name.split("_")[0] + "".join(part.title() for part in name.split("_")[1:])


def converted(kind, value, outbound, invocation=False):
    if kind == "bytes":
        return f"ByteString.copyFrom({value}.asReadOnlyBuffer())" if outbound else f"{value}.asReadOnlyByteBuffer()"
    if kind in ENUMS:
        return f"{value}.value()" if outbound else f"new Management.{kind}({value})"
    if kind in MESSAGES:
        method = "toInvocation" + kind if invocation and kind in ("ResourceBudget", "ErrorDetail", "PlatformError") else "toWire"
        return f"{method if outbound else 'fromWire'}({value})"
    return value


def generate():
    lines = ["package dev.latent.sdk.transport;", "", "import dev.latent.sdk.Management;",
             "import com.google.protobuf.ByteString;", "import java.util.Map;", "import java.util.Optional;", "",
             "public final class Wire {", "    private Wire() { }", ""]
    models = [(name, wire) for name, wire in WIRE.items()]
    models += [(name, f"latent.invocation.v1.Invocation.{name}") for name in ("ResourceBudget", "ErrorDetail", "PlatformError")]
    for name, wire in models:
        invocation = wire.startswith("latent.invocation.")
        method = "toInvocation" + name if invocation and name in ("ResourceBudget", "ErrorDetail", "PlatformError") else "toWire"
        fields = MESSAGES[name]
        lines += [f"    public static {wire} {method}(Management.{name} value) {{", f"        var result = {wire}.newBuilder();"]
        groups = sorted({field["oneof"] for field in fields if "oneof" in field})
        for group in groups:
            count = " + ".join(f"(value.{lower(field['name'])}().isPresent() ? 1 : 0)" for field in fields if field.get("oneof") == group)
            lines.append(f'        if ({count} > 1) throw new IllegalArgumentException("contradictory oneof");')
        for field in fields:
            kind, accessor, setter = field["type"], f"value.{lower(field['name'])}()", upper(field["name"])
            if field.get("map"):
                lines.append(f"        result.putAll{setter}({accessor});")
            elif field.get("repeated"):
                expression = converted(kind, "item", True, invocation)
                suffix = "Value" if kind in ENUMS else ""
                lines.append(f"        for (var item : {accessor}) result.add{setter}{suffix}({expression});")
            elif field.get("optional"):
                expression = converted(kind, accessor + ".get()", True, invocation)
                suffix = "Value" if kind in ENUMS else ""
                lines.append(f"        if ({accessor}.isPresent()) result.set{setter}{suffix}({expression});")
            else:
                suffix = "Value" if kind in ENUMS else ""
                lines.append(f"        result.set{setter}{suffix}({converted(kind, accessor, True, invocation)});")
        lines += ["        return result.build();", "    }", "", f"    public static Management.{name} fromWire({wire} value) {{", f"        return new Management.{name}("]
        expressions = []
        for field in fields:
            kind, getter = field["type"], upper(field["name"])
            suffix = "Value" if kind in ENUMS else ""
            accessor = f"value.get{getter}{suffix}()"
            if field.get("map"):
                expression = f"Map.copyOf(value.get{getter}Map())"
            elif field.get("repeated"):
                expression = f"value.get{getter}List().stream().map(item -> {converted(kind, 'item', False)}).toList()"
            else:
                expression = converted(kind, accessor, False)
                if field.get("optional"):
                    expression = f"value.has{getter}() ? Optional.of({expression}) : Optional.empty()"
            expressions.append("                " + expression)
        lines += [",\n".join(expressions) + ");", "    }", ""]
    lines += ["}", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--patch", action="store_true")
    args = parser.parse_args()
    path = SDK / "src/transport/java/dev/latent/sdk/transport/Wire.java"
    expected = generate()
    actual = path.read_text(encoding="utf-8") if path.exists() else ""
    if args.check:
        if actual != expected:
            raise SystemExit("Java bridge is stale; generate_bridge.py --patch")
    elif args.patch:
        print("*** Begin Patch")
        relative = path.relative_to(ROOT).as_posix()
        if path.exists():
            print(f"*** Update File: {relative}")
            for line in list(difflib.unified_diff(actual.splitlines(), expected.splitlines(), lineterm=""))[2:]:
                print("@@" if line.startswith("@@") else line)
        else:
            print(f"*** Add File: {relative}")
            print("\n".join("+" + line for line in expected.splitlines()))
        print("*** End Patch")
    else:
        parser.error("choose --check or --patch")


if __name__ == "__main__":
    main()
