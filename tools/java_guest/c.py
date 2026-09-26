"""Canonical ownership-aware C bridge; no replaced application implementation."""
from __future__ import annotations

from tools.java_guest.model import Graph, cident


class Codec:
    def __init__(self, graph: Graph): self.graph, self.counter = graph, 0

    def emit(self, value, expression: str, operation: str, wire: str) -> list[str]:
        self.counter += 1
        unique = "local_" + str(self.counter)
        expression = "(" + expression + ")"
        if value is None: return []
        if isinstance(value, str):
            if value == "string":
                if operation == "free": return [f"lsf_release({expression}.ptr, {expression}.len); {expression}.ptr = NULL; {expression}.len = 0;"]
                if operation == "read":
                    return [f"{expression}.len = (size_t)lsf_get({wire}, 4);", f"lsf_require({expression}.len <= LSF_MAX_BYTES);",
                            f"{expression}.ptr = lsf_allocate({expression}.len, 1);",
                            f"for (size_t {unique} = 0; {unique} < {expression}.len; {unique}++) {expression}.ptr[{unique}] = (uint8_t)lsf_get({wire}, 1);"]
                return [f"lsf_require({expression}.len <= LSF_MAX_BYTES); lsf_put({wire}, {expression}.len, 4);",
                        f"for (size_t {unique} = 0; {unique} < {expression}.len; {unique}++) lsf_put({wire}, {expression}.ptr[{unique}], 1);"]
            if operation == "free": return []
            width = 1 if value == "bool" else 4 if value == "char" else int(value[1:]) // 8
            if value in ("f32", "f64"):
                ctype = "uint32_t" if width == 4 else "uint64_t"
                return ([f"{ctype} {unique} = ({ctype})lsf_get({wire}, {width}); memcpy(&{expression}, &{unique}, {width});"] if operation == "read"
                        else [f"{ctype} {unique}; memcpy(&{unique}, &{expression}, {width}); lsf_put({wire}, {unique}, {width});"])
            if operation == "write": return [f"lsf_put({wire}, (uint64_t){expression}, {width});"]
            check = (f"lsf_require({unique} <= 1);" if value == "bool" else
                     f"lsf_require({unique} <= 0x10ffff && !({unique} >= 0xd800 && {unique} <= 0xdfff));" if value == "char" else "")
            return [f"uint64_t {unique} = lsf_get({wire}, {width}); {check} {expression} = (__typeof__({expression})){unique};"]
        kind = self.graph.types[value]["kind"]
        if kind == "resource": raise ValueError("resource values require explicit own or borrow")
        form, body = next(iter(kind.items()))
        if form == "type": return self.emit(body, expression, operation, wire)
        if form == "handle":
            if operation == "free": return []  # Ownership moved to Java or the canonical callee.
            return self.emit("u32", expression + ".__handle", operation, wire)
        if form in ("record", "tuple"):
            fields = body["fields"] if form == "record" else [{"name": "f" + str(i), "type": item} for i, item in enumerate(body["types"])]
            return [line for field in fields for line in self.emit(field["type"], expression + "." + cident(field["name"]), operation, wire)]
        if form == "list":
            lines = []
            if operation == "read":
                count = f"(size_t)lsf_get({wire}, 4)" if body == "u8" else f"lsf_count({wire})"
                bound = "LSF_MAX_BYTES" if body == "u8" else "LSF_MAX_ITEMS"
                lines.extend([f"{expression}.len = {count}; lsf_require({expression}.len <= {bound});",
                              f"{expression}.ptr = lsf_allocate({expression}.len, sizeof(*{expression}.ptr));"])
            elif operation == "write":
                bound = "LSF_MAX_BYTES" if body == "u8" else "LSF_MAX_ITEMS"
                lines.append(f"lsf_require({expression}.len <= {bound}); lsf_put({wire}, {expression}.len, 4);")
            lines.append(f"for (size_t {unique} = 0; {unique} < {expression}.len; {unique}++) {{")
            lines.extend(self.emit(body, expression + ".ptr[" + unique + "]", operation, wire))
            lines.append("}")
            if operation == "free": lines.append(f"lsf_release({expression}.ptr, {expression}.len * sizeof(*{expression}.ptr)); {expression}.ptr = NULL; {expression}.len = 0;")
            return lines
        if form in ("option", "result"):
            tag = "is_some" if form == "option" else "is_err"
            lines = self.emit("bool", expression + "." + tag, operation, wire)
            lines.append(f"if ({expression}.{tag}) {{")
            lines.extend(self.emit(body if form == "option" else body["err"], expression + (".val" if form == "option" else ".val.err"), operation, wire))
            if form == "result":
                lines.append("} else {"); lines.extend(self.emit(body["ok"], expression + ".val.ok", operation, wire))
            lines.append("}"); return lines
        if form == "variant":
            if operation == "read":
                lines = [f"uint64_t {unique} = lsf_get({wire}, 4); lsf_require({unique} < {len(body['cases'])});",
                         f"{expression}.tag = (__typeof__({expression}.tag)){unique};"]
            else:
                lines = self.emit("u32", expression + ".tag", operation, wire) if operation != "free" else []
            lines.append(f"switch ({expression}.tag) {{")
            for tag, case in enumerate(body["cases"]):
                lines.append(f"case {tag}: {{")
                lines.extend(self.emit(case["type"], expression + ".val." + cident(case["name"]), operation, wire))
                lines.append("break; }")
            lines.append("default: __builtin_trap(); }")
            return lines
        if form in ("enum", "flags"):
            if operation == "free": return []
            scalar = "u64" if form == "flags" else "u32"
            if operation == "read":
                check = (f"{unique} < {len(body['cases'])}" if form == "enum" else
                         "true" if len(body["flags"]) == 64 else f"({unique} >> {len(body['flags'])}) == 0")
                lines = [f"uint64_t {unique} = lsf_get({wire}, {8 if form == 'flags' else 4}); lsf_require({check});",
                         f"{expression} = (__typeof__({expression})){unique};"]
            else: lines = self.emit(scalar, expression, operation, wire)
            if form == "enum": lines.append(f"lsf_require({expression} < {len(body['cases'])});")
            elif len(body["flags"]) < 64: lines.append(f"lsf_require(((uint64_t){expression} >> {len(body['flags'])}) == 0);")
            return lines
        raise ValueError("unsupported C bridge form " + form)


