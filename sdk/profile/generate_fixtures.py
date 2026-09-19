import base64
import json

from generate import ROOT, camel, pascal, snake, type_name


LANGUAGES = ("rust", "go", "ts", "java", "dotnet", "c")


def quoted(value, language):
    result = json.dumps(value, ensure_ascii=True)
    if language == "rust":
        result = result.replace("\\u0000", "\\u{0000}")
    if language in ("java", "c"):
        result = result.replace("\\u0000", "\\000")
    return result


def default_value(kind, messages, enums):
    if kind in messages:
        return {}
    if kind in enums or kind in ("uint32", "int32"):
        return 0
    if kind == "uint64":
        return "0"
    if kind == "bool":
        return False
    return ""


def qualified(kind, language):
    if language == "java":
        return "Management." + kind
    if language in ("ts", "dotnet"):
        return "Profile." + kind
    if language == "c":
        return "latent_profile_" + snake(kind)
    return kind


def field_name(name, language):
    if language in ("java", "ts"):
        return camel(name)
    if language in ("go", "dotnet"):
        return pascal(name)
    return name


def atomic(field):
    return {"type": field["type"]}


def render_value(field, value, language, messages, enums):
    kind = field["type"]
    if field.get("map"):
        pairs = [(quoted(key, language), render_value(atomic(field), item, language, messages, enums)) for key, item in value.items()]
        if language == "rust":
            return "BTreeMap::from([" + ", ".join(f"({key}.into(), {item})" for key, item in pairs) + "])"
        if language == "go":
            return type_name(field, language, enums) + "{" + ", ".join(f"{key}: {item}" for key, item in pairs) + "}"
        if language == "ts":
            return "{" + ", ".join(f"{key}: {item}" for key, item in pairs) + "}"
        if language == "java":
            return "Map.ofEntries(" + ", ".join(f"Map.entry({key}, {item})" for key, item in pairs) + ")"
        if language == "dotnet":
            native = type_name(atomic(field), language, enums)
            return f"new Dictionary<string, {native}> {{" + ", ".join(f"{{{key}, {item}}}" for key, item in pairs) + "}"
        if not pairs:
            return "NULL"
        native = "latent_key_value" if kind == "string" else "latent_profile_counter"
        return f"(const {native}[]){{" + ", ".join(f"{{.key = PROFILE_TEXT({key}), .value = {item}}}" for key, item in pairs) + "}"
    if field.get("repeated"):
        entries = [render_value(atomic(field), item, language, messages, enums) for item in value]
        content = ", ".join(entries)
        if language == "rust":
            return "vec![" + content + "]"
        if language == "go":
            return type_name(field, language, enums) + "{" + content + "}"
        if language == "ts":
            return "[" + content + "]"
        if language == "java":
            return "List.of(" + content + ")"
        if language == "dotnet":
            native = qualified(kind, language) if kind in messages or kind in enums else type_name(atomic(field), language, enums)
            return f"new {native}[] {{" + content + "}"
        if not entries:
            return "NULL"
        native = type_name(atomic(field), language, enums)
        return f"(const {native}[]){{" + content + "}"
    if field.get("optional"):
        if value is None:
            return {"rust": "None", "go": "nil", "ts": "undefined", "java": "Optional.empty()", "dotnet": "null", "c": "0"}[language]
        inner = render_value(atomic(field), value, language, messages, enums)
        if language == "rust":
            return "Some(" + inner + ")"
        if language == "go":
            return "fixturePointer(" + inner + ")"
        if language == "java":
            return "Optional.of(" + inner + ")"
        return inner
    if kind in messages:
        entries = []
        for member in messages[kind]:
            name = member["name"]
            native = field_name(name, language)
            if member.get("optional") and name not in value:
                if language in ("rust", "go", "ts", "c"):
                    continue
                content = render_value(member, None, language, messages, enums)
            else:
                default = {} if member.get("map") else [] if member.get("repeated") else default_value(member["type"], messages, enums)
                content = render_value(member, value.get(name, default), language, messages, enums)
            if language in ("java", "dotnet"):
                entries.append(content)
            elif language == "c":
                if member.get("optional"):
                    entries.append(f".has_{name} = true")
                entries.append(f".{name} = {content}")
                if member.get("repeated") or member.get("map"):
                    entries.append(f".{name}_count = {len(value.get(name, {}))}")
            else:
                entries.append(native + ": " + content)
        if language == "rust" and any(member.get("optional") and member["name"] not in value for member in messages[kind]):
            entries.append("..Default::default()")
        content = ", ".join(entries)
        native = qualified(kind, language)
        if language in ("java", "dotnet"):
            return f"new {native}({content})"
        if language == "ts":
            return "{" + content + "}"
        if language == "c":
            return f"({native}){{" + (content or "0") + "}"
        return native + "{" + content + "}"
    if kind in enums:
        native = qualified(kind, language)
        if language in ("java", "dotnet"):
            return f"new {native}({value})"
        if language == "rust":
            return f"{native}({value:_})"
        if language == "go":
            return f"{native}({value})"
        if language == "c":
            return f"(({native})({value}))"
        return str(value)
    if kind == "string":
        literal = quoted(value, language)
        if language == "rust":
            return literal + ".into()" if value else "String::new()"
        if language == "c":
            return "PROFILE_TEXT(" + literal + ")"
        return literal
    if kind == "bool":
        return "true" if value else "false"
    if kind == "uint64":
        return {
            "rust": f"{int(value):_}_u64", "go": f"uint64({value})", "ts": value + "n",
            "java": f'Long.parseUnsignedLong("{value}")', "dotnet": value + "UL", "c": f"UINT64_C({value})",
        }[language]
    if kind in ("uint32", "int32"):
        if language == "java" and kind == "uint32":
            return f'Integer.parseUnsignedInt("{value}")'
        if language == "rust":
            return f"{value:_}" + ("_u32" if kind == "uint32" else "_i32")
        if language == "go":
            return f"{kind}({value})"
        if language in ("c", "dotnet") and kind == "uint32":
            return str(value) + "U"
        return str(value)
    if kind == "bytes":
        entries = list(base64.b64decode(value, validate=True))
        content = ", ".join(str(item) for item in entries)
        if language == "rust":
            return "vec![" + content + "]"
        if language == "go":
            return "[]byte{" + content + "}"
        if language == "ts":
            return "new Uint8Array([" + content + "])"
        if language == "java":
            return "ByteBuffer.wrap(new byte[]{" + ", ".join("(byte)" + str(item) for item in entries) + "})"
        if language == "dotnet":
            return "new byte[]{" + content + "}"
        data = "(const uint8_t[]){" + content + "}" if entries else "NULL"
        return f"(latent_bytes){{.data = {data}, .length = {len(entries)}}}"
    raise ValueError("unsupported fixture kind " + kind)


