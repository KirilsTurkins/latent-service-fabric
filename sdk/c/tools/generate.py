from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from google.protobuf import descriptor_pb2


SDK = Path(__file__).resolve().parents[1]
ROOT = SDK.parents[1]
FIELD = descriptor_pb2.FieldDescriptorProto


def snake(value):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def generate(build, output):
    output.mkdir(parents=True, exist_ok=True)
    profile = json.loads((ROOT / "sdk/profile/client-profile.json").read_text())
    sources = [name.removeprefix("api/proto/") for name in profile["sources"]]
    protoc = build / "deps/protoc/bin/protoc"
    subprocess.run([str(protoc), "-I", str(ROOT / "api/proto"), "--include_imports",
                    "--descriptor_set_out=" + str(output / "rpc.pb"),
                    "--python_out=" + str(output), *sources], check=True, timeout=30)
    descriptor = descriptor_pb2.FileDescriptorSet.FromString((output / "rpc.pb").read_bytes())
    all_messages = {}
    locations = {}

    def collect(prefix, messages, filename):
        for message in messages:
            name = prefix + "." + message.name
            all_messages[name] = message
            locations[name] = filename
            collect(name, message.nested_type, filename)

    for source in descriptor.file:
        collect(source.package, source.message_type, source.name)
    selected = set()
    for source in descriptor.file:
        names = profile["sources"].get("api/proto/" + source.name, [])
        selected.update(source.package + "." + name for name in names
                        if source.package + "." + name in all_messages)
    pending = list(selected)
    while pending:
        for field in all_messages[pending.pop()].field:
            if field.type == FIELD.TYPE_MESSAGE and field.type_name[1:] not in selected:
                selected.add(field.type_name[1:])
                pending.append(field.type_name[1:])
    kinds = {FIELD.TYPE_STRING: "LSF_STRING", FIELD.TYPE_BYTES: "LSF_BYTES",
             FIELD.TYPE_UINT64: "LSF_U64", FIELD.TYPE_UINT32: "LSF_U32",
             FIELD.TYPE_INT32: "LSF_I32", FIELD.TYPE_ENUM: "LSF_I32",
             FIELD.TYPE_BOOL: "LSF_BOOL", FIELD.TYPE_MESSAGE: "LSF_MESSAGE"}

    def cname(name):
        message = all_messages[name]
        if message.options.map_entry:
            return "latent_key_value" if message.field[1].type == FIELD.TYPE_STRING else "latent_profile_counter"
        return "latent_profile_" + snake(message.name)

    def symbol(name):
        return "lsf_" + name.replace(".", "_")

    for source in descriptor.file:
        options = [f'{source.package}.* type:FT_CALLBACK no_unions:true callback_datatype:"lsf_pb_slot" callback_function:"lsf_wire_callback"',
                   f'{source.name} include:"wire.h"']
        for name, message in all_messages.items():
            if locations[name] != source.name:
                continue
            if name not in selected:
                options.append(f"{name} skip_message:true")
            for field in message.field if name in selected else []:
                if field.type == FIELD.TYPE_ENUM:
                    options.append(f"{name}.{field.name} type_override:TYPE_INT32")
        path = output / Path(source.name).with_suffix(".options")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(options) + "\n")
    nanopb = next((build / "deps/nanopb").glob("nanopb-*"))
    for source in descriptor.file:
        single = output / (Path(source.name).stem + ".descriptor.pb")
        subprocess.run([str(protoc), "-I", str(ROOT / "api/proto"), "--include_imports",
                        "--descriptor_set_out=" + str(single), source.name], check=True, timeout=30)
        subprocess.run([sys.executable, str(nanopb / "generator/nanopb_generator.py"),
                        "--quiet", "--error-on-unmatched", "--no-timestamp", "-I", str(output),
                        "-D", str(output), str(single)], check=True, timeout=30)
    header = ["#ifndef LSF_WIRE_GENERATED_H", "#define LSF_WIRE_GENERATED_H", '#include "wire.h"']
    body = ['#include "wire_generated.h"', "#include <stddef.h>"]
    for source in descriptor.file:
        body.append('#include "' + str(Path(source.name).with_suffix(".pb.h")) + '"')
    for name in sorted(selected):
        header.append(f"extern const lsf_message {symbol(name)};")
    for name in sorted(selected):
        message = all_messages[name]
        native = cname(name)
        body.append(f"static const lsf_field {symbol(name)}_fields[] = {{")
        for field in sorted(message.field, key=lambda item: item.number):
            repeated = field.label == FIELD.LABEL_REPEATED
            nested = all_messages.get(field.type_name[1:])
            present = not repeated and (field.proto3_optional or field.HasField("oneof_index")
                                         or field.type == FIELD.TYPE_MESSAGE)
            presence = f"offsetof({native}, has_{field.name})" if present else "LSF_NO_OFFSET"
            count = f"offsetof({native}, {field.name}_count)" if repeated else "LSF_NO_OFFSET"
            stride = f"sizeof((({native} *)0)->{field.name}[0])" if repeated else f"sizeof((({native} *)0)->{field.name})"
            submessage = "&" + symbol(field.type_name[1:]) if nested else "NULL"
            group = field.oneof_index + 1 if field.HasField("oneof_index") and not field.proto3_optional else 0
            body.append(f"    {{{field.number}, {kinds[field.type]}, offsetof({native}, {field.name}), {presence}, {count}, {stride}, {group}, "
                        + ("true" if nested and nested.options.map_entry else "false") + f", {submessage}}},")
        body.extend(["};", f"const lsf_message {symbol(name)} = {{",
                     f"    &{name.replace('.', '_')}_msg, {symbol(name)}_fields,",
                     f"    {len(message.field)}, sizeof({native}), sizeof({name.replace('.', '_')})", "};",
                     f'_Static_assert(sizeof({name.replace(".", "_")}) <= LSF_WIRE_STORAGE, "wire scratch bound");'])
    body.append("const lsf_rpc lsf_rpcs[8] = {")
    for operation in profile["operations"]:
        service_name = operation["service"]
        candidates = [(source, service) for source in descriptor.file for service in source.service
                      if source.package + "." + service.name == service_name]
        if len(candidates) != 1:
            raise ValueError("RPC service selection")
        method = next(method for method in candidates[0][1].method if method.name == operation["name"])
        if method.client_streaming or method.server_streaming:
            raise ValueError("only unary RPCs are supported")
        body.append(f'    {{"/{service_name}/{method.name}", &{symbol(method.input_type[1:])}, &{symbol(method.output_type[1:])}}},')
    body.append("};")
    header.extend(["extern const lsf_rpc lsf_rpcs[8];", "#endif"])
    (output / "wire_generated.h").write_text("\n".join(header) + "\n")
    (output / "wire_generated.c").write_text("\n".join(body) + "\n")
    identities = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in profile["sources"]}
    (output / "source-sha256.json").write_text(json.dumps(identities, indent=2, sort_keys=True) + "\n")
    subprocess.run([sys.executable, str(SDK / "tools/wire_vectors.py"), str(output)], check=True, timeout=30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.build_dir / "generated"
    if args.check:
        with tempfile.TemporaryDirectory(prefix="latent-c-generation-") as temporary:
            candidate = Path(temporary)
            generate(args.build_dir, candidate)
            for path in candidate.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    previous = output / path.relative_to(candidate)
                    if not previous.is_file() or previous.read_bytes() != path.read_bytes():
                        raise RuntimeError(f"nonreproducible generated C binding: {path.name}")
    else:
        generate(args.build_dir, output)
    print("C authoritative protobuf generation verified")


if __name__ == "__main__":
    main()
