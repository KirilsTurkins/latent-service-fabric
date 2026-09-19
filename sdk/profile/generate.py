import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE = Path(__file__).with_name("client-profile.json")
SCALARS = {"string", "bytes", "bool", "uint32", "uint64", "int32"}


def snake(value):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def pascal(value):
    return "".join(part[:1].upper() + part[1:] for part in value.split("_"))


def camel(value):
    result = pascal(value)
    return result[:1].lower() + result[1:]


def blocks(text, keyword):
    for match in re.finditer(r"\b" + keyword + r"\s+(\w+)\s*\{", text):
        start = match.end()
        depth = 1
        position = start
        while depth and position < len(text):
            depth += (text[position] == "{") - (text[position] == "}")
            position += 1
        if depth:
            raise ValueError("unterminated protobuf block")
        yield match.group(1), text[start:position - 1]


def read_contract():
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    messages = {}
    enums = {}
    field_pattern = re.compile(
        r"\b(?:(optional|repeated)\s+)?(map\s*<\s*string\s*,\s*\w+\s*>|\w+)"
        r"\s+(\w+)\s*=\s*(\d+)\s*;"
    )
    source_texts = []
    for source, selected in profile["sources"].items():
        source_text = re.sub(r"//[^\n]*", "", (ROOT / source).read_text(encoding="utf-8"))
        source_texts.append(source_text)
        found = set()
        for name, body in blocks(source_text, "enum"):
            if name not in selected:
                continue
            prefix = snake(name).upper() + "_"
            enums[name] = {
                label.removeprefix(prefix): int(number)
                for label, number in re.findall(r"(\w+)\s*=\s*(-?\d+)\s*;", body)
            }
            found.add(name)
        for name, body in blocks(source_text, "message"):
            if name not in selected:
                continue
            groups = {}
            for group, group_body in blocks(body, "oneof"):
                for match in field_pattern.finditer(group_body):
                    groups[match.group(3)] = group
            fields = []
            for match in field_pattern.finditer(body):
                label, kind, field_name, number = match.groups()
                field = {"name": field_name, "type": kind, "number": int(number)}
                if kind.startswith("map"):
                    field["type"] = re.search(r",\s*(\w+)\s*>", kind).group(1)
                    field["map"] = True
                if label == "optional":
                    field["optional"] = True
                if label == "repeated":
                    field["repeated"] = True
                if field_name in groups:
                    field["optional"] = True
                    field["oneof"] = groups[field_name]
                fields.append(field)
            if not fields:
                raise ValueError("empty or unsupported message " + name)
            messages[name] = fields
            found.add(name)
        if found != set(selected):
            raise ValueError(f"missing selected definitions in {source}: {set(selected) - found}")
    for operation in profile["operations"]:
        service_name = operation["service"].rsplit(".", 1)[1]
        service_bodies = [
            body for source in source_texts for name, body in blocks(source, "service")
            if name == service_name
        ]
        signature = (r"rpc\s+" + operation["name"] + r"\s*\(\s*" + operation["request"]
                     + r"\s*\)\s*returns\s*\(\s*" + operation["response"] + r"\s*\)")
        if not any(re.search(signature, body) for body in service_bodies):
            raise ValueError("missing authoritative RPC " + operation["name"])
    messages.update(profile["local_messages"])
    enums.update(profile["local_enums"])
    for fields in messages.values():
        for field in fields:
            kind = field["type"]
            if kind not in SCALARS | messages.keys() | enums.keys():
                raise ValueError("unknown field type " + kind)
            if kind in messages and not field.get("required") and not field.get("repeated"):
                field["optional"] = True
    ordered = {}

    def visit(name):
        if name in ordered:
            return
        for field in messages[name]:
            if field["type"] in messages:
                visit(field["type"])
        ordered[name] = messages[name]

    for name in messages:
        visit(name)
    return profile, ordered, enums