def check(condition, label, language):
    message = quoted(label, language)
    if language == "rust":
        if " == " in condition:
            left, right = condition.split(" == ", 1)
            if right in ("true", "false"):
                return f"assert!({left if right == 'true' else '!' + left}, {message});"
            return f"assert_eq!({left}, {right}, {message});"
        return f"assert!({condition}, {message});"
    if language == "go":
        return f"if !({condition}) {{ tester.Fatal({message}) }}"
    if language in ("java", "ts"):
        return f"check({condition}, {message});"
    if language == "dotnet":
        return f"Check({condition}, {message});"
    return f"assert(({condition}) && {message});"


def assertions(field, value, path, language, messages, enums, label):
    result = []
    kind = field["type"]
    if field.get("optional"):
        if language == "rust":
            condition = f"{path}.is_some()"
            inner = f"{path}.as_ref().unwrap()" if kind in messages else f"{path}.as_deref().unwrap()" if kind == "string" else f"{path}.unwrap()"
        elif language == "go":
            condition, inner = f"{path} != nil", f"(*{path})"
        elif language == "java":
            condition, inner = f"{path}.isPresent()", f"{path}.get()"
        elif language == "ts":
            condition, inner = f"{path} !== undefined", f"{path}!"
        elif language == "dotnet":
            condition = f"{path} is not null"
            inner = f"{path}!.Value" if kind in enums or kind in ("uint64", "uint32", "int32", "bool") else path + "!"
        else:
            owner, member = path.rsplit(".", 1)
            condition, inner = f"{owner}.has_{member}", path
        absent = f"{path}.is_none()" if language == "rust" else f"!({condition})"
        result.append(check(condition if value is not None else absent, label + ".presence", language))
        if value is not None:
            result += assertions(atomic(field), value, inner, language, messages, enums, label)
        return result
    if field.get("map") or field.get("repeated"):
        collection = field.get("map")
        count = len(value)
        length = {"rust": f"{path}.len()", "go": f"len({path})", "ts": f"Object.keys({path}).length" if collection else f"{path}.length", "java": f"{path}.size()", "dotnet": f"{path}.Count", "c": path + "_count"}[language]
        result.append(check(f"{length} == {count}", label + ".count", language))
        for position, item in enumerate(value.items() if collection else value):
            if collection:
                key, member = item
                quoted_key = quoted(key, language)
                if language == "rust":
                    inner = f"{path}[{quoted_key}]"
                elif language == "java":
                    inner = f"{path}.get({quoted_key})"
                elif language == "c":
                    result += assertions({"type": "string"}, key, f"{path}[{position}].key", language, messages, enums, label + ".key")
                    inner = f"{path}[{position}].value"
                else:
                    inner = f"{path}[{quoted_key}]" + ("!" if language == "ts" else "")
            else:
                member = item
                inner = f"{path}.get({position})" if language == "java" else f"{path}[{position}]" + ("!" if language == "ts" else "")
            result += assertions(atomic(field), member, inner, language, messages, enums, label + f".{position}")
        return result
    if kind in messages:
        for member in messages[kind]:
            name = member["name"]
            default = None if member.get("optional") else {} if member.get("map") else [] if member.get("repeated") else default_value(member["type"], messages, enums)
            inner = path + "." + field_name(name, language) + ("()" if language == "java" else "")
            result += assertions(member, value.get(name, default), inner, language, messages, enums, label + "." + name)
        return result
    if kind in enums:
        raw = {"rust": path + ".0", "go": f"int32({path})", "ts": path, "java": path + ".value()", "dotnet": path + ".Value", "c": path}[language]
        expected = f"{value:_}" if language == "rust" else str(value)
        result.append(check(f"{raw} == {expected}", label, language))
    elif kind == "string":
        literal = quoted(value, language)
        if language == "java":
            condition = f"{path}.equals({literal})"
        elif language == "c":
            result.append(check(f"{path}.length == {len(value.encode('utf-8'))}", label + ".length", language))
            if value:
                result.append(check(f"memcmp({path}.data, {literal}, {len(value.encode('utf-8'))}) == 0", label, language))
            return result
        else:
            condition = f"{path} == {literal}"
        result.append(check(condition, label, language))
    elif kind == "bytes":
        expected = list(base64.b64decode(value, validate=True))
        length = {"rust": path + ".len()", "go": f"len({path})", "ts": path + ".length", "java": path + ".remaining()", "dotnet": path + ".Length", "c": path + ".length"}[language]
        result.append(check(f"{length} == {len(expected)}", label + ".length", language))
        for position, member in enumerate(expected):
            inner = f"({path}.get({position}) & 255)" if language == "java" else f"{path}.Span[{position}]" if language == "dotnet" else f"{path}.data[{position}]" if language == "c" else f"{path}[{position}]"
            result.append(check(f"{inner} == {member}", label + f".{position}", language))
    else:
        expected = render_value(field, value, language, messages, enums)
        result.append(check(f"{path} == {expected}", label, language))
    return result