def generate(graph: Graph) -> str:
    output = ['/* Generated from authoritative WIT. DO NOT EDIT. */', '#include "bridge.h"']
    codec = Codec(graph)
    for function in graph.exports:
        # ABI argument names are not contract identity. Isolate them from the
        # bridge's input/output/result locals, even for identically named WIT.
        params = [{**p, "name": "arg" + str(i)} for i, p in enumerate(function["cParams"])]
        parameters = ", ".join(p["type"] + " " + ("*" if p["pointer"] else "") + p["name"] for p in params) or "void"
        output.extend([f"{function['cReturn']} {function['symbol']}({parameters}) {{", "lsf_wire output = {0};"])
        for p, cp in zip(function["params"], params):
            expression = ("*" if cp["pointer"] else "") + cp["name"]
            output.extend(codec.emit(p["type"], expression, "write", "&output"))
            output.extend(codec.emit(p["type"], expression, "free", "NULL"))
        output.append(f"void *owned; lsf_wire input = lsf_invoke({function['operation']}, &output, &owned);")
        result = function.get("result")
        if result is not None:
            if function["cReturn"] == "void": result_name = "*" + params[-1]["name"]
            else:
                result_name = "result"
                output.append(function["cReturn"] + " result = {0};")
            output.extend(codec.emit(result, result_name, "read", "&input"))
        output.append("lsf_finish(&input); lsf_java_free(owned);")
        if function["cReturn"] != "void": output.append("return result;")
        output.append("}")
    output.extend(["void *lsf_java_host(int32_t operation, void *bytes, int32_t length) {",
                   "lsf_require(length >= 0 && (uint32_t)length <= LSF_MAX_BYTES);",
                   "lsf_wire input = {bytes, (size_t)length, 0, (size_t)length}; lsf_wire output = {0};",
                   "switch (operation) {"])
    for function in graph.imports:
        output.append(f"case {function['operation']}: {{")
        arguments, inputs = [], []
        params = [{**p, "name": "arg" + str(i)} for i, p in enumerate(function["cParams"])]
        for p, cp in zip(function["params"], params):
            output.append(cp["type"] + " " + cp["name"] + " = {0};")
            output.extend(codec.emit(p["type"], cp["name"], "read", "&input"))
            arguments.append(("&" if cp["pointer"] else "") + cp["name"])
            inputs.append((p["type"], cp["name"]))
        output.append("lsf_finish(&input);")
        result = function.get("result")
        if result is not None:
            return_type = function["cParams"][-1]["type"] if function["cReturn"] == "void" else function["cReturn"]
            output.append(return_type + " result = {0};")
            if function["cReturn"] == "void": arguments.append("&result")
        output.append(("result = " if function["cReturn"] != "void" else "") + function["symbol"] + "(" + ", ".join(arguments) + ");")
        for value, expression in inputs: output.extend(codec.emit(value, expression, "free", "NULL"))
        if result is not None:
            output.extend(codec.emit(result, "result", "write", "&output"))
            output.extend(codec.emit(result, "result", "free", "NULL"))
        output.append("break; }")
    for ordinal, index in enumerate(graph.resources):
        definition = graph.types[index]
        prefix, name = graph.c_prefix(definition["owner"]["interface"]), cident(definition["name"])
        output.extend([f"case {-1 - ordinal}: {{", "uint32_t handle = (uint32_t)lsf_get(&input, 4); lsf_finish(&input);",
                       f"{prefix}_{name}_drop_own(({prefix}_own_{name}_t){{(int32_t)handle}}); break; }}"])
    output.extend(["default: __builtin_trap(); }", "return lsf_result(&output);", "}"])
    return "\n".join(output) + "\n"
