"""Compare authoritative and compiled WIT without unstable parser table IDs."""
from __future__ import annotations


def surface(data: dict, world: str | None = None) -> dict:
    if set(data) != {"worlds", "interfaces", "types", "packages"}:
        raise ValueError("unsupported Java component WIT graph")
    if len(data["types"]) > 1024 or len(data["interfaces"]) > 128:
        raise ValueError("Java component WIT graph limit")

    def identity(package, name):
        base, _, version = data["packages"][package]["name"].partition("@")
        return base + "/" + name + ("@" + version if version else "")

    worlds = [item for item in data["worlds"] if world is None
              or world in (item["name"], identity(item["package"], item["name"]))]
    if len(worlds) != 1: raise ValueError("component WIT world must resolve exactly once")
    memo, active = {}, set()

    def value(index, depth=0):
        if index is None or isinstance(index, str): return index
        if type(index) is not int or not 0 <= index < len(data["types"]) or depth > 32 or index in active:
            raise ValueError("invalid or recursive Java WIT surface")
        if index in memo: return memo[index]
        active.add(index)
        definition = data["types"][index]
        kind = definition["kind"]
        child = lambda item: value(item, depth + 1)
        if kind == "resource":
            owner = data["interfaces"][definition["owner"]["interface"]]
            result = {"resource": identity(owner["package"], owner["name"]) + "/" + definition["name"]}
        else:
            form, body = next(iter(kind.items()))
            if form == "type": result = child(body)
            elif form in {"list", "option"}: result = {form: child(body)}
            elif form in {"record", "variant"}:
                key = "fields" if form == "record" else "cases"
                result = {form: [{"name": item["name"], "type": child(item["type"])} for item in body[key]]}
            elif form == "tuple": result = {form: list(map(child, body["types"]))}
            elif form in {"result", "handle"}: result = {form: {key: child(item) for key, item in body.items()}}
            elif form in {"enum", "flags"}:
                result = {form: [item["name"] for item in body["cases" if form == "enum" else "flags"]]}
            else: raise ValueError("unsupported compiled Java WIT type: " + form)
        active.remove(index)
        memo[index] = result
        return result

    result = {}
    for direction in ("imports", "exports"):
        result[direction] = {}
        for item in worlds[0][direction].values():
            if set(item) != {"interface"}: raise ValueError("compiled Java WIT has an unexpected world item")
            interface = data["interfaces"][item["interface"]["id"]]
            name = identity(interface["package"], interface["name"])
            if name in result[direction]: raise ValueError("duplicate compiled Java WIT interface")
            result[direction][name] = {
                "types": {name: value(index) for name, index in interface["types"].items()},
                "functions": {name: {"kind": function["kind"],
                    "params": [{"name": p["name"], "type": value(p["type"])} for p in function["params"]],
                    "result": value(function.get("result"))} for name, function in interface["functions"].items()},
            }
    return result