def type_name(field, language, enums):
    kind = field["type"]
    primitives = {
        "rust": {"string": "String", "bytes": "Vec<u8>", "bool": "bool", "uint64": "u64", "uint32": "u32", "int32": "i32"},
        "go": {"string": "string", "bytes": "[]byte", "bool": "bool", "uint64": "uint64", "uint32": "uint32", "int32": "int32"},
        "ts": {"string": "string", "bytes": "Uint8Array", "bool": "boolean", "uint64": "bigint", "uint32": "number", "int32": "number"},
        "java": {"string": "String", "bytes": "ByteBuffer", "bool": "boolean", "uint64": "long", "uint32": "int", "int32": "int"},
        "dotnet": {"string": "string", "bytes": "ReadOnlyMemory<byte>", "bool": "bool", "uint64": "ulong", "uint32": "uint", "int32": "int"},
        "c": {"string": "latent_string", "bytes": "latent_bytes", "bool": "bool", "uint64": "uint64_t", "uint32": "uint32_t", "int32": "int32_t"},
    }
    result = primitives[language].get(kind, "latent_profile_" + snake(kind) if language == "c" else kind)
    boxed = {"long": "Long", "int": "Integer", "boolean": "Boolean"}
    if field.get("map"):
        result = {
            "rust": f"BTreeMap<String, {result}>",
            "go": "map[string]" + result,
            "ts": f"Readonly<Record<string, {result}>>",
            "java": f"Map<String, {boxed.get(result, result)}>",
            "dotnet": f"IReadOnlyDictionary<string, {result}>",
            "c": "const latent_key_value *" if kind == "string" else "const latent_profile_counter *",
        }[language]
    elif field.get("repeated"):
        result = {
            "rust": f"Vec<{result}>", "go": "[]" + result, "ts": f"readonly {result}[]",
            "java": f"List<{boxed.get(result, result)}>", "dotnet": f"IReadOnlyList<{result}>",
            "c": "const " + result + " *",
        }[language]
    elif field.get("optional"):
        result = {
            "rust": f"Option<{result}>", "go": "*" + result, "ts": result,
            "java": f"Optional<{boxed.get(result, result)}>", "dotnet": result + "?", "c": result,
        }[language]
    return result


def rust_models(profile, messages, enums):
    output = ["use std::collections::BTreeMap;", "use std::future::Future;", "use std::pin::Pin;", ""]
    for name, values in enums.items():
        output += ["#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]", f"pub struct {name}(pub i32);", "", f"impl {name} {{"]
        output += [f"    pub const {label}: Self = Self({number});" for label, number in values.items()]
        output += ["}", ""]
    for name, fields in messages.items():
        output += ["#[derive(Debug, Clone, Default, PartialEq, Eq)]", f"pub struct {name} {{"]
        output += [f"    pub {field['name'] if field['name'] != 'function' else 'function'}: {type_name(field, 'rust', enums)}," for field in fields]
        output += ["}", ""]
    output += [
        "#[derive(Debug, Clone, PartialEq, Eq)]", "pub struct ClientResponse<Response> {",
        "    pub value: Response,", "    pub metadata: ResponseMetadata,", "}", "",
        "pub type ClientFuture<'call, Response> =",
        "    Pin<Box<dyn Future<Output = Result<ClientResponse<Response>, ClientFailure>> + Send + 'call>>;", "",
        "pub trait ClientProfile: Send + Sync {",
    ]
    for operation in profile["operations"]:
        output += [f"    fn {snake(operation['name'])}(", "        &self,",
                   f"        request: {operation['request']},", "        options: CallOptions,",
                   f"    ) -> ClientFuture<'_, {operation['response']}>;", ""]
    output += ["}", "", "impl std::fmt::Display for ClientFailure {",
               "    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {",
               "        formatter.write_str(&self.message)", "    }", "}", "",
               "impl std::error::Error for ClientFailure {}", "",
               "pub fn parse_u64_decimal(value: &str) -> Option<u64> {",
               "    let parsed = value.parse::<u64>().ok()?;",
               "    (parsed.to_string() == value).then_some(parsed)", "}", ""]
    return "\n".join(output)


