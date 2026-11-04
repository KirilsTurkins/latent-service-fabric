"""Typed Java surface and deterministic private codecs for a reviewed WIT graph."""
from __future__ import annotations

import hashlib
import json

from tools.java_guest.model import Graph, PRIMITIVES, camel, jident
from tools.java_guest.surface import surface


# Shutdown can affect either direction or both; keep its borrow exclusive.
NETWORK_LANES = {'read': 'NETWORK_READ', 'write': 'NETWORK_WRITE',
                 'ready': 'NETWORK_READY', 'inspect': 'NETWORK_INSPECT'}
NETWORK_IDENTITY = 'latent:network/streams@0.1.0'
# Full normalized interface from the retained wasm-tools 1.254.0 WIT graph.
NETWORK_SURFACE_SHA256 = '50417c915e7177d962a6792d98dc655a1c040c779d2ab53dd4728f73f6013d70'


def exact_network_surface(graph: Graph) -> bool:
    """No same-name signature, nested-resource, or additional-operation drift."""
    try:
        package = graph.data['packages'][graph.world['package']]['name']
        base, _, version = package.partition('@')
        world = base + '/' + graph.world['name'] + ('@' + version if version else '')
        contract = surface(graph.data, world)['imports'][NETWORK_IDENTITY]
        encoded = json.dumps(contract, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(encoded).hexdigest() == NETWORK_SURFACE_SHA256
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def borrowed_resource(graph: Graph, value):
    """Resolve only a bounded borrow handle, including transparent aliases."""
    seen = set()
    for _ in range(33):
        if type(value) is not int or not 0 <= value < len(graph.types) or value in seen:
            return None
        seen.add(value)
        kind = graph.types[value]['kind']
        if not isinstance(kind, dict) or len(kind) != 1:
            return None
        form, body = next(iter(kind.items()))
        if form == 'type':
            value = body
        elif form == 'handle' and isinstance(body, dict) and set(body) == {'borrow'}:
            return graph.resource_index(body['borrow'])
        else:
            return None
    return None


def network_connection(graph: Graph, index: int) -> bool:
    """Select only the exact async stream connection, not other resources."""
    item = graph.types[index]
    owner = item.get('owner')
    if item.get('kind') != 'resource' or item.get('name') != 'connection' or not isinstance(owner, dict):
        return False
    interface_id = owner.get('interface')
    if type(interface_id) is not int or not 0 <= interface_id < len(graph.data['interfaces']):
        return False
    interface = graph.data['interfaces'][interface_id]
    package = graph.data['packages'][interface['package']]['name']
    if package != 'latent:network@0.1.0' or interface['name'] != 'streams' or not exact_network_surface(graph):
        return False
    operations = {f['name']: f for f in graph.imports if f['interface'] == interface_id}
    return all(name in operations and operations[name].get('asyncLowered')
               and operations[name]['params']
               and borrowed_resource(graph, operations[name]['params'][0]['type']) == index
               for name in ('read', 'write', 'ready'))


def network_lane(graph: Graph, function: dict):
    lane = NETWORK_LANES.get(function['name'])
    if lane is None or not function['params']:
        return None
    index = borrowed_resource(graph, function['params'][0]['type'])
    if index is None or not network_connection(graph, index):
        return None
    if graph.types[index]['owner']['interface'] != function['interface']:
        return None
    return lane


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
            directional = ', true' if network_connection(graph, index) else ''
            output.append(f"public static final class {name} extends Resource {{ private {name}(int handle) {{ super(handle, {operation}{directional}); }} }}")
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
    # A cross-interface `use` of a resource is its type identity, not a value
    # codec. Only the distinct own/borrow handle codecs may transfer access.
    if form == "type":
        target, seen = body, {index}
        for _ in range(33):
            if isinstance(target, str): break
            if target in seen: raise ValueError("recursive Java resource alias")
            seen.add(target)
            aliased = graph.types[target]["kind"]
            if aliased == "resource": return []
            if not isinstance(aliased, dict) or set(aliased) != {"type"}: break
            target = aliased["type"]
        else: raise ValueError("Java resource alias depth limit")
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
        else: read.append("return new " + graph.name(graph.resource_index(body["own"])) + "((int) input.integer(4));")
    else: raise ValueError("unsupported Java codec form " + form)
    jtype, suffix = graph.jtype(index), graph.codec(index)
    return [f"private static void write{suffix}(Wire.Writer output, {jtype} value) {{", *write, "}",
            f"private static {jtype} read{suffix}(Wire.Reader input) {{", *read, "}"]


def generate(graph: Graph, *, activation_profile: bool = False, fiber_io_profile: bool = False) -> str:
    output = ["// Generated from authoritative WIT and maintained wit-bindgen C. DO NOT EDIT.",
              "package dev.latent.generated;", "import dev.latent.guest.*;", "import org.teavm.interop.Address;",
              "import org.teavm.interop.Export;", "import org.teavm.interop.Function;",
              "public final class Bindings {", "private Bindings() { }"]
    output.extend(['public static final class BorrowPermit {',
        'private final Wire.HostFunction function; private final int operation, direction;',
        'private BorrowPermit(Wire.HostFunction function, int operation, int direction) { this.function = function; this.operation = operation; this.direction = direction; }',
        'public int direction() { return direction; }',
        'public boolean authorizes(Wire.HostFunction candidate, int operation) { return function == candidate && this.operation == operation; }',
        '}'])
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
            lane = network_lane(graph, function)
            if function.get('asyncLowered'):
                # Admission may fail normally. It must precede marshalling an
                # own<T>, which closes the Java resource before native entry.
                direction = 'Wire.' + lane if lane else '0'
                writer_initializer = f"new Wire.Writer(new BorrowPermit(hostCall, {function['operation']}, {direction}))"
                output.append("try (dev.latent.guest.runtime.HostCalls.Call hostCall = dev.latent.guest.runtime.HostCalls.admit(); Wire.Writer arguments = " + writer_initializer + ") {")
            else:
                writer_initializer = (f"new Wire.Writer(new BorrowPermit(null, {function['operation']}, Wire.{lane}))"
                                      if lane else "new Wire.Writer()")
                output.append("try (Wire.Writer arguments = " + writer_initializer + ") {")
            output.extend(writer(graph, p["type"], "arg" + str(i), "arguments") for i, p in enumerate(function["params"]))
            call = (f"arguments.call(hostCall, {function['operation']}, false)"
                    if function.get('asyncLowered') else f"arguments.call({function['operation']})")
            output.append(f"try (Wire.Reader input = {call}) {{")
            output.extend([graph.jtype(function.get("result")) + " result = " + reader(graph, function.get("result")) + ";",
                           "input.finish(); return result;", "} } }"])
        output.append("}")
    if activation_profile:
        for function in graph.imports:
            interface = graph.data['interfaces'][function['interface']]
            package = graph.data['packages'][interface['package']]['name']
            if package != 'latent:runtime@0.1.0' or interface['name'] != 'activation': continue
            if function['name'] not in {'timer-next', 'wait-for'}: continue
            parameters = ", ".join(graph.jtype(p['type']) + ' arg' + str(i) for i, p in enumerate(function['params']))
            result = graph.jtype(function.get('result'))
            helper = 'lsfRootTimerNext' if function['name'] == 'timer-next' else 'lsfRootWaitFor'
            output.append(f'public static Option<{result}> {helper}({parameters}) {{')
            if fiber_io_profile:
                if not function.get('asyncLowered'): raise ValueError('root wait requires its real async ABI')
                output.append('try (Wire.Writer arguments = new Wire.Writer()) {')
                output.extend(writer(graph, p['type'], 'arg' + str(i), 'arguments') for i, p in enumerate(function['params']))
                output.append(f'try (Wire.Reader input = arguments.call(dev.latent.guest.runtime.HostCalls::waitRoot, {function["operation"]}, true)) {{')
                output.append('if (input == null) return Option.none();')
                output.append(result + ' result = ' + reader(graph, function.get('result')) + ';')
                output.append('input.finish(); return Option.some(result); } } }')
            else:
                arguments = ', '.join('arg' + str(i) for i, _p in enumerate(function['params']))
                output.append('return Option.some(' + graph.interface_names[function['interface']] + '.'
                              + jident(function['name']) + '(' + arguments + ')); }')
    output.extend(["public abstract static class Dispatch extends Function { public abstract Address apply(int operation, Address data, int length); }",
                   'public static void main(String[] args) { Function.get(Dispatch.class, Bindings.class, "dispatch"); }'])
    if activation_profile:
        output.extend(['@Export(name = "lsf_java_dispatch") public static Address dispatch(int operation, Address data, int length) {',
                       'return dev.latent.guest.runtime.Activation.invoke(operation, data, length); }',
                       'public static Address dispatchBody(int operation, int inputAddress, int length) {'])
    else:
        output.append('@Export(name = "lsf_java_dispatch") public static Address dispatch(int operation, Address data, int length) {')
    output.extend([
                   "try (Wire.Reader input = Wire.Reader.copy(" +
                   ("Address.fromInt(inputAddress)" if activation_profile else "data") +
                   ", length); Wire.Writer output = new Wire.Writer()) {",
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
