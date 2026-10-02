"""Generate transaction client conversions; Protobuf remains authoritative."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def snake(value):
    return "".join("_" + letter.lower() if letter.isupper() else letter for letter in value).lstrip("_")


def pascal(value):
    return "".join(word[0].upper() + word[1:] for word in value.split("_"))


def rust_module(owner):
    if owner.startswith(".latent.transaction.v1."):
        return "t"
    if owner.startswith(".latent.control.v1."):
        return "c"
    raise ValueError("unreviewed transaction model owner")


def rust_value(field, expression, outbound, contract, old_contract):
    kind = field["type"]
    new_message = kind in contract["messages"] and not field.get("external", False)
    old_message = field.get("external", False) and kind in old_contract["messages"]
    old_grouped = old_message and any(item.get("oneof") for item in old_contract["messages"][kind])
    is_enum = kind in contract["enums"]
    if field.get("repeated"):
        if outbound and new_message:
            return expression + ".into_iter().map(TryInto::try_into).collect::<Result<_, _>>()?"
        if new_message or old_message:
            return expression + ".into_iter().map(Into::into).collect()"
        if is_enum:
            return expression + (".into_iter().map(|item| item.0).collect()" if outbound else ".into_iter().map(model::" + kind + ").collect()")
        return expression
    if field.get("optional"):
        if outbound and new_message:
            return expression + ".map(TryInto::try_into).transpose()?"
        if outbound and old_grouped:
            return expression + ".map(TryInto::try_into).transpose().map_err(|_| ValidationError::Shape)?"
        if new_message or old_message:
            return expression + ".map(Into::into)"
        if is_enum:
            return expression + (".map(|item| item.0)" if outbound else ".map(model::" + kind + ")")
        return expression
    if is_enum:
        return expression + ".0" if outbound else "model::" + kind + "(" + expression + ")"
    if outbound and new_message:
        return expression + ".try_into()?"
    if outbound and old_grouped:
        return expression + ".try_into().map_err(|_| ValidationError::Shape)?"
    return expression + ".into()" if new_message or old_message else expression


def rust(contract, old_contract):
    lines = ["// Generated from exact, fully qualified Protobuf transaction model owners.",
             "use crate::transaction as model;",
             "use latent_rpc::{control::v1 as c, transaction::v1 as t, phase4::ValidationError};", ""]
    for name, fields in contract["messages"].items():
        module = rust_module(contract["wireNames"][name])
        groups = {}
        for field in fields:
            if field.get("oneof"):
                groups.setdefault(field["oneof"], []).append(field)
        for outbound in [False, True]:
            origin = "model::" + name if outbound else module + "::" + name
            target = module + "::" + name if outbound else "model::" + name
            lines += [f"impl {'TryFrom' if outbound else 'From'}<{origin}> for {target} {{"]
            if outbound:
                lines += ["    type Error = ValidationError;", f"    fn try_from(value: {origin}) -> Result<Self, Self::Error> {{"]
            else:
                lines += [f"    fn from(value: {origin}) -> Self {{"]
            for group, members in groups.items():
                enum = module + "::" + snake(name) + "::" + pascal(group)
                if outbound:
                    lines.append(f"        let {group} = match ({', '.join('value.' + field['name'] for field in members)}) {{")
                    lines.append("            (" + ", ".join("None" for _ in members) + ") => None,")
                    for index, field in enumerate(members):
                        pattern = ", ".join("Some(member)" if position == index else "None" for position in range(len(members)))
                        scalar = rust_value({key: value for key, value in field.items() if key not in {"optional", "oneof"}}, "member", True, contract, old_contract)
                        lines.append(f"            ({pattern}) => Some({enum}::{pascal(field['name'])}({scalar})),")
                    lines += ["            _ => return Err(ValidationError::Shape),", "        };"]
                else:
                    lines.append(f"        let ({', '.join(field['name'] for field in members)}) = match value.{group} {{")
                    lines.append("            None => (" + ", ".join("None" for _ in members) + "),")
                    for index, field in enumerate(members):
                        scalar = rust_value({key: value for key, value in field.items() if key not in {"optional", "oneof"}}, "member", False, contract, old_contract)
                        values = ", ".join("Some(" + scalar + ")" if position == index else "None" for position in range(len(members)))
                        lines.append(f"            Some({enum}::{pascal(field['name'])}(member)) => ({values}),")
                    lines.append("        };")
            lines.append("        Ok(Self {" if outbound else "        Self {")
            for field in fields:
                if field.get("oneof"):
                    if not outbound:
                        lines.append("            " + field["name"] + ",")
                    continue
                lines.append("            " + field["name"] + ": " + rust_value(field, "value." + field["name"], outbound, contract, old_contract) + ",")
            if outbound:
                lines.extend("            " + group + "," for group in groups)
            lines += ["        })" if outbound else "        }", "    }", "}", ""]
    return subprocess.run(["rustfmt", "--edition", "2024"], input="\n".join(lines), text=True,
                          capture_output=True, check=True, timeout=30).stdout


def generate():
    contract = json.loads((ROOT / "sdk/profile/transaction-client-contract.json").read_bytes())
    old = json.loads((ROOT / "sdk/profile/contract.json").read_bytes())
    return {"sdk/rust/src/network/transaction/conversions.rs": rust(contract, old)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, expected in generate().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                raise ValueError("transaction conversion drift: " + name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="\n")
    print("Checked exact transaction conversions" if args.check else "Generated exact transaction conversions")


if __name__ == "__main__":
    main()
