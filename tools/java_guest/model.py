"""Closed supported WIT graph, obtained from the maintained wasm-tools parser."""
from __future__ import annotations

import re

JAVA_WORDS = set("abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while record yield var true false null".split())
JAVA_MEMBERS = {"equals", "hashCode", "toString", "getClass", "clone", "finalize", "notify", "notifyAll", "wait", "tag"}
C_WORDS = JAVA_WORDS | set("alignas alignof and and_eq asm auto atomic_cancel atomic_commit atomic_noexcept bitand bitor bool char8_t char16_t char32_t compl concept consteval constexpr constinit co_await co_return co_yield decltype delete dynamic_cast explicit export extern friend inline mutable namespace noexcept not not_eq nullptr operator or or_eq register reinterpret_cast requires signed sizeof static_assert static_cast struct template thread_local typedef typeid typename union unsigned using virtual wchar_t xor xor_eq restrict _Atomic".split())
PRIMITIVES = {"bool", "u8", "s8", "u16", "s16", "u32", "s32", "u64", "s64", "f32", "f64", "char", "string"}


def snake(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", value)


def camel(value: str) -> str:
    return "".join(word[:1].upper() + word[1:] for word in re.split(r"[^a-zA-Z0-9]", value) if word)


def jident(value: str) -> str:
    result = camel(value)
    result = result[:1].lower() + result[1:]
    return result + "_" if result in JAVA_WORDS | JAVA_MEMBERS else result


def cident(value: str) -> str:
    result = snake(value)
    return result + "_" if result in C_WORDS else result


class Graph:
    def __init__(self, data: dict, world: str, header: str):
        if set(data) != {"worlds", "interfaces", "types", "packages"}:
            raise ValueError("unsupported wasm-tools WIT graph format")
        if len(data["types"]) > 1024 or len(data["interfaces"]) > 128 or len(header) > 1024 * 1024:
            raise ValueError("Java binding graph exceeds its finite limits")
        self.data, self.types, self.header = data, data["types"], header
        candidates = []
        for item in data["worlds"]:
            package = data["packages"][item["package"]]["name"]
            base, _, version = package.partition("@")
            identity = base + "/" + item["name"] + ("@" + version if version else "")
            if world in (item["name"], identity): candidates.append(item)
        if len(candidates) != 1: raise ValueError("Java binding world must resolve exactly once")
        self.world = candidates[0]
        self.imports, self.exports, self.interface_names = [], [], {}
        self.export_ids = set()
        for direction in ("imports", "exports"):
            for key, item in self.world[direction].items():
                if set(item) != {"interface"} or set(item["interface"]) != {"id"}:
                    raise ValueError("Java profile requires named interface imports and exports")
                interface_id = item["interface"]["id"]
                interface = data["interfaces"][interface_id]
                if interface.get("package") is None or not interface.get("name"):
                    raise ValueError("Java profile rejects anonymous inline WIT interfaces")
                if direction == "exports": self.export_ids.add(interface_id)
                package = data["packages"][interface["package"]]["name"].split("@")[0]
                java_name = camel(package + "/" + interface["name"])
                if java_name in self.interface_names.values():
                    raise ValueError("Java profile rejects ambiguous multiple interface versions or import/export aliases")
                self.interface_names[interface_id] = java_name
                prefix = self.c_prefix(interface_id, direction == "exports")
                for function in interface["functions"].values():
                    if function["kind"] not in ("freestanding", "async-freestanding"):
                        raise ValueError("Java profile rejects WIT resource constructors and methods; freestanding operations are supported")
                    symbol = prefix + "_" + snake(function["name"])
                    match = re.search(r"^(?:extern )?([\w ]+) " + re.escape(symbol) + r"\(([^;]*)\);$", header, re.MULTILINE)
                    if match is None: raise ValueError("generated C signature not found: " + symbol)
                    params = []
                    for parameter in match[2].split(","):
                        parameter = parameter.strip()
                        if parameter == "void": continue
                        found = re.fullmatch(r"(\w+)\s+(\*?)(\w+)", parameter)
                        if found is None: raise ValueError("unsupported generated C parameter syntax")
                        params.append({"type": found[1], "pointer": bool(found[2]), "name": found[3]})
                    result = function.get("result")
                    expected = len(function["params"]) + (1 if match[1] == "void" and result is not None else 0)
                    if len(params) != expected: raise ValueError("unexpected flattened or asynchronous C ABI")
                    target = self.imports if direction == "imports" else self.exports
                    target.append({**function, "interface": interface_id, "symbol": symbol,
                                   "cReturn": match[1], "cParams": params, "operation": len(target)})
        if len(self.export_ids) != 1 or not self.exports:
            raise ValueError("Java profile currently requires one nonempty exported interface")
        if len(self.imports) > 256 or len(self.exports) > 64:
            raise ValueError("Java function inventory exceeds its finite limit")
        self.live, self.heights, self.active = set(), {}, set()
        for function in self.imports + self.exports:
            for parameter in function["params"]: self.visit(parameter["type"])
            self.visit(function.get("result"))
        self.resources = [index for index in sorted(self.live) if self.types[index]["kind"] == "resource"]
        for function in self.exports:
            for parameter in function["params"]:
                self.reject_export_resources(parameter["type"])
            self.reject_export_resources(function.get("result"))
        for index in self.resources:
            if self.types[index]["owner"]["interface"] in self.export_ids:
                raise ValueError("Java profile does not yet support exported resources")

    @classmethod
    def preflight(cls, data: dict, world: str):
        """Validate Java shape constraints before invoking the C ABI generator.

        This uses the same graph constructor and type checks. Placeholder C
        declarations only supply the constructor's parameter-count bookkeeping;
        the real C declarations are independently checked during generation.
        """
        if set(data) != {"worlds", "interfaces", "types", "packages"}:
            raise ValueError("unsupported wasm-tools WIT graph format")
        if len(data["types"]) > 1024 or len(data["interfaces"]) > 128:
            raise ValueError("Java binding graph exceeds its finite limits")
        selected = []
        for item in data["worlds"]:
            package = data["packages"][item["package"]]["name"]
            base, _, version = package.partition("@")
            identity = base + "/" + item["name"] + ("@" + version if version else "")
            if world in (item["name"], identity): selected.append(item)
        if len(selected) != 1: raise ValueError("Java binding world must resolve exactly once")
        probe = cls.__new__(cls)
        probe.data = data
        header = []
        for direction in ("imports", "exports"):
            for item in selected[0][direction].values():
                if set(item) != {"interface"} or set(item["interface"]) != {"id"}:
                    raise ValueError("Java profile requires named interface imports and exports")
                index = item["interface"]["id"]
                interface = data["interfaces"][index]
                if interface.get("package") is None or not interface.get("name"):
                    raise ValueError("Java profile rejects anonymous inline WIT interfaces")
                prefix = probe.c_prefix(index, direction == "exports")
                for function in interface["functions"].values():
                    params = ["probe_value arg" + str(i) for i, _ in enumerate(function["params"])]
                    if function.get("result") is not None: params.append("probe_value *result")
                    header.append("void " + prefix + "_" + snake(function["name"]) + "(" + (", ".join(params) or "void") + ");")
        graph = cls(data, world, "\n".join(header))
        # Generated Java identifiers are part of this profile, not WIT rules.
        names = [graph.name(index) for index in sorted(graph.live)]
        if len(names) != len(set(names)): raise ValueError("Java profile type-name collision; rename the WIT types")
        exports = [jident(function["name"]) for function in graph.exports]
        if len(exports) != len(set(exports)): raise ValueError("Java profile operation-name collision; rename the WIT operations")
        for index in graph.live:
            kind = graph.types[index]["kind"]
            if not isinstance(kind, dict): continue
            form, body = next(iter(kind.items()))
            fields = body.get("fields", body.get("cases", [])) if isinstance(body, dict) else []
            names = [jident(field["name"]) for field in fields]
            if len(names) != len(set(names)): raise ValueError("Java profile member-name collision; rename the WIT members")
        return graph

    def reject_export_resources(self, value, depth=0):
        if value is None or isinstance(value, str): return
        if depth > 32: raise ValueError("Java export type depth limit")
        kind = self.types[value]["kind"]
        if kind == "resource":
            raise ValueError("Java public RPC signatures do not support exported resources")
        form, body = next(iter(kind.items()))
        if form == "handle":
            ownership = "borrowed" if "borrow" in body else "owned"
            raise ValueError(f"Java public RPC signatures reject {ownership} resource export values")
        if form in {"type", "option", "list"}: children = [body]
        elif form in {"record", "variant"}: children = [item["type"] for item in body["fields" if form == "record" else "cases"]]
        elif form == "tuple": children = body["types"]
        elif form == "result": children = list(body.values())
        else: children = []
        for child in children: self.reject_export_resources(child, depth + 1)

    def c_prefix(self, index: int, exported: bool = False) -> str:
        interface = self.data["interfaces"][index]
        package = self.data["packages"][interface["package"]]["name"]
        base, _, version = package.partition("@")
        ambiguous = sum(p["name"].split("@")[0] == base for p in self.data["packages"]) > 1
        return ("exports_" if exported else "") + snake(base) + "_" + (snake(version) + "_" if ambiguous else "") + snake(interface["name"])

    def visit(self, value, depth=0):
        if value is None: return
        if depth > 32: raise ValueError("invalid or excessively nested WIT type")
        if isinstance(value, str):
            if value not in PRIMITIVES: raise ValueError("unsupported Java WIT scalar: " + value)
            return
        if type(value) is not int or not 0 <= value < len(self.types) or depth > 32:
            raise ValueError("invalid or excessively nested WIT type")
        if value in self.active: raise ValueError("recursive WIT type is unsupported")
        if value in self.heights:
            if depth + self.heights[value] > 32: raise ValueError("invalid or excessively nested WIT type")
            return
        self.active.add(value)
        self.live.add(value)
        definition = self.types[value]
        kind = definition["kind"]
        if kind == "resource":
            self.active.remove(value)
            self.heights[value] = 0
            return
        if not isinstance(kind, dict) or len(kind) != 1: raise ValueError("unsupported WIT type")
        form, body = next(iter(kind.items()))
        if form in ("type", "list", "option"): children = [body]
        elif form == "record":
            if not body["fields"]: raise ValueError("Java profile rejects empty WIT records: component records require a field")
            children = [p["type"] for p in body["fields"]]
        elif form == "tuple": children = body["types"]
        elif form == "result": children = [body["ok"], body["err"]]
        elif form == "variant": children = [p["type"] for p in body["cases"]]
        elif form == "handle": children = list(body.values())
        elif form in ("enum", "flags"):
            children = []
            if form == "flags" and len(body["flags"]) > 64: raise ValueError("Java supports at most 64 WIT flags")
        else: raise ValueError("unsupported Java WIT type: " + form)
        if len(children) > 1024: raise ValueError("Java WIT type member inventory exceeds its finite limit")
        for child in children: self.visit(child, depth + 1)
        self.heights[value] = max((1 + self.heights.get(child, 0) for child in children if child is not None), default=0)
        self.active.remove(value)

    def name(self, index: int) -> str:
        definition = self.types[index]
        if not definition["name"]: return "Value" + str(index)
        owner = definition.get("owner")
        if not owner or "interface" not in owner: raise ValueError("Java profile rejects world-owned named types")
        interface = owner["interface"]
        prefix = self.interface_names.get(interface)
        if prefix is None:
            item = self.data["interfaces"][interface]
            prefix = camel(self.data["packages"][item["package"]]["name"].split("@")[0] + "/" + item["name"])
        return prefix + camel(definition["name"])

    def jtype(self, value) -> str:
        if value is None: return "Unit"
        if isinstance(value, str):
            return {"bool": "Boolean", "u8": "Short", "s8": "Byte", "u16": "Integer", "s16": "Short",
                    "u32": "Long", "s32": "Integer", "u64": "Unsigned64", "s64": "Long", "f32": "Float",
                    "f64": "Double", "char": "Integer", "string": "String"}[value]
        kind = self.types[value]["kind"]
        if kind == "resource": return self.name(value)
        form, body = next(iter(kind.items()))
        if form == "type": return self.jtype(body)
        if form == "list": return "byte[]" if body == "u8" else "java.util.List<" + self.jtype(body) + ">"
        if form == "option": return "Option<" + self.jtype(body) + ">"
        if form == "result": return "Result<" + self.jtype(body["ok"]) + ", " + self.jtype(body["err"]) + ">"
        if form == "handle": return self.name(next(iter(body.values())))
        if form == "flags": return "Unsigned64"
        return self.name(value)

    @staticmethod
    def codec(value) -> str:
        return "Unit" if value is None else "T" + str(value) if type(value) is int else camel(value)