def go_models(profile, messages, enums):
    output = ["package profile", "", "import (", '\t"context"', '\t"strconv"', ")", ""]
    for name, values in enums.items():
        output += [f"type {name} int32", "", "const ("]
        output += [f"\t{name}{pascal(label.lower())} {name} = {number}" for label, number in values.items()]
        output += [")", ""]
    for name, fields in messages.items():
        output += [f"type {name} struct {{"]
        output += [f"\t{pascal(field['name'])} {type_name(field, 'go', enums)}" for field in fields]
        output += ["}", ""]
    output += ["type ClientResponse[Response any] struct {", "\tValue Response", "\tMetadata ResponseMetadata", "}", "", "type ClientProfile interface {"]
    for operation in profile["operations"]:
        output += [f"\t{operation['name']}(ctx context.Context, request {operation['request']}, options CallOptions) (ClientResponse[{operation['response']}], error)"]
    output += ["}", "", "func (failure *ClientFailure) Error() string { return failure.Message }", "",
               "func ParseU64Decimal(value string) (uint64, bool) {",
               "\tparsed, failure := strconv.ParseUint(value, 10, 64)",
               "\treturn parsed, failure == nil && strconv.FormatUint(parsed, 10) == value", "}", ""]
    return "\n".join(output)


def ts_models(profile, messages, enums):
    output = []
    for name, values in enums.items():
        output += [f"export type {name} = number;", f"export const {name} = {{"]
        output += [f"  {pascal(label.lower())}: {number}," for label, number in values.items()]
        output += ["} as const;", ""]
    for name, fields in messages.items():
        output += [f"export interface {name} {{"]
        output += [f"  readonly {camel(field['name'])}{'?' if field.get('optional') else ''}: {type_name(field, 'ts', enums)};" for field in fields]
        if name == "CallOptions":
            output += ["  readonly signal?: AbortSignal;"]
        output += ["}", ""]
    output += ["export interface ClientResponse<Response> {", "  readonly value: Response;", "  readonly metadata: ResponseMetadata;", "}", "", "export interface ClientProfile {"]
    for operation in profile["operations"]:
        output += [f"  {camel(snake(operation['name']))}(request: {operation['request']}, options?: CallOptions): Promise<ClientResponse<{operation['response']}>>;"]
    output += ["}", "", "export class ClientError extends Error {",
               "  constructor(readonly failure: ClientFailure) {", "    super(failure.message);", '    this.name = "ClientError";', "  }", "}", "",
               "export function parseU64Decimal(value: string): bigint {",
               '  if (typeof value !== "string" || !/^(0|[1-9][0-9]{0,19})$/.test(value)) {',
               '    throw new RangeError("invalid uint64 decimal");', "  }", "  const parsed = BigInt(value);",
               "  if (parsed > 18446744073709551615n) throw new RangeError(\"uint64 overflow\");",
               "  return parsed;", "}", "", "export function formatU64Decimal(value: bigint): string {",
               '  if (typeof value !== "bigint" || value < 0n || value > 18446744073709551615n) {',
               '    throw new RangeError("invalid uint64 bigint");', "  }", "  return value.toString(10);", "}", ""]
    return "\n".join(output)


def java_models(profile, messages, enums):
    output = ["package dev.latent.sdk;", "", "import java.nio.ByteBuffer;", "import java.util.List;", "import java.util.Map;", "import java.util.Optional;", "import java.util.concurrent.CompletableFuture;", "", "public final class Management {", "    private Management() { }", ""]
    for name, values in enums.items():
        output += [f"    public record {name}(int value) {{"]
        output += [f"        public static final {name} {label} = new {name}({number});" for label, number in values.items()]
        output += ["    }", ""]
    for name, fields in messages.items():
        output += [f"    public record {name}("]
        output += [f"            {type_name(field, 'java', enums)} {camel(field['name'])}{',' if position < len(fields) - 1 else ') { }'}" for position, field in enumerate(fields)]
        output += [""]
    output += ["    public record ClientResponse<Response>(Response value, ResponseMetadata metadata) { }", "", "    public interface ClientProfile {"]
    for operation in profile["operations"]:
        output += [f"        CompletableFuture<ClientResponse<{operation['response']}>> {camel(snake(operation['name']))}(", f"                {operation['request']} request, CallOptions options);", ""]
    output += ["    }", "", "    public static final class ClientException extends RuntimeException {",
               "        private static final long serialVersionUID = 1L;", "        private final ClientFailure failure;", "",
               "        public ClientException(ClientFailure failure) {", "            super(failure.message());", "            this.failure = failure;", "        }", "",
               "        public ClientFailure failure() { return failure; }", "    }", "",
               "    public static long parseU64Decimal(String value) {",
               '        if (!value.matches("0|[1-9][0-9]{0,19}")) throw new NumberFormatException("invalid uint64 decimal");',
               "        return Long.parseUnsignedLong(value);", "    }", "",
               "    public static String formatU64Decimal(long value) { return Long.toUnsignedString(value); }", "}", ""]
    return "\n".join(output)


