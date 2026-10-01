"""Finite captured C source/include recipes and target-checked Wasm archives."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from tools.application_dependencies import Closure
from tools.application_dependency_store import DependencyError, MAX_OBJECT, path_name, read_bytes
from tools.build_snapshot import digest


def unsigned(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 35, 7):
        if offset >= len(data):
            raise DependencyError("c-wasm-object-malformed")
        byte = data[offset]; offset += 1
        value |= (byte & 0x7f) << shift
        if not byte & 0x80:
            if value > 0xffffffff:
                raise DependencyError("c-wasm-object-malformed")
            return value, offset
    raise DependencyError("c-wasm-object-malformed")


def wasm_object(payload: bytes) -> dict:
    if not payload.startswith(b"\0asm\x01\0\0\0"):
        raise DependencyError("c-static-archive-host-native-member")
    offset, linking, features = 8, None, {}
    while offset < len(payload):
        section = payload[offset]; offset += 1
        size, offset = unsigned(payload, offset)
        end = offset + size
        if end > len(payload) or section > 12:
            raise DependencyError("c-wasm-object-malformed")
        if section == 0:
            length, content = unsigned(payload, offset)
            if length > 128 or content + length > end:
                raise DependencyError("c-wasm-object-malformed")
            try:
                name = payload[content:content + length].decode("utf-8")
            except UnicodeError:
                raise DependencyError("c-wasm-object-malformed") from None
            content += length
            if name == "linking":
                if linking is not None:
                    raise DependencyError("c-wasm-object-malformed")
                linking, _unused = unsigned(payload, content)
                if linking != 2:
                    raise DependencyError("c-wasm-linking-abi-unsupported")
            elif name == "target_features":
                count, content = unsigned(payload, content)
                if count > 64:
                    raise DependencyError("c-wasm-feature-limit")
                for _index in range(count):
                    if content >= end or payload[content] not in (ord("+"), ord("-")):
                        raise DependencyError("c-wasm-object-malformed")
                    sign = chr(payload[content]); content += 1
                    length, content = unsigned(payload, content)
                    if not 0 < length <= 64 or content + length > end:
                        raise DependencyError("c-wasm-object-malformed")
                    name = payload[content:content + length].decode("ascii", "strict"); content += length
                    if name in features:
                        raise DependencyError("c-wasm-object-malformed")
                    features[name] = sign
                if content != end:
                    raise DependencyError("c-wasm-object-malformed")
        offset = end
    if linking is None:
        raise DependencyError("c-wasm-static-member-is-not-relocatable-object")
    if any(features.get(name) == "+" for name in ("atomics", "memory64", "shared-mem")):
        raise DependencyError("c-wasm-object-requires-unqualified-runtime-profile")
    return {"digest": digest(payload), "size": len(payload), "linkingVersion": linking, "targetFeatures": features}


def archive_members(data: bytes) -> list[dict]:
    if not data.startswith(b"!<arch>\n"):
        raise DependencyError("c-static-archive-format-or-thin-archive-denied")
    offset, long_names, members, seen = 8, b"", [], set()
    while offset < len(data):
        if offset + 60 > len(data):
            raise DependencyError("c-static-archive-malformed")
        header = data[offset:offset + 60]; offset += 60
        try:
            name = header[:16].decode("ascii").strip()
            size_text = header[48:58].decode("ascii").strip()
        except UnicodeError:
            raise DependencyError("c-static-archive-malformed") from None
        if header[58:] != b"`\n" or not size_text.isdigit():
            raise DependencyError("c-static-archive-malformed")
        size = int(size_text)
        if size > MAX_OBJECT or offset + size > len(data):
            raise DependencyError("c-static-archive-member-limit")
        payload = data[offset:offset + size]; offset += size
        if size & 1:
            if data[offset:offset + 1] != b"\n":
                raise DependencyError("c-static-archive-malformed")
            offset += 1
        if name == "//":
            long_names = payload
            continue
        if name in {"/", "/SYM64/", "__.SYMDEF", "__.SYMDEF SORTED"}:
            continue
        if name.startswith("#1/"):
            if not name[3:].isdigit() or int(name[3:]) > len(payload):
                raise DependencyError("c-static-archive-malformed")
            length = int(name[3:]); name = payload[:length].decode("ascii", "strict").rstrip("\0")
            payload = payload[length:]
        elif name.startswith("/") and name[1:].isdigit():
            position = int(name[1:])
            if position >= len(long_names):
                raise DependencyError("c-static-archive-malformed")
            end = long_names.find(b"/\n", position)
            if end < 0:
                raise DependencyError("c-static-archive-malformed")
            name = long_names[position:end].decode("ascii", "strict")
        else:
            name = name.rstrip("/")
        path_name(name)
        if "/" in name or name.casefold() in seen or len(members) >= 1024:
            raise DependencyError("c-static-archive-member-collision-or-limit")
        seen.add(name.casefold())
        members.append({"name": name, **wasm_object(payload)})
    if not members:
        raise DependencyError("c-static-archive-empty")
    return members


@dataclass(frozen=True)
class Inputs:
    sources: tuple[Path, ...]
    includes: tuple[Path, ...]
    archives: tuple[Path, ...]
    defines: tuple[str, ...]
    receipt: dict


def selected(closure: Closure | None, *, compiler_digest: str, runtime_digest: str,
             compiler_distribution_digest: str | None = None) -> Inputs:
    sources, includes, archives, defines, receipts = [], [], [], [], []
    if closure is None:
        return Inputs((), (), (), (), {"formatVersion": 1, "artifacts": []})
    if closure.lock["selection"].get("target", "wasm32-wasi") != "wasm32-wasi":
        raise DependencyError("c-selected-target-not-maintained-profile")
    for item in closure.lock["artifacts"]:
        if item["role"] not in {"application", "resource"}:
            continue
        root = closure.work / item["mount"]
        options = item["metadata"]
        if set(options) & {"buildCommand", "configure", "compilerOptions", "generator", "plugins"}:
            raise DependencyError("c-executable-or-unobserved-build-options-denied")
        selected_sources = options.get("cSources", [])
        selected_includes = options.get("includeDirectories", [])
        selected_defines = options.get("defines", {})
        if item["role"] == "resource" and (selected_sources or selected_defines):
            raise DependencyError("c-resource-cannot-declare-executable-source")
        if (not isinstance(selected_sources, list) or len(selected_sources) > 64
                or not isinstance(selected_includes, list) or len(selected_includes) > 64
                or not isinstance(selected_defines, dict) or len(selected_defines) > 64):
            raise DependencyError("c-dependency-recipe-limit")
        if item["format"] == "file":
            if item["mount"].endswith((".h", ".inc")) and not selected_sources and selected_includes == ["."]:
                includes.append(root.parent)
                receipts.append({"id": item["id"], "header": item["files"][0], "role": item["role"]})
                continue
            if not item["mount"].endswith(".a") or item["role"] != "application":
                raise DependencyError("c-library-file-must-be-static-archive")
            members = archive_members(read_bytes(root))
            profile = options.get("archiveProfile")
            expected = {"formatVersion": 1, "target": "wasm32-wasi", "compilerDigest": compiler_digest,
                        "compilerDistributionDigest": compiler_distribution_digest,
                        "runtimeDigest": runtime_digest, "checkpointProfile": "closed-synchronous-v1", "members": members}
            if compiler_distribution_digest is None or profile != expected:
                raise DependencyError("c-static-archive-needs-current-observed-abi-profile-or-source-rebuild")
            archives.append(root)
            receipts.append({"id": item["id"], "archive": profile, "profileAuthority": "reviewed-source-build-policy"})
        else:
            observed = {row["path"] for row in item["files"]}
            for name in selected_sources:
                name = path_name(name)
                if not name.endswith(".c") or name not in observed:
                    raise DependencyError("c-source-not-in-captured-closure")
                sources.append(root / name)
            for name in selected_includes:
                if name != ".":
                    path_name(name)
                target = root if name == "." else root / name
                if not target.is_dir():
                    raise DependencyError("c-include-not-in-captured-closure")
                includes.append(target)
            receipts.append({"id": item["id"], "sources": selected_sources, "includes": selected_includes,
                             "compilerDigest": compiler_digest, "runtimeDigest": runtime_digest})
        for name, value in selected_defines.items():
            if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name) or not isinstance(value, str)
                    or not re.fullmatch(r"[A-Za-z0-9_+.-]{1,128}", value)):
                raise DependencyError("c-preprocessor-option-invalid")
            defines.append(name + "=" + value)
    if len(sources) > 64 or len(includes) > 64 or len(archives) > 32 or len(defines) > 64:
        raise DependencyError("c-dependency-recipe-limit")
    return Inputs(tuple(sources), tuple(includes), tuple(archives), tuple(defines), {
        "formatVersion": 1, "artifacts": receipts, "target": "wasm32-wasi", "networkResolution": False,
        "runtimeProfile": "closed-synchronous-v1", "generatedBuildExecution": "disabled"})
