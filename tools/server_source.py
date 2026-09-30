"""Finite compiler declarations for listener-free server source; no authority.

The language compiler calls emit after inspecting the final component. Route
selection is a separate explicit operator input. Neither step runs application
initialization, publishes a route, or grants permission to create a listener.
"""
from __future__ import annotations

import re
import ipaddress
from pathlib import Path

from tools.dev_workflow.common import decode, digest, encode, integer, members, require, sha
from tools.rust_capsule_project import canonical, inventory, read_file, write_json

SCHEMA = "lsf.server.source.v1"
PROFILE = "lsf.server.source.profile.v1"
CONFIGURATION = "lsf.server.mounts.v1"
WEB = "latent:web/application@0.1.0"
METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
LANGUAGES = ("java", "rust", "c", "typescript", "go", "dotnet")
MAX_BYTES = 262144
MAX_ENDPOINTS = 16
MAX_CONTEXTS = 64
MAX_MOUNTS = 32
RECIPE = ("tools/server_source.py", "tools/java_guest/surface.py",
          "wit/platform/web/package.wit", "wit/platform/context/package.wit")


def token(value: str, maximum=128) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.$:/@+-]*", value)
            and len(value.encode()) <= maximum and ".." not in value and "://" not in value,
            "server-source-token")
    return value


def path(value: str) -> str:
    # This version deliberately narrows source matching to the host's canonical
    # path subset. No regex, percent decoding, Unicode alias, or query matching.
    require(isinstance(value, str) and 0 < len(value) <= 1024 and value.startswith("/")
            and re.fullmatch(r"/[A-Za-z0-9._~!$&'()*+,;=:@/-]*", value)
            and "//" not in value and all(part not in {".", ".."} for part in value.split("/"))
            and value != "/_lsf" and not value.startswith("/_lsf/"), "server-source-path")
    return value


def authority(value: str, scheme: str) -> str:
    require(isinstance(value, str) and 0 < len(value) <= 255 and value.isascii(), "server-source-mount-origin")
    host, separator, port = value.partition(":")
    require(host == host.lower() and not host.endswith(".") and host, "server-source-mount-origin")
    if separator:
        require(re.fullmatch(r"[1-9][0-9]{0,4}", port) and int(port) <= 65535
                and (scheme, port) not in {("http", "80"), ("https", "443")}, "server-source-mount-origin")
    if re.fullmatch(r"[0-9.]+", host):
        try:
            require(str(ipaddress.IPv4Address(host)) == host, "server-source-mount-origin")
        except ipaddress.AddressValueError:
            raise ValueError("server-source-mount-origin") from None
    else:
        require(all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in host.split(".")), "server-source-mount-origin")
    return value


def source_location(value: dict, files: dict[str, bytes] | None = None) -> None:
    members(value, {"path", "line", "column"})
    name = value["path"]
    require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_./-]{1,256}", name)
            and not name.startswith("/") and all(part not in {"", ".", ".."} for part in name.split("/")),
            "server-source-location")
    integer(value["line"], 1, 1048576)
    integer(value["column"], 1, 1048576)
    if files is not None:
        require(name in files, "server-source-location-not-captured")
        try:
            lines = files[name].decode("utf-8").splitlines()
        except UnicodeError:
            raise ValueError("server-source-location-encoding") from None
        require(value["line"] <= len(lines)
                and value["column"] <= len(lines[value["line"] - 1]) + 1, "server-source-location-range")


def profile(raw: bytes) -> dict:
    value = decode(raw, 65536)
    members(value, {"schemaVersion", "id", "language", "sourceApis", "compilerDigest", "adapter",
                    "runtimeDigest", "initialization", "target", "limits", "unsupported"})
    require(value["schemaVersion"] == PROFILE and value["language"] in LANGUAGES, "server-source-profile")
    token(value["id"])
    require(isinstance(value["sourceApis"], list) and 0 < len(value["sourceApis"]) <= 128
            and len(set(map(token, value["sourceApis"]))) == len(value["sourceApis"]), "server-source-apis")
    sha(value["compilerDigest"])
    sha(value["runtimeDigest"])
    members(value["adapter"], {"kind", "digest"})
    require(value["adapter"]["kind"] in {"automatic", "developer-extension"}, "server-source-adapter-kind")
    sha(value["adapter"]["digest"])
    require(value["initialization"] == "fresh-original-entrypoint"
            and value["target"] == {"contract": WEB, "function": "handle", "profile": "buffered-v1"}, "server-source-runtime-contract")
    limits = members(value["limits"], {"endpoints", "contexts", "requestBodyBytes", "responseBodyBytes", "headers", "headerBytes"})
    integer(limits["endpoints"], 1, MAX_ENDPOINTS)
    integer(limits["contexts"], 1, MAX_CONTEXTS)
    require({name: number for name, number in limits.items() if name not in {"endpoints", "contexts"}}
            == {"requestBodyBytes": 65536, "responseBodyBytes": 262144, "headers": 64, "headerBytes": 16384},
            "server-source-runtime-contract")
    require(isinstance(value["unsupported"], list) and len(value["unsupported"]) <= 256
            and len(set(map(token, value["unsupported"]))) == len(value["unsupported"]), "server-source-unsupported")
    return value