def dotnet_models(profile, messages, enums):
    output = ["using System.Globalization;", "", "namespace Latent.Sdk.Profile;", ""]
    for name, values in enums.items():
        output += [f"/// <summary>Open numeric {name} value; unknown integers are retained.</summary>", '/// <param name="Value">The exact signed protobuf enum value.</param>', f"public readonly record struct {name}(int Value)", "{"]
        for label, number in values.items():
            output += [f"    /// <summary>The {label.lower().replace('_', ' ')} value.</summary>", f"    public static readonly {name} {pascal(label.lower())} = new({number});"]
        output += ["}", ""]
    for name, fields in messages.items():
        output += [f"/// <summary>Transport-neutral {name}; see the shared client profile for authority and lifetime rules.</summary>"]
        output += [f'/// <param name="{pascal(field["name"])}">The exact {field["name"]} value with preserved presence.</param>' for field in fields]
        output += [f"public sealed record {name}("]
        output += [f"    {type_name(field, 'dotnet', enums)} {pascal(field['name'])}{',' if position < len(fields) - 1 else ');'}" for position, field in enumerate(fields)]
        output += [""]
    output += ["/// <summary>A fully owned unary response and independent recovery metadata.</summary>",
               '/// <typeparam name="Response">The response model.</typeparam>',
               '/// <param name="Value">The decoded response.</param>', '/// <param name="Metadata">The independent outcome and audit observations.</param>',
               "public sealed record ClientResponse<Response>(Response Value, ResponseMetadata Metadata);", "",
               "/// <summary>The common eight-operation client profile; cancellation is local, not server cleanup.</summary>", "public interface IClientProfile", "{"]
    for operation in profile["operations"]:
        output += [f"    /// <summary>Calls {operation['name']} once within a bounded local deadline.</summary>",
                   f"    ValueTask<ClientResponse<{operation['response']}>> {operation['name']}Async(",
                   f"        {operation['request']} request,", "        CallOptions options,", "        CancellationToken cancellationToken = default);", ""]
    output += ["}", "", "/// <summary>A typed local or RPC failure, separate from an invocation outcome.</summary>",
               "public sealed class ClientException : Exception", "{", "    /// <summary>Retained, redacted failure and recovery facts.</summary>",
               "    public ClientFailure Failure { get; }", "", "    /// <summary>Retains failure facts without changing operation knowledge.</summary>",
               "    public ClientException(ClientFailure failure) : base(failure.Message) { Failure = failure; }", "}", "",
               "/// <summary>Lossless canonical unsigned decimal conversion for shared fixtures.</summary>", "public static class UnsignedDecimal", "{",
               "    /// <summary>Parses zero through UInt64.MaxValue without signs, whitespace or leading zeroes.</summary>",
               "    public static ulong Parse(string value)", "    {",
               "        if (value.Length == 0 || value.Length > 20 || (value.Length > 1 && value[0] == '0'))",
               '            throw new FormatException("invalid uint64 decimal");',
               "        return ulong.Parse(value, NumberStyles.None, CultureInfo.InvariantCulture);", "    }", "",
               "    /// <summary>Formats all unsigned bits as canonical decimal.</summary>",
               "    public static string Format(ulong value) => value.ToString(CultureInfo.InvariantCulture);", "}", ""]
    return "\n".join(output)


