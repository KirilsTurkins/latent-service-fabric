"""Generate additive transaction client models from the authoritative descriptors.

The existing stateless models and their generator are reused without rewriting
them. Fully qualified Protobuf owners survive in the shared transaction index;
in particular, transaction paging never aliases control-plane paging.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = "sdk/profile/transaction-requirements-v1.json"
SCALARS = {"TYPE_STRING": "string", "TYPE_BYTES": "bytes", "TYPE_BOOL": "bool",
           "TYPE_UINT64": "uint64", "TYPE_UINT32": "uint32", "TYPE_INT32": "int32"}
OUTPUTS = {
    "rust": "sdk/rust/src/transaction/models.rs",
    "go": "sdk/go/transaction/models.go",
    "typescript": "sdk/typescript-client/src/transactions.ts",
    "java": "sdk/java-client/src/main/java/dev/latent/sdk/Transactions.java",
    "dotnet": "sdk/dotnet/Latent.Sdk/Transactions.cs",
    "c": "sdk/c/include/latent/transaction.h",
    "index": "sdk/profile/transaction-client-contract.json",
}


def renderer():
    spec = importlib.util.spec_from_file_location("latent_transaction_client_renderers", ROOT / "sdk/profile/generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def descriptor() -> dict:
    version = subprocess.run(["buf", "--version"], capture_output=True, check=True, timeout=10).stdout.strip()
    if version != b"1.72.0":
        raise ValueError("transaction client generation requires pinned Buf 1.72.0")
    (ROOT / "target").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="transaction-client-descriptor-", dir=ROOT / "target") as directory:
        path = Path(directory) / "descriptor.json"
        subprocess.run(["buf", "--timeout", "30s", "build", str(ROOT / "api/proto"),
                        "--as-file-descriptor-set", "--exclude-source-info", "-o", str(path)],
                       check=True, timeout=40, cwd=ROOT)
        raw = path.read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("transaction client descriptor exceeds its bounded input")
        return json.loads(raw)


def node_descriptor(requirements: dict) -> str:
    """Reuse the maintained Node protobuf codec with exact Phase 4 descriptors."""
    sources = sorted({service["source"] for service in requirements["externalClient"]["requiredServices"]})
    with tempfile.TemporaryDirectory(prefix="transaction-node-descriptor-", dir=ROOT / "target") as directory:
        path = Path(directory) / "descriptor.bin"
        command = ["buf", "--timeout", "30s", "build", str(ROOT / "api/proto"),
                   "--as-file-descriptor-set", "--exclude-source-info", "-o", str(path)]
        for source in sources:
            command.extend(["--path", str(ROOT / source)])
        subprocess.run(command, check=True, timeout=40, cwd=ROOT)
        raw = path.read_bytes()
        if not 0 < len(raw) <= 128 * 1024:
            raise ValueError("transaction Node descriptor exceeds its bounded input")
    digest = sha256(raw).hexdigest()
    return ('// Generated from the exact maintained transaction descriptors.\n'
            'import { Buffer } from "node:buffer";\n\n'
            f'export const descriptorDigest = "sha256:{digest}";\n'
            f'export const descriptorBytes = Buffer.from("{base64.b64encode(raw).decode("ascii")}", "base64");\n')


def definitions(image: dict) -> tuple[dict, dict, dict]:
    messages, enums, files = {}, {}, {}
    for source in image["file"]:
        prefix = "." + source["package"] + "."
        for item in source.get("messageType", []):
            messages[prefix + item["name"]] = item
        for item in source.get("enumType", []):
            enums[prefix + item["name"]] = item
        files[source["name"]] = source
    return messages, enums, files


def derive(image: dict, requirements: dict, legacy_profile: dict, legacy_messages: dict, legacy_enums: dict) -> dict:
    all_messages, all_enums, files = definitions(image)
    selected = set()
    roots, operations = {}, []
    if requirements["wireProfile"] != "lsf-transaction-v1":
        raise ValueError("unsupported transaction client wire profile")
    for service in requirements["externalClient"]["requiredServices"]:
        filename = service["source"].removeprefix("api/proto/")
        source = files[filename]
        prefix = "." + source["package"] + "."
        for name in service["messages"] + service["enums"]:
            selected.add(prefix + name)
        roots[filename] = {"sha256": service["sourceSha256"], "service": service["service"]}
        declared = next((item for item in source.get("service", [])
                         if source["package"] + "." + item["name"] == service["service"]), None)
        if declared is None:
            raise ValueError("missing authoritative transaction client service")
        methods = {method["name"]: method for method in declared["method"]}
        for operation in service["operations"]:
            method = methods[operation["name"]]
            if (method["inputType"] != prefix + operation["request"]
                    or method["outputType"] != prefix + operation["response"]
                    or method.get("clientStreaming", False) or method.get("serverStreaming", False)):
                raise ValueError("transaction RPC definition contradicts the mandatory profile")
            operations.append({**operation, "service": service["service"],
                               "wireRequest": method["inputType"], "wireResponse": method["outputType"]})
    wire_names = {name.rsplit(".", 1)[1]: name for name in sorted(selected)}
    if len(wire_names) != len(selected):
        raise ValueError("ambiguous transaction model name needs an explicit qualified projection")
    old_names = set(legacy_messages) | set(legacy_enums)
    external_owners = set()
    for filename, names in legacy_profile["sources"].items():
        source = files[filename.removeprefix("api/proto/")]
        external_owners.update("." + source["package"] + "." + name for name in names)
    # These three invocation-owned messages already have explicit conversions to
    # the stateless shared models; this is the established protocol projection.
    external_owners.update(".latent.invocation.v1." + name
                           for name in ("ResourceBudget", "ErrorDetail", "PlatformError"))
    external = set()
    messages, enums = {}, {}
    for name, wire_name in sorted(wire_names.items()):
        if wire_name in all_enums:
            prefix = renderer().snake(name).upper() + "_"
            enums[name] = {item["name"].removeprefix(prefix): item["number"] for item in all_enums[wire_name]["value"]}
            continue
        if wire_name not in all_messages:
            raise ValueError("required transaction model is absent from authoritative descriptors")
        item = all_messages[wire_name]
        fields = []
        for raw in sorted(item.get("field", []), key=lambda field: field["number"]):
            field = {"name": raw["name"], "number": raw["number"], "jsonName": raw["jsonName"]}
            kind = raw["type"]
            if kind in SCALARS:
                field["type"] = SCALARS[kind]
            elif kind in {"TYPE_MESSAGE", "TYPE_ENUM"}:
                target = raw["typeName"]
                short = target.rsplit(".", 1)[1]
                field["type"] = short
                field["wireType"] = target
                if target not in selected:
                    if short not in old_names or target not in external_owners:
                        raise ValueError("unreviewed external transaction model owner: " + target)
                    if short in wire_names:
                        raise ValueError("external owner cannot alias a transaction model: " + target)
                    external.add(short)
                    field["external"] = True
            else:
                raise ValueError("unsupported transaction field kind: " + kind)
            repeated = raw["label"] == "LABEL_REPEATED"
            if repeated:
                field["repeated"] = True
            elif raw.get("proto3Optional", False) or "oneofIndex" in raw or kind == "TYPE_MESSAGE":
                field["optional"] = True
            if "oneofIndex" in raw and not raw.get("proto3Optional", False):
                field["oneof"] = item["oneofDecl"][raw["oneofIndex"]]["name"]
            fields.append(field)
        messages[name] = fields
    ordered, visiting = {}, set()

    def visit(name):
        if name in ordered:
            return
        if name in visiting:
            raise ValueError("recursive transaction model requires an explicit bounded representation")
        visiting.add(name)
        for field in messages[name]:
            if field["type"] in messages and not field.get("external", False):
                visit(field["type"])
        visiting.remove(name)
        ordered[name] = messages[name]

    for name in messages:
        visit(name)
    return {
        "schemaVersion": "latent.transaction-client.models.v1",
        "profile": requirements["externalClient"]["profile"],
        "wireProfile": requirements["wireProfile"],
        "hostAbiDigest": requirements["hostAbiDigest"],
        "preparationProfileDigest": requirements["preparationProfileDigest"],
        "evidenceKind": "generated-model-definition",
        "externalClientExecutionQualified": False,
        "operations": operations,
        "sources": roots,
        "wireNames": wire_names,
        "externalTypes": sorted(external),
        "messages": ordered,
        "enums": enums,
    }


def qualify_external(text: str, contract: dict, language: str) -> str:
    for name in sorted(contract["externalTypes"], key=len, reverse=True):
        prefix = {"rust": "crate::management::", "go": "profile.", "typescript": "profile.",
                  "java": "Management.", "dotnet": "global::Latent.Sdk.Profile."}.get(language)
        if language == "c":
            text = re.sub(r"\blatent_transaction_" + renderer().snake(name) + r"\b",
                          "latent_profile_" + renderer().snake(name), text)
        elif language == "go":
            # A Go field can share its type's PascalCase spelling (Success,
            # AuditAck). Qualify the type position while preserving the field.
            text = re.sub(r"(?m)^(\s+\w+\s+)(\*|\[\])?" + re.escape(name) + r"\b",
                          lambda match: match[1] + (match[2] or "") + prefix + name, text)
        elif language == "dotnet":
            # Record properties likewise retain their unqualified member name.
            text = re.sub(r"\b" + re.escape(name) + r"\b(?=\??(?:\s+\w+|[>\]]))",
                          prefix + name, text)
        else:
            text = re.sub(r"\b" + re.escape(name) + r"\b", prefix + name, text)
    return text


def render(contract: dict, language: str) -> str:
    old = renderer()
    profile = {"operations": []}
    messages, enums = contract["messages"], contract["enums"]
    if language == "rust":
        source = old.rust_models(profile, messages, enums)
        source = source.split("#[derive(Debug, Clone, PartialEq, Eq)]\npub struct ClientResponse", 1)[0]
        source = source.replace("use std::future::Future;\n", "").replace("use std::pin::Pin;\n", "")
        if not any(field.get("map") for fields in messages.values() for field in fields):
            source = source.replace("use std::collections::BTreeMap;\n", "")
        for name, fields in messages.items():
            if sum(field["type"] == "bool" for field in fields) > 3:
                # These descriptor fields are independent observed wire facts.
                # Combining them into a local state enum would change the ABI.
                source = source.replace(f"pub struct {name} {{",
                                        "#[allow(clippy::struct_excessive_bools)]\n"
                                        f"pub struct {name} {{")
    elif language == "go":
        source = old.go_models(profile, messages, enums).split("type ClientResponse[", 1)[0]
        source = source.replace('package profile\n\nimport (\n\t"context"\n\t"strconv"\n)\n',
                                'package transaction\n\nimport "latent.dev/sdk/go/profile"\n')
    elif language == "typescript":
        source = 'import type * as profile from "./management.js";\n\n' + old.ts_models(profile, messages, enums).split("export interface ClientResponse<", 1)[0]
    elif language == "java":
        source = old.java_models(profile, messages, enums).split("    public record ClientResponse<", 1)[0] + "}\n"
        source = source.replace("public final class Management", "public final class Transactions").replace("private Management()", "private Transactions()")
        source = source.replace("import java.util.concurrent.CompletableFuture;\n", "")
    elif language == "dotnet":
        source = old.dotnet_models(profile, messages, enums).split("/// <summary>A fully owned unary response", 1)[0]
        source = source.replace("namespace Latent.Sdk.Profile;", "namespace Latent.Sdk.Transactions;").replace("using System.Globalization;\n", "")
    elif language == "c":
        source = old.c_models(profile, messages, enums).split("typedef struct latent_profile_client latent_profile_client;", 1)[0]
        source = source.replace("LATENT_CLIENT_PROFILE_H", "LATENT_TRANSACTION_MODELS_H").replace('#include "types.h"', '#include "profile.h"')
        source = source.replace("latent_profile_", "latent_transaction_").replace("LATENT_PROFILE_", "LATENT_TRANSACTION_")
        source = source.replace("typedef struct latent_transaction_counter {\n    latent_string key;\n    uint64_t value;\n} latent_transaction_counter;\n", "")
        source += "#ifdef __cplusplus\n}\n#endif\n\n#endif\n"
    else:
        raise ValueError("unknown transaction client language")
    source = qualify_external(source, contract, language)
    values = [contract[key] for key in ("wireProfile", "hostAbiDigest", "preparationProfileDigest")]
    quoted = [json.dumps(value) for value in values]
    if language == "rust":
        source += ("/// Constructs a protocol descriptor; this value grants no authority.\n"
                   "#[must_use]\npub fn current_profile() -> TransactionProfile {\n    TransactionProfile {\n" +
                   "\n".join(f"        {name}: {value}.into()," for name, value in zip(
                       ("profile", "host_abi_digest", "preparation_profile_digest"), quoted, strict=True)) + "\n    }\n}\n")
    elif language == "go":
        source += ("// CurrentProfile describes the exact protocol; it grants no authority.\n"
                   "func CurrentProfile() TransactionProfile {\n\treturn TransactionProfile{\n" +
                   "\n".join(f"\t\t{name}: {value}," for name, value in zip(
                       ("Profile", "HostAbiDigest", "PreparationProfileDigest"), quoted, strict=True)) + "\n\t}\n}\n")
    elif language == "typescript":
        source += ("/** Constructs a protocol descriptor; this value grants no authority. */\n"
                   "export function currentProfile(): TransactionProfile {\n  return {\n" +
                   "\n".join(f"    {name}: {value}," for name, value in zip(
                       ("profile", "hostAbiDigest", "preparationProfileDigest"), quoted, strict=True)) + "\n  };\n}\n")
    elif language == "java":
        source = source.removesuffix("}\n") + ("    /** Constructs a protocol descriptor; this value grants no authority. */\n"
                   "    public static TransactionProfile currentProfile() {\n"
                   "        return new TransactionProfile(" + ", ".join(quoted) + ");\n    }\n}\n")
    elif language == "dotnet":
        source += ("/// <summary>Constructs a protocol descriptor; this value grants no authority.</summary>\n"
                   "public static class CurrentTransactionProfile\n{\n"
                   "    /// <summary>Returns the exact maintained wire and preparation profile.</summary>\n"
                   "    public static TransactionProfile Create() => new(" + ", ".join(quoted) + ");\n}\n")
    elif language == "c":
        helper = ("/* Protocol data only. This descriptor grants no authority. */\n"
                  "static inline latent_transaction_transaction_profile latent_transaction_current_profile(void) {\n"
                  "    latent_transaction_transaction_profile result = {\n" +
                  "\n".join(f"        {{{literal}, {len(value)}}}," for value, literal in zip(values, quoted, strict=True)) +
                  "\n    };\n    return result;\n}\n\n")
        source = source.replace("#ifdef __cplusplus\n}\n#endif", helper + "#ifdef __cplusplus\n}\n#endif")
    banner = "/* Generated from the authoritative transaction client descriptors. */\n" if language == "c" else "// Generated from the authoritative transaction client descriptors.\n"
    return banner + source.lstrip()


def generate(languages: list[str]) -> dict[str, str]:
    requirements = json.loads((ROOT / REQUIREMENTS).read_bytes())
    for service in requirements["externalClient"]["requiredServices"]:
        actual = "sha256:" + sha256((ROOT / service["source"]).read_bytes()).hexdigest()
        if actual != service["sourceSha256"]:
            raise ValueError("mandatory client profile is stale against its exact source")
    old = renderer()
    old_profile, old_messages, old_enums = old.read_contract()
    contract = derive(descriptor(), requirements, old_profile, old_messages, old_enums)
    outputs = {OUTPUTS["index"]: json.dumps(contract, indent=2) + "\n"}
    for language in languages:
        source = render(contract, language)
        formatter = ["rustfmt", "--edition", "2024"] if language == "rust" else ["gofmt"] if language == "go" else None
        if formatter:
            source = subprocess.run(formatter, input=source, text=True, capture_output=True, check=True, timeout=30).stdout
        outputs[OUTPUTS[language]] = source
    if "typescript" in languages:
        outputs["sdk/typescript-client/src/node/protocol/transaction-generated.ts"] = node_descriptor(requirements)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--language", action="append", choices=["rust", "c", "typescript", "go", "java", "dotnet"])
    args = parser.parse_args()
    languages = args.language or ["rust", "c", "typescript", "go", "java", "dotnet"]
    for name, expected in generate(languages).items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                raise ValueError("transaction client model differs from authoritative generation: " + name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="\n")
    print("Checked additive transaction client model definitions" if args.check else "Generated additive transaction client model definitions; execution remains unqualified")


if __name__ == "__main__":
    main()
