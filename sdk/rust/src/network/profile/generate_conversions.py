import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "sdk/profile"))
from generate import read_contract, pascal
from generate_fixtures import render_value


def converted(field, expression, direction, messages, enums):
    kind = field["type"]
    if field.get("map"):
        return expression + ".into_iter().collect()"
    if field.get("repeated"):
        return expression + ".into_iter().map(Into::into).collect()" if kind in messages else expression
    if field.get("optional"):
        return expression + ".map(Into::into)" if kind in messages else expression
    if kind in enums:
        return "model::" + kind + "(" + expression + ")" if direction == "model" else expression + ".0"
    return expression + ".into()" if kind in messages else expression


def conversion(name, module, fields, messages, enums):
    output = []
    grouped = [field for field in fields if field.get("oneof")]
    ordinary = [field for field in fields if not field.get("oneof")]
    for direction in ("model", "wire"):
        origin, target = (module + "::" + name, "model::" + name) if direction == "model" else ("model::" + name, module + "::" + name)
        fallible = bool(grouped) and direction == "wire"
        output += [f"impl {'TryFrom' if fallible else 'From'}<{origin}> for {target} {{"]
        if fallible:
            output += ["    type Error = super::RpcFailure;", f"    fn try_from(value: {origin}) -> Result<Self, Self::Error> {{"]
        else:
            output += [f"    fn from(value: {origin}) -> Self {{"]
        if grouped:
            group = grouped[0]["oneof"]
            owner = module + "::" + ''.join(('_' + letter.lower()) if letter.isupper() else letter for letter in name).lstrip('_')
            enum = owner + "::" + pascal(group)
            members = [field["name"] for field in grouped]
            if direction == "model":
                output += [f"        let ({', '.join(members)}) = match value.{group} {{", "            None => (" + ", ".join("None" for _ in members) + "),"]
                for position, field in enumerate(grouped):
                    values = ["Some(member.into())" if index == position else "None" for index in range(len(members))]
                    output += [f"            Some({enum}::{pascal(field['name'])}(member)) => ({', '.join(values)}),"]
                output += ["        };"]
            else:
                output += [f"        let {group} = match ({', '.join('value.' + member for member in members)}) {{", "            (" + ", ".join("None" for _ in members) + ") => None,"]
                for position, field in enumerate(grouped):
                    values = ["Some(member)" if index == position else "None" for index in range(len(members))]
                    output += [f"            ({', '.join(values)}) => Some({enum}::{pascal(field['name'])}(member.into())),"]
                output += ["            _ => return Err(super::RpcFailure::local(super::FailureKind::InvalidRequest)),", "        };"]
        output += ["        Ok(Self {" if fallible else "        Self {"]
        for field in ordinary:
            output += [f"            {field['name']}: {converted(field, 'value.' + field['name'], direction, messages, enums)},"]
        if grouped:
            output += ["            " + (group if direction == "wire" else ", ".join(members)) + ","]
        output += ["        })" if fallible else "        }", "    }", "}", ""]
    return output


def generated():
    profile, messages, enums = read_contract()
    selected = {}
    for source, names in profile["sources"].items():
        for name in names:
            if name in messages:
                selected[name] = "invocation" if "/invocation/" in source else "control"
    output = ["use crate::management as model;", "use latent_rpc::{control::v1 as control, invocation::v1 as invocation};", ""]
    for name, module in selected.items():
        output += conversion(name, module, messages[name], messages, enums)
    for name in ("ResourceBudget", "ErrorDetail", "PlatformError"):
        output += conversion(name, "invocation", messages[name], messages, enums)
    vectors = ["#![allow(clippy::too_many_lines)]", "", "use crate::management::*;", "use latent_rpc::{control::v1 as control, invocation::v1 as invocation};", "use prost::Message;", "use std::collections::BTreeMap;", "", "#[test]", "fn shared_vectors_roundtrip_through_actual_protobuf() {"]
    fixtures = json.loads((ROOT / "sdk/profile/fixtures.json").read_text(encoding="utf-8"))
    count = 0
    for case in fixtures["cases"]:
        name = case["type"]
        if name not in selected:
            continue
        count += 1
        literal = render_value({"type": name}, case["value"], "rust", messages, enums)
        wire = selected[name] + "::" + name
        grouped = [field for field in messages[name] if field.get("oneof")]
        contradictory = sum(field["name"] in case["value"] for field in grouped) > 1
        vectors += ["    {", f"        let value = {literal};"]
        if contradictory:
            vectors += [f"        assert!({wire}::try_from(value).is_err(), {json.dumps(case['name'])});"]
        else:
            expression = f"{wire}::try_from(value.clone()).unwrap()" if grouped else f"{wire}::from(value.clone())"
            vectors += [f"        let encoded = {expression}.encode_to_vec();", f"        let decoded = {wire}::decode(encoded.as_slice()).unwrap();", f"        assert_eq!({name}::from(decoded), value, {json.dumps(case['name'])});"]
        vectors += ["    }"]
    vectors += [f'    println!("shared protobuf model vectors: {count}");', "}", ""]
    files = {
        "sdk/rust/src/network/profile/conversions.rs": "\n".join(output),
        "sdk/rust/src/network/profile/vectors.rs": "\n".join(vectors),
    }
    return {name: subprocess.run(["rustfmt", "--edition", "2021"], input=content, text=True, capture_output=True, check=True).stdout for name, content in files.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", action="store_true")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if arguments.patch == arguments.check:
        parser.error("choose --patch or --check")
    stale = []
    if arguments.patch:
        print("*** Begin Patch")
    for name, content in generated().items():
        path = ROOT / name
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old == content:
            continue
        stale.append(name)
        if arguments.patch:
            print(("*** Add File: " if old is None else "*** Update File: ") + path.as_posix())
            if old is None:
                print("\n".join("+" + line for line in content.splitlines()))
            else:
                for line in list(difflib.unified_diff(old.splitlines(), content.splitlines(), n=3))[2:]:
                    print("@@" if line.startswith("@@") else line)
    if arguments.patch:
        print("*** End Patch")
    elif stale:
        raise SystemExit("stale profile adapters: " + ", ".join(stale))
    else:
        print("Rust profile conversions and shared protobuf vectors are current")


if __name__ == "__main__":
    main()