def endpoints(rows: list, files: dict[str, bytes] | None = None) -> None:
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_ENDPOINTS, "server-source-endpoint-limit")
    identifiers, count = set(), 0
    for row in rows:
        members(row, {"id", "bind", "contexts"})
        identity = token(row["id"], 64)
        require(identity not in identifiers, "server-source-duplicate-endpoint")
        identifiers.add(identity)
        members(row["bind"], {"address", "port", "backlog"})
        require(row["bind"]["address"] in {"wildcard", "loopback"}, "server-source-logical-address")
        integer(row["bind"]["port"], 1, 65535)
        integer(row["bind"]["backlog"], 0, 65535)
        contexts = row["contexts"]
        require(isinstance(contexts, list) and 0 < len(contexts) <= MAX_CONTEXTS, "server-source-context-limit")
        paths = set()
        for context in contexts:
            members(context, {"path", "match", "handler", "source"})
            selected = path(context["path"])
            require(selected not in paths, "server-source-conflicting-registration")
            paths.add(selected)
            require(context["match"] in {"exact", "segment-prefix", "literal-prefix"}, "server-source-matching")
            if context["match"] == "segment-prefix":
                require(selected == "/" or not selected.endswith("/"), "server-source-prefix-trailing-slash")
            token(context["handler"], 192)
            source_location(context["source"], files)
            count += 1
            require(count <= MAX_CONTEXTS, "server-source-context-limit")


def inspect(commands, wasm: Path, component: Path, reference: Path) -> dict:
    """Compare the actual linked signature with the staged authoritative WIT.

    reference is a compiler-owned staged copy of wit/platform/web plus its
    captured dependencies. The compiler already includes that tree in its
    recipe identity. This is component inspection, never Java initialization.
    """
    from tools.java_guest.surface import surface
    actual = surface(decode(commands.run("server-final-wit", wasm, "component", "wit", component, "--json"),
                            4 * 1024 * 1024))
    expected = surface(decode(commands.run("server-reference-wit", wasm, "component", "wit", reference, "--json"),
                              4 * 1024 * 1024), "application-service")
    require(WEB in actual["exports"] and actual["exports"][WEB] == expected["exports"][WEB],
            "server-source-final-web-signature")
    return actual["exports"][WEB]


def emit(files: dict[str, bytes], component: bytes, profile_raw: bytes, plan: dict,
         web_surface: dict, *, source_inputs: bytes | None = None) -> dict:
    selected = profile(profile_raw)
    members(plan, {"initializer", "extraction", "endpoints"})
    token(plan["initializer"], 192)
    require(plan["extraction"] in {"compiler-ast", "developer-extension"}, "server-source-extraction")
    require((plan["extraction"] == "compiler-ast") == (selected["adapter"]["kind"] == "automatic"),
            "server-source-extension-cannot-claim-automatic")
    endpoints(plan["endpoints"], files)
    require(len(plan["endpoints"]) <= selected["limits"]["endpoints"]
            and sum(len(endpoint["contexts"]) for endpoint in plan["endpoints"]) <= selected["limits"]["contexts"],
            "server-source-selected-profile-limit")
    require(isinstance(web_surface, dict) and set(web_surface) == {"types", "functions"}
            and set(web_surface["functions"]) == {"handle"}, "server-source-inspected-web-export-required")
    value = {"schemaVersion": SCHEMA, "authority": "none", "language": selected["language"],
        "profileId": selected["id"], "profileDigest": digest(profile_raw),
        "sourceDigest": digest(source_inputs if source_inputs is not None else inventory(files)),
        "componentDigest": digest(component), "compilerDigest": selected["compilerDigest"],
        "adapterDigest": selected["adapter"]["digest"], "runtimeDigest": selected["runtimeDigest"],
        "configurationDigest": digest(canonical(plan)),
        "export": {"contract": WEB, "function": "handle", "witSurfaceDigest": digest(canonical(web_surface))},
        "initializer": plan["initializer"], "extraction": plan["extraction"],
        "lifecycle": "fresh-activation", "endpoints": plan["endpoints"]}
    value["identity"] = digest(encode(value))
    validate(encode(value))
    return value


