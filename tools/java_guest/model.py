"""Closed supported WIT graph, obtained from the maintained wasm-tools parser."""
from __future__ import annotations

import re

JAVA_WORDS = set("abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while record yield var true false null".split())
C_WORDS = JAVA_WORDS | set("alignas alignof and and_eq asm auto atomic_cancel atomic_commit atomic_noexcept bitand bitor bool char8_t char16_t char32_t compl concept consteval constexpr constinit co_await co_return co_yield decltype delete dynamic_cast explicit export extern friend inline mutable namespace noexcept not not_eq nullptr operator or or_eq register reinterpret_cast requires signed sizeof static_assert static_cast struct template thread_local typedef typeid typename union unsigned using virtual wchar_t xor xor_eq restrict _Atomic".split())
PRIMITIVES = {"bool", "u8", "s8", "u16", "s16", "u32", "s32", "u64", "s64", "f32", "f64", "char", "string"}


def snake(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", value)


def camel(value: str) -> str:
    return "".join(word[:1].upper() + word[1:] for word in re.split(r"[^a-zA-Z0-9]", value) if word)


def jident(value: str) -> str:
    result = camel(value)
    result = result[:1].lower() + result[1:]
    return result + "_" if result in JAVA_WORDS else result


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
        self.live = set()
        for function in self.imports + self.exports:
            for parameter in function["params"]: self.visit(parameter["type"])
            self.visit(function.get("result"))
        self.resources = [index for index in sorted(self.live) if self.types[index]["kind"] == "resource"]
        for index in self.resources:
            if self.types[index]["owner"]["interface"] in self.export_ids:
                raise ValueError("Java profile does not yet support exported resources")

    def c_prefix(self, index: int, exported: bool = False) -> str:
        interface = self.data["interfaces"][index]
        package = self.data["packages"][interface["package"]]["name"]
        base, _, version = package.partition("@")
        ambiguous = sum(p["name"].split("@")[0] == base for p in self.data["packages"]) > 1
        return ("exports_" if exported else "") + snake(base) + "_" + (snake(version) + "_" if ambiguous else "") + snake(interface["name"])

    def visit(self, value, depth=0):
        if value is None: return
        if isinstance(value, str):
            if value not in PRIMITIVES: raise ValueError("unsupported Java WIT scalar: " + value)
            return
        if type(value) is not int or not 0 <= value < len(self.types) or depth > 32:
            raise ValueError("invalid or excessively nested WIT type")
        if value in self.live: return
        self.live.add(value)
        definition = self.types[value]
        kind = definition["kind"]
        if kind == "resource": return
        if not isinstance(kind, dict) or len(kind) != 1: raise ValueError("unsupported WIT type")
        form, body = next(iter(kind.items()))
        if form in ("type", "list", "option"): children = [body]
        elif form == "record": children = [p["type"] for p in body["fields"]]
        elif form == "tuple": children = body["types"]
        elif form == "result": children = [body["ok"], body["err"]]
        elif form == "variant": children = [p["type"] for p in body["cases"]]
        elif form == "handle": children = list(body.values())
        elif form in ("enum", "flags"):
            children = []
            if form == "flags" and len(body["flags"]) > 64: raise ValueError("Java supports at most 64 WIT flags")
        else: raise ValueError("unsupported Java WIT type: " + form)
        for child in children: self.visit(child, depth + 1)

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