def c_models(profile, messages, enums):
    output = ["#ifndef LATENT_CLIENT_PROFILE_H", "#define LATENT_CLIENT_PROFILE_H", "", '#include "latent.h"', "", "#ifdef __cplusplus", 'extern "C" {', "#endif", "",
              "typedef struct latent_profile_counter {", "    latent_string key;", "    uint64_t value;", "} latent_profile_counter;", ""]
    for name, values in enums.items():
        prefix = "latent_profile_" + snake(name)
        output += [f"typedef int32_t {prefix};"]
        output += [f"#define {prefix.upper()}_{label} (({prefix}){number})" for label, number in values.items()]
        output += [""]
    for name, fields in messages.items():
        prefix = "latent_profile_" + snake(name)
        output += [f"typedef struct {prefix} {{"]
        for field in fields:
            if field.get("optional"):
                output += [f"    bool has_{field['name']};"]
            output += [f"    {type_name(field, 'c', enums)} {field['name']};"]
            if field.get("repeated") or field.get("map"):
                output += [f"    size_t {field['name']}_count;"]
        output += [f"}} {prefix};", ""]
    output += ["typedef struct latent_profile_client latent_profile_client;", "typedef struct latent_profile_call latent_profile_call;", ""]
    for operation in profile["operations"]:
        prefix = "latent_profile_" + snake(operation["name"])
        output += [f"typedef struct {prefix}_result {{", f"    latent_profile_{snake(operation['response'])} value;",
                   "    latent_profile_response_metadata metadata;", f"}} {prefix}_result;", "",
                   f"typedef void (*{prefix}_callback)(", f"    const {prefix}_result *response,",
                   "    const latent_profile_client_failure *failure,", "    void *user_data);", ""]
    output += ["typedef struct latent_profile_client_vtable {"]
    for operation in profile["operations"]:
        prefix = "latent_profile_" + snake(operation["name"])
        output += [f"    latent_profile_call *(*{snake(operation['name'])})(", "        latent_profile_client *client,",
                   f"        const latent_profile_{snake(operation['request'])} *request,", "        const latent_profile_call_options *options,",
                   f"        {prefix}_callback callback,", "        void *user_data);", ""]
    output += ["    void (*cancel_local)(latent_profile_call *call);", "    void (*release_call)(latent_profile_call *call);",
               "    void (*destroy)(latent_profile_client *client);", "} latent_profile_client_vtable;", "",
               "static inline bool latent_profile_parse_u64(latent_string value, uint64_t *output) {",
               "    uint64_t parsed = 0;",
               "    if (output == NULL || value.data == NULL || value.length == 0 || value.length > 20", "        || (value.length > 1 && value.data[0] == '0')) return false;",
               "    for (size_t position = 0; position < value.length; ++position) {",
               "        unsigned char digit = (unsigned char)value.data[position];",
               "        if (digit < '0' || digit > '9') return false;", "        uint64_t amount = (uint64_t)(digit - '0');",
               "        if (parsed > (UINT64_MAX - amount) / 10) return false;", "        parsed = parsed * 10 + amount;", "    }",
               "    *output = parsed;", "    return true;", "}", "", "#ifdef __cplusplus", "}", "#endif", "", "#endif", ""]
    return "\n".join(output)


def generated_files():
    profile, messages, enums = read_contract()
    return {
        "sdk/rust/src/management.rs": rust_models(profile, messages, enums),
        "sdk/go/profile/models.go": go_models(profile, messages, enums),
        "sdk/typescript-client/src/management.ts": ts_models(profile, messages, enums),
        "sdk/java-client/src/main/java/dev/latent/sdk/Management.java": java_models(profile, messages, enums),
        "sdk/dotnet/Latent.Sdk/Management.cs": dotnet_models(profile, messages, enums),
        "sdk/c/include/latent/profile.h": c_models(profile, messages, enums),
        "sdk/profile/contract.json": json.dumps({"profile": profile["profile"], "operations": profile["operations"], "messages": messages, "enums": enums}, indent=2) + "\n",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--patch", action="store_true")
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    if sum((arguments.check, arguments.patch, arguments.write)) != 1:
        parser.error("choose exactly one of --check, --patch, --write")
    changes = []
    for path, expected in generated_files().items():
        actual = (ROOT / path).read_text(encoding="utf-8") if (ROOT / path).exists() else None
        if actual == expected:
            continue
        changes.append(path)
        if arguments.write:
            (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / path).write_text(expected, encoding="utf-8", newline="\n")
        if arguments.patch:
            if actual is None:
                changes[-1] = f"*** Add File: {ROOT.as_posix()}/{path}\n" + "\n".join("+" + line for line in expected.splitlines())
            else:
                changes[-1] = (f"*** Update File: {ROOT.as_posix()}/{path}\n@@\n"
                               + "\n".join("-" + line for line in actual.splitlines()) + "\n"
                               + "\n".join("+" + line for line in expected.splitlines()))
    if arguments.patch:
        print("*** Begin Patch\n" + "\n".join(changes) + "\n*** End Patch")
    elif arguments.check and changes:
        print("stale generated files: " + ", ".join(changes), file=sys.stderr)
        return 1
    else:
        print(f"client profile: {len(generated_files())} generated files verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