def validate(raw: bytes, *, component_digest: str | None = None, source_digest: str | None = None,
             profile_digest: str | None = None) -> dict:
    value = decode(raw, MAX_BYTES)
    members(value, {"schemaVersion", "authority", "language", "profileId", "profileDigest", "sourceDigest",
                    "componentDigest", "compilerDigest", "adapterDigest", "runtimeDigest", "configurationDigest", "export",
                    "initializer", "extraction", "lifecycle", "endpoints", "identity"})
    require(value["schemaVersion"] == SCHEMA and value["authority"] == "none"
            and value["language"] in LANGUAGES and value["lifecycle"] == "fresh-activation",
            "server-source-declaration")
    token(value["profileId"])
    token(value["initializer"], 192)
    require(value["extraction"] in {"compiler-ast", "developer-extension"}, "server-source-extraction")
    for key in ("profileDigest", "sourceDigest", "componentDigest", "compilerDigest", "adapterDigest", "runtimeDigest", "configurationDigest", "identity"):
        sha(value[key])
    members(value["export"], {"contract", "function", "witSurfaceDigest"})
    require(value["export"]["contract"] == WEB and value["export"]["function"] == "handle", "server-source-export")
    sha(value["export"]["witSurfaceDigest"])
    endpoints(value["endpoints"])
    require(value["identity"] == digest(encode({key: item for key, item in value.items() if key != "identity"})),
            "server-source-identity-mismatch")
    for field, expected in (("componentDigest", component_digest), ("sourceDigest", source_digest), ("profileDigest", profile_digest)):
        if expected is not None:
            require(value[field] == sha(expected), "server-source-stale-" + field)
    return value


def contains(mount: dict, context: dict) -> bool:
    route, source = mount["path"], context["path"]
    if mount["pathMatch"] == "exact":
        return context["match"] == "exact" and route == source
    if route == "/":
        return True
    if context["match"] == "literal-prefix":
        # Equality is insufficient: /hey also accepts /heyday in the JDK.
        return source.startswith(route + "/")
    return source == route or source.startswith(route + "/")


def mounts(raw: bytes, declaration: dict) -> list[dict]:
    value = decode(raw, 65536)
    members(value, {"schemaVersion", "profileDigest", "mounts"})
    require(value["schemaVersion"] == CONFIGURATION and value["profileDigest"] == declaration["profileDigest"],
            "server-source-mount-profile-mismatch")
    rows = value["mounts"]
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_MOUNTS, "server-source-mount-limit")
    names, routes, covered = set(), set(), set()
    by_id = {row["id"]: row for row in declaration["endpoints"]}
    for row in rows:
        members(row, {"endpoint", "name", "scheme", "host", "path", "pathMatch", "methods", "dispatch"})
        require(row["endpoint"] in by_id, "server-source-mount-endpoint")
        require(isinstance(row["name"], str) and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", row["name"])
                and row["name"] not in names, "server-source-mount-name")
        names.add(row["name"])
        require(row["scheme"] in {"http", "https"}, "server-source-mount-origin")
        authority(row["host"], row["scheme"])
        path(row["path"])
        require(row["pathMatch"] in {"exact", "prefix"} and (row["pathMatch"] != "prefix"
                or row["path"] == "/" or not row["path"].endswith("/")), "server-source-host-matching")
        require(isinstance(row["methods"], list) and 0 < len(row["methods"]) <= len(METHODS)
                and all(method in METHODS for method in row["methods"])
                and len(set(row["methods"])) == len(row["methods"]), "server-source-methods")
        require(row["dispatch"] in {"direct", "guest"}, "server-source-dispatch")
        contexts = by_id[row["endpoint"]]["contexts"]
        require(all(contains(row, context) for context in contexts), "server-source-non-equivalent-narrow-mount")
        if row["dispatch"] == "direct":
            require(len(contexts) == 1 and ((contexts[0]["match"] == "exact" and row["pathMatch"] == "exact")
                    or (contexts[0]["match"] == "segment-prefix" and row["pathMatch"] == "prefix")
                    or (contexts[0]["match"] == "literal-prefix" and row["path"] == "/"))
                    and contexts[0]["path"] == row["path"], "server-source-direct-route-not-equivalent")
        for method in row["methods"]:
            route = (row["scheme"], row["host"], row["path"], row["pathMatch"], method)
            require(route not in routes, "server-source-duplicate-mount")
            routes.add(route)
        covered.add(row["endpoint"])
    require(covered == set(by_id), "server-source-endpoint-without-authorized-mount")
    return rows


def package(output: Path, declaration: dict) -> tuple[str, str, str]:
    """Add the source declaration as a signed asset before package assembly."""
    raw = encode(declaration)
    validate(raw, component_digest=digest(read_file(output / "component.wasm", 64 * 1024 * 1024)))
    write_json(output / "server-source.json", declaration)
    return "server-source.json", "asset", "application/vnd.latent.server.source.v1+json"
