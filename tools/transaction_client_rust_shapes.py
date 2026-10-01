"""Generate bounded Rust model visitors and exact Protobuf predecode schemas."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

from transaction_client_models import ROOT, descriptor, renderer


def identifier(name: str) -> str:
    return name.strip(".").replace(".", "_").upper()


def native(name: str) -> str:
    parts = name.strip(".").split(".")
    if len(parts) != 4 or parts[0] != "latent" or parts[2] != "v1":
        raise ValueError("unreviewed native message owner: " + name)
    return f"latent_rpc::{parts[1]}::v1::{parts[3]}"


def rustfmt(source: str) -> str:
    return subprocess.run(["rustfmt", "--edition", "2024"], input=source, text=True,
                          capture_output=True, check=True, timeout=30).stdout


def generate() -> dict[str, str]:
    contract = json.loads((ROOT / "sdk/profile/transaction-client-contract.json").read_bytes())
    old = json.loads((ROOT / "sdk/profile/contract.json").read_bytes())
    image = descriptor()
    messages = {}

    def visit(items, prefix):
        for item in items:
            name = prefix + "." + item["name"]
            messages[name] = item
            visit(item.get("nestedType", []), name)

    for source in image["file"]:
        visit(source.get("messageType", []), "." + source["package"])
    reachable = set()

    def reach(name):
        if name in reachable:
            return
        if name not in messages:
            raise ValueError("absent exact wire message: " + name)
        reachable.add(name)
        for field in messages[name].get("field", []):
            if field["type"] == "TYPE_MESSAGE":
                reach(field["typeName"])

    for operation in contract["operations"]:
        reach(operation["wireResponse"])
    # Transport error details use the established control PlatformError owner.
    reach(".latent.control.v1.PlatformError")
    wire = ["// Generated from exact Protobuf owners. Do not edit.",
            "use super::codec::{Field, Kind, Schema};", ""]
    for name in sorted(reachable):
        item = messages[name]
        fields = item.get("field", [])
        if len(fields) > 64:
            raise ValueError("wire schema exceeds the fixed field-count bound")
        size = "256" if item.get("options", {}).get("mapEntry", False) else "2 * std::mem::size_of::<" + native(name) + ">() + 64"
        wire += [f"pub(super) static {identifier(name)}: Schema = Schema {{",
                 f"    allocation: {size},", "    fields: &["]
        for field in fields:
            kind = field["type"]
            if kind == "TYPE_MESSAGE":
                target = field["typeName"]
                if messages[target].get("options", {}).get("mapEntry", False):
                    shape = "Kind::Map(&" + identifier(target) + ")"
                else:
                    shape = "Kind::Message(&" + identifier(target) + ")"
            else:
                shape = {"TYPE_STRING": "Kind::String", "TYPE_BYTES": "Kind::Bytes",
                         "TYPE_BOOL": "Kind::Bool", "TYPE_UINT64": "Kind::U64",
                         "TYPE_UINT32": "Kind::U32", "TYPE_INT32": "Kind::I32",
                         "TYPE_ENUM": "Kind::I32"}.get(kind)
                if shape is None:
                    raise ValueError("unreviewed wire kind: " + kind)
            oneof = int(field["oneofIndex"]) + 1 if "oneofIndex" in field else 0
            repeated = str(field["label"] == "LABEL_REPEATED").lower()
            maximum = 256 if field["name"] == "required_record_ids" else 128
            wire.append(f"        Field {{ number: {field['number']}, kind: {shape}, repeated: {repeated}, maximum: {maximum}, oneof: {oneof} }},")
        wire += ["    ],", "};", ""]

    # Visitors run before the owned application model is converted. This keeps
    # oversized collections from allocating another native graph during encode.
    shapes = ["// Generated bounded visitors. Do not edit.",
              "use super::codec::Budget;", "use crate::transaction as model;",
              "use latent_rpc::phase4::ValidationError;", ""]
    done = set()

    def model(name, external=False):
        return "crate::management::" + name if external else "model::" + name

    def visitor(name, external=False):
        nonlocal shapes
        key = (name, external)
        if key in done:
            return
        done.add(key)
        fields = (old if external else contract)["messages"][name]
        for field in fields:
            child = field["type"]
            owner = external or bool(field.get("external"))
            if child in (old if owner else contract)["messages"]:
                visitor(child, owner)
        method = ("legacy_" if external else "") + renderer().snake(name)
        shapes.extend([f"fn {method}(value: &{model(name, external)}, depth: usize, budget: &mut Budget) -> Result<(), ValidationError> {{",
                       "    let _ = value;",
                       f"    budget.node(std::mem::size_of::<{model(name, external)}>(), depth)?;"])
        for field in fields:
            member = "value." + field["name"]
            kind = field["type"]
            owner = external or bool(field.get("external"))
            if field.get("map"):
                shapes += [f"    if {member}.len() > 32 {{ return Err(ValidationError::Capacity); }}",
                           f"    for (key, member) in &{member} {{ budget.data(key.len())?; budget.data(member.len())?; }}"]
                continue
            is_message = kind in (old if owner else contract)["messages"]
            action = ("legacy_" if owner else "") + renderer().snake(kind) + "(member, depth + 1, budget)?;" if is_message else "budget.data(member.len())?;" if kind in {"string", "bytes"} else ""
            if field.get("repeated"):
                shapes.append(f"    if {member}.len() > 128 {{ return Err(ValidationError::Capacity); }}")
                if action:
                    shapes.append(f"    for member in &{member} {{ {action} }}")
            elif field.get("optional") or field.get("oneof"):
                if action:
                    shapes.append(f"    if let Some(member) = &{member} {{ {action} }}")
            elif action:
                shapes.append("    { let member = &" + member + "; " + action + " }")
        shapes += ["    Ok(())", "}", ""]

    for operation in contract["operations"]:
        visitor(operation["request"])
    shapes += ["pub(super) trait ModelShape { fn validate_shape(&self) -> Result<(), ValidationError>; }", ""]
    for operation in contract["operations"]:
        name = operation["request"]
        shapes += [f"impl ModelShape for model::{name} {{",
                   "    fn validate_shape(&self) -> Result<(), ValidationError> {",
                   f"        {renderer().snake(name)}(self, 0, &mut Budget::new())", "    }", "}"]
    return {
        "sdk/rust/src/network/transaction/wire_schemas.rs": rustfmt("\n".join(wire)),
        "sdk/rust/src/network/transaction/model_shapes.rs": rustfmt("\n".join(shapes)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, source in generate().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != source:
                raise ValueError("transaction Rust shape drift: " + name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8", newline="\n")
    print("Checked bounded Rust transaction shapes" if args.check else "Generated bounded Rust transaction shapes")


if __name__ == "__main__":
    main()
