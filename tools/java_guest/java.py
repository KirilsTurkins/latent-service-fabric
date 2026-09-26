"""Typed Java surface and deterministic private codecs for a reviewed WIT graph."""
from __future__ import annotations

from tools.java_guest.model import Graph, PRIMITIVES, camel, jident


def reader(graph: Graph, value, source="input") -> str:
    return "read" + graph.codec(value) + "(" + source + ")"


def writer(graph: Graph, value, expression: str, target="output") -> str:
    return "write" + graph.codec(value) + "(" + target + ", " + expression + ");"


def definitions(graph: Graph) -> list[str]:
    output = []
    for index in sorted(graph.live):
        item = graph.types[index]
        name, kind = graph.name(index), item["kind"]
        if kind == "resource":
            operation = -1 - graph.resources.index(index)
            output.append(f"public static final class {name} extends Resource {{ private {name}(int handle) {{ super(handle, {operation}); }} }}")
            continue
        form, body = next(iter(kind.items()))
        if form in ("record", "tuple"):
            fields = body["fields"] if form == "record" else [{"name": "f" + str(i), "type": value} for i, value in enumerate(body["types"])]
            arguments = ", ".join(graph.jtype(field["type"]) + " " + jident(field["name"]) for field in fields)
            checks = " ".join(f"java.util.Objects.requireNonNull({jident(field['name'])});" for field in fields)
            output.append(f"public record {name}({arguments}) {{ public {name} {{ {checks} }} }}")
        elif form == "enum":
            output.append(f"public enum {name} {{ " + ", ".join(camel(case["name"]) for case in body["cases"]) + " }")
        elif form == "variant":
            output.append(f"public static final class {name} {{")
            output.extend(["private final int tag; private final Object value;",
                           f"private {name}(int tag, Object value) {{ this.tag = tag; this.value = value; }}",
                           "public int tag() { return tag; }"])
            for tag, case in enumerate(body["cases"]):
                member, value = jident(case["name"]), case["type"]
                arguments = "" if value is None else graph.jtype(value) + " value"
                payload = "Unit.VALUE" if value is None else "java.util.Objects.requireNonNull(value)"
                output.append(f"public static {name} {member}({arguments}) {{ return new {name}({tag}, {payload}); }}")
                if value is not None:
                    output.append(f"@SuppressWarnings(\"unchecked\") public {graph.jtype(value)} {member}Value() {{ Wire.require(tag == {tag}); return ({graph.jtype(value)}) value; }}")
            output.append("}")
    return output


def scalar(value: str) -> tuple[str, str]:
    if value == "bool": return "input.bool()", "output.bool(value);"
    if value == "string": return "input.string()", "output.string(value);"
    if value == "u64": return "new Unsigned64(input.integer(8))", "output.integer(value.bits(), 8);"
    if value == "char":
        return "readCharValue(input)", "Wire.require(value >= 0 && value <= 0x10ffff && !(value >= 0xd800 && value <= 0xdfff)); output.unsigned(value, 4);"
    if value in ("f32", "f64"):
        return (("Float.intBitsToFloat((int) input.integer(4))", "output.integer(Float.floatToRawIntBits(value), 4);") if value == "f32"
                else ("Double.longBitsToDouble(input.integer(8))", "output.integer(Double.doubleToRawLongBits(value), 8);"))
    width = int(value[1:]) // 8
    cast = {"u8": "short", "u16": "int", "u32": "long", "s8": "byte", "s16": "short", "s32": "int", "s64": "long"}[value]
    method = "unsigned" if value[0] == "u" else "integer"
    return f"({cast}) input.integer({width})", f"output.{method}(value, {width});"


def codec(graph: Graph, index: int) -> list[str]:
    kind, name = graph.types[index]["kind"], graph.name(index)
    if kind == "resource": return []
    form, body = next(iter(kind.items()))
    write, read = [], []
    if form == "type":
        write.append(writer(graph, body, "value")); read.append("return " + reader(graph, body) + ";")
    elif form == "list":
        if body == "u8":
            write.append("output.bytes(value);"); read.append("return input.bytes();")
        else:
            write.append("output.count(value.size());")
            write.append(f"for ({graph.jtype(body)} item : value) {{ {writer(graph, body, 'item')} }}")
            read.extend(["int count = input.count();", f"java.util.ArrayList<{graph.jtype(body)}> values = new java.util.ArrayList<>(count);",
                         f"for (int i = 0; i < count; i++) values.add({reader(graph, body)});", "return values;"])
    elif form in ("record", "tuple"):
        fields = body["fields"] if form == "record" else [{"name": "f" + str(i), "type": value} for i, value in enumerate(body["types"])]
        write.extend(writer(graph, field["type"], "value." + jident(field["name"]) + "()") for field in fields)
        read.append("return new " + name + "(" + ", ".join(reader(graph, field["type"]) for field in fields) + ");")
    elif form == "option":
        write.append("output.bool(value.isSome()); if (value.isSome()) { " + writer(graph, body, "value.value()") + " }")
        read.append("return input.bool() ? Option.some(" + reader(graph, body) + ") : Option.none();")
    elif form == "result":
        write.append("output.bool(value.isError()); if (value.isError()) { " + writer(graph, body["err"], "value.error()") + " } else { " + writer(graph, body["ok"], "value.value()") + " }")
        read.append("return input.bool() ? Result.err(" + reader(graph, body["err"]) + ") : Result.ok(" + reader(graph, body["ok"]) + ");")
    elif form == "variant":
        write.append("output.integer(value.tag(), 4); switch (value.tag()) {")
        read.append("switch ((int) input.integer(4)) {")
        for tag, case in enumerate(body["cases"]):
            write.append(f"case {tag}: " + (writer(graph, case["type"], "value." + jident(case["name"]) + "Value()") if case["type"] is not None else "") + " break;")
            read.append(f"case {tag}: return {name}.{jident(case['name'])}(" + (reader(graph, case["type"]) if case["type"] is not None else "") + ");")
        write.append('default: throw new IllegalArgumentException("invalid variant tag"); }')
        read.append('default: throw new IllegalArgumentException("invalid variant tag"); }')
    elif form == "enum":
        write.append("output.integer(value.ordinal(), 4);")
        read.extend(["long tag = input.integer(4);", f"Wire.require(tag < {len(body['cases'])});", f"return {name}.values()[(int) tag];"])
    elif form == "flags":
        count = len(body["flags"])
        check = "" if count == 64 else f"Wire.require((value.bits() >>> {count}) == 0); "
        write.append(check + "output.integer(value.bits(), 8);")
        read.append("Unsigned64 value = new Unsigned64(input.integer(8)); " + check + "return value;")
    elif form == "handle":
        own = "own" in body
        write.append("output.resource(value, " + str(own).lower() + ");")
        if not own: read.append('throw new IllegalArgumentException("borrowed resource exports are unsupported");')
        else: read.append("return new " + graph.name(body["own"]) + "((int) input.integer(4));")
    else: raise ValueError("unsupported Java codec form " + form)
    jtype, suffix = graph.jtype(index), graph.codec(index)
    return [f"private static void write{suffix}(Wire.Writer output, {jtype} value) {{", *write, "}",
            f"private static {jtype} read{suffix}(Wire.Reader input) {{", *read, "}"]