def unsigned_checks(cases, language):
    output = []
    for case in cases:
        value = quoted(case["decimal"], language)
        valid = case["valid"]
        if language == "rust":
            predicate = "is_some" if valid else "is_none"
            output.append(check(f"parse_u64_decimal({value}).{predicate}()", "uint64 decimal", language))
            if valid:
                output.append(check(f"parse_u64_decimal({value}).unwrap().to_string() == {value}", "uint64 roundtrip", language))
        elif language == "go":
            output += ["{", f"    parsed, valid := ParseU64Decimal({value})", "    _ = parsed",
                       "    " + check(f"valid == {str(valid).lower()}", "uint64 decimal", language)]
            if valid:
                output += ["    " + check(f"strconv.FormatUint(parsed, 10) == {value}", "uint64 roundtrip", language)]
            output += ["}"]
        elif language == "ts":
            if valid:
                output.append(check(f"Profile.formatU64Decimal(Profile.parseU64Decimal({value})) == {value}", "uint64 roundtrip", language))
            else:
                output += [f"rejects(() => Profile.parseU64Decimal({value}));"]
        elif language == "java":
            if valid:
                output.append(check(f"Management.formatU64Decimal(Management.parseU64Decimal({value})).equals({value})", "uint64 roundtrip", language))
            else:
                output += [f"try {{ Management.parseU64Decimal({value}); throw new AssertionError(\"uint64 rejected\"); }} catch (NumberFormatException expected) {{ }}"]
        elif language == "dotnet":
            if valid:
                output.append(check(f"Profile.UnsignedDecimal.Format(Profile.UnsignedDecimal.Parse({value})) == {value}", "uint64 roundtrip", language))
            else:
                output += [f"Rejects(() => Profile.UnsignedDecimal.Parse({value}));"]
        else:
            output += ["{", "    uint64_t parsed = UINT64_C(42);", f"    bool valid = latent_profile_parse_u64(PROFILE_TEXT({value}), &parsed);",
                       "    " + check(f"valid == {str(valid).lower()}", "uint64 decimal", language),
                       "    " + check(f"parsed == UINT64_C({case['decimal'] if valid else '42'})", "uint64 parsed or unchanged", language), "}"]
    return output


