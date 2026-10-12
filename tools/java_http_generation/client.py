"""Normal typed fetch client over the node's canonical WIT value format."""
import json
from pathlib import Path
from tools.rust_capsule_project import read_file, canonical


def ts_type(shape) -> str:
    if shape is None: return "null"
    if isinstance(shape, str):
        return "boolean" if shape == "bool" else "string" if shape in {"string", "char", "u64", "s64", "f32", "f64"} else "number"
    kind, body = next(iter(shape.items()))
    if kind == "list": return "ReadonlyArray<" + ts_type(body) + ">"
    if kind == "tuple": return "readonly [" + ", ".join(map(ts_type, body)) + "]"
    if kind == "record": return "{ " + "; ".join("readonly " + json.dumps(field["name"]) + ": " + ts_type(field["type"]) for field in body) + " }"
    if kind == "enum": return " | ".join(map(json.dumps, body)) or "never"
    if kind == "flags": return "ReadonlyArray<" + (" | ".join(map(json.dumps, body)) or "never") + ">"
    if kind == "variant":
        return " | ".join("{ readonly case: " + json.dumps(case["name"]) + ("; readonly value: " + ts_type(case["type"]) if case["type"] is not None else "") + " }" for case in body)
    if kind == "option": return "{ readonly none: null } | { readonly some: " + ts_type(body) + " }"
    if kind == "result": return "{ readonly ok: " + ts_type(body["ok"]) + " } | { readonly err: " + ts_type(body["err"]) + " }"
    raise ValueError("client-generation: public resources and unknown shapes cannot be transported")


def files(routes: list[dict]) -> dict[str, bytes]:
    schema = {"profile": "latent.java-http.adapter.v1", "routes": routes}
    methods, declarations = [], []
    for route in routes:
        signature = route["signature"]
        arguments = ["arg" + str(index) for index in range(len(signature["params"]))]
        methods.append("  " + route["clientName"] + "(" + ", ".join(arguments + ["options = {}"])
            + ") { return this.call(" + json.dumps(route["clientName"]) + ", [" + ", ".join(arguments) + "], options); }")
        result = "readonly []" if signature["result"] is None else "readonly [" + ts_type(signature["result"]) + "]"
        parameters = [argument + ": " + ts_type(parameter["type"]) for argument, parameter in zip(arguments, signature["params"])]
        declarations.append("  " + route["clientName"] + "(" + ", ".join(parameters + ["options?: {signal?: AbortSignal}"])
            + "): Promise<{status: number; value: " + result + " | string}>;")
    runtime = read_file(Path(__file__).with_name("client-runtime.mjs")).decode()
    client = "// Full-width integers and floating values retain canonical string representations.\nconst schema = " + canonical(schema).decode() + ";\n" + runtime.replace("// @METHODS@", "\n".join(methods))
    declaration = "// Generated from actual WIT. u64/s64/f32/f64 use checked canonical strings.\nexport declare class JavaHttpClient {\n  constructor(origin: string);\n" + "\n".join(declarations) + "\n}\n"
    return {"client.mjs": client.encode(), "client.d.ts": declaration.encode(), "schema.json": canonical(schema) + b"\n"}