def generate(graph: Graph) -> str:
    output = ["// Generated from authoritative WIT and maintained wit-bindgen C. DO NOT EDIT.",
              "package dev.latent.generated;", "import dev.latent.guest.*;", "import org.teavm.interop.Address;",
              "import org.teavm.interop.Export;", "import org.teavm.interop.Function;",
              "public final class Bindings {", "private Bindings() { }"]
    output.extend(definitions(graph))
    output.append("public interface Exports {")
    for function in graph.exports:
        arguments = ", ".join(graph.jtype(p["type"]) + " arg" + str(i) for i, p in enumerate(function["params"]))
        output.append(graph.jtype(function.get("result")) + " " + jident(function["name"]) + "(" + arguments + ");")
    output.append("}")
    for interface in sorted({f["interface"] for f in graph.imports}):
        name = graph.interface_names[interface]
        output.append(f"public static final class {name} {{ private {name}() {{ }}")
        for function in [f for f in graph.imports if f["interface"] == interface]:
            arguments = ", ".join(graph.jtype(p["type"]) + " arg" + str(i) for i, p in enumerate(function["params"]))
            output.append("public static " + graph.jtype(function.get("result")) + " " + jident(function["name"]) + "(" + arguments + ") {")
            output.append("try (Wire.Writer arguments = new Wire.Writer()) {")
            output.extend(writer(graph, p["type"], "arg" + str(i), "arguments") for i, p in enumerate(function["params"]))
            output.append(f"try (Wire.Reader input = arguments.call({function['operation']})) {{")
            output.extend([graph.jtype(function.get("result")) + " result = " + reader(graph, function.get("result")) + ";",
                           "input.finish(); return result;", "} } }"])
        output.append("}")
    output.extend(["public abstract static class Dispatch extends Function { public abstract Address apply(int operation, Address data, int length); }",
                   'public static void main(String[] args) { Function.get(Dispatch.class, Bindings.class, "dispatch"); }',
                   '@Export(name = "lsf_java_dispatch") public static Address dispatch(int operation, Address data, int length) {',
                   "try (Wire.Reader input = Wire.Reader.copy(data, length); Wire.Writer output = new Wire.Writer()) {",
                   "switch (operation) {"])
    for function in graph.exports:
        output.append(f"case {function['operation']}: {{")
        for i, p in enumerate(function["params"]):
            output.append(graph.jtype(p["type"]) + " arg" + str(i) + " = " + reader(graph, p["type"]) + ";")
        output.append("input.finish();")
        arguments = ", ".join("arg" + str(i) for i, _p in enumerate(function["params"]))
        call = "new dev.latent.app.Capsule()." + jident(function["name"]) + "(" + arguments + ")"
        output.append(writer(graph, function.get("result"), call))
        output.append("return output.nativeResult(); }")
    output.append('default: throw new IllegalArgumentException("unknown Java export"); } } }')
    output.extend(["private static Unit readUnit(Wire.Reader input) { return Unit.VALUE; }",
                   "private static void writeUnit(Wire.Writer output, Unit value) { java.util.Objects.requireNonNull(value); }",
                   "private static Integer readCharValue(Wire.Reader input) { long value = input.integer(4); Wire.require(value <= 0x10ffff && !(value >= 0xd800 && value <= 0xdfff)); return (int) value; }"])
    for primitive in sorted(PRIMITIVES):
        read, write = scalar(primitive)
        output.extend([f"private static {graph.jtype(primitive)} read{graph.codec(primitive)}(Wire.Reader input) {{ return {read}; }}",
                       f"private static void write{graph.codec(primitive)}(Wire.Writer output, {graph.jtype(primitive)} value) {{ {write} }}"])
    for index in sorted(graph.live): output.extend(codec(graph, index))
    output.append("}")
    return "\n".join(output) + "\n"