def generate(profile, messages, enums):
    fixtures = json.loads((ROOT / "sdk/profile/fixtures.json").read_text(encoding="utf-8"))
    outputs = {}
    for language in LANGUAGES:
        body = []
        for case in fixtures["cases"]:
            field = {"type": case["type"]}
            literal = render_value(field, case["value"], language, messages, enums)
            native = qualified(case["type"], language)
            declaration = {
                "rust": f"let value = {literal};", "go": f"value := {literal}",
                "ts": f"const value: {native} = {literal};", "java": f"{native} value = {literal};",
                "dotnet": f"var value = {literal};", "c": f"{native} value = {literal};",
            }[language]
            body += ["{", "    " + declaration]
            body += ["    " + line for line in assertions(field, case["value"], "value", language, messages, enums, case["name"])]
            body += ["}"]
        body += unsigned_checks(fixtures["unsigned"], language)
        count = len(fixtures["cases"])
        if language == "rust":
            header = ["#![allow(clippy::too_many_lines)]", "", "use latent_sdk::management::*;", "use std::collections::BTreeMap;", "", "#[test]", "fn shared_profile_vectors() {"]
            footer = ["}", ""]
            path = "sdk/rust/tests/client_profile_vectors.rs"
        elif language == "go":
            header = ["package profile", "", "import (", '\t"strconv"', '\t"testing"', ")", "", "func fixturePointer[Value any](value Value) *Value { return &value }", "", "func TestSharedProfileVectors(tester *testing.T) {"]
            footer = ["}", ""]
            path = "sdk/go/profile/vectors_test.go"
        elif language == "ts":
            header = ['import { profile as Profile } from "../src/index.js";', "", "function check(value: boolean, message: string): asserts value {", "  if (!value) throw new Error(message);", "}", "", "function rejects(action: () => unknown): void {", "  try { action(); } catch (failure) {", "    if (failure instanceof RangeError) return;", "    throw failure;", "  }", '  throw new Error("unsigned input must be rejected");', "}", ""]
            footer = ['rejects(() => Profile.formatU64Decimal(9007199254740992 as unknown as bigint));', 'rejects(() => Profile.parseU64Decimal(1 as unknown as string));', 'rejects(() => Profile.formatU64Decimal(-1n));', 'rejects(() => Profile.formatU64Decimal(18446744073709551616n));', f'console.log("shared profile vectors: {count}");', ""]
            path = "sdk/typescript-client/tests/profile-vectors.ts"
        elif language == "java":
            header = ["package dev.latent.sdk;", "", "import java.nio.ByteBuffer;", "import java.util.List;", "import java.util.Map;", "import java.util.Optional;", "", "final class ProfileVectors {", "    private ProfileVectors() { }", "    private static void check(boolean value, String message) {", "        if (!value) throw new AssertionError(message);", "    }", "    static void run() {"]
            footer = [f'        System.out.println("shared profile vectors: {count}");', "    }", "}", ""]
            path = "sdk/java-client/src/test/java/dev/latent/sdk/ProfileVectors.java"
        elif language == "dotnet":
            header = ["using Profile = Latent.Sdk.Profile;", "", "namespace Latent.Sdk.SemanticTests;", "", "internal static class ProfileVectors", "{", "    private static void Check(bool value, string message)", "    {", "        if (!value) throw new InvalidOperationException(message);", "    }", "", "    private static void Rejects(Action action)", "    {", "        try { action(); }", "        catch (FormatException) { return; }", "        catch (OverflowException) { return; }", '        throw new InvalidOperationException("uint64 input must be rejected");', "    }", "", "    internal static void Run()", "    {"]
            footer = [f'        Console.WriteLine("shared profile vectors: {count}");', "    }", "}", ""]
            path = "sdk/dotnet/Latent.Sdk.SemanticTests/ProfileVectors.cs"
        else:
            header = ['#include "latent/profile.h"', "#include <assert.h>", "#include <string.h>", "", '#define PROFILE_TEXT(value) ((latent_string){(value), sizeof(value) - 1u})', "", "static void profile_vectors(void) {"]
            footer = ["}", "", "#undef PROFILE_TEXT", ""]
            path = "sdk/c/tests/profile_vectors.h"
        indentation = "        " if language in ("java", "dotnet") else "" if language == "ts" else "    "
        outputs[path] = "\n".join(header + [indentation + line for line in body] + footer)
    return outputs
