"""Inspect emitted imports and bind conservative observations to package bytes."""
from __future__ import annotations

from pathlib import Path

from tools import guest_compatibility as compatibility
from tools.dev_workflow.common import decode, encode, digest, require
from tools.rust_capsule_project import ROOT, inventory, read_file, read_json, write_json

RECIPE = ("tools/guest_compatibility.py", "tools/guest_compatibility_build.py",
          "tools/dev_workflow/common.py", "wit/host-abi-phase3-v4.json")


def _structural_type_checker(indexed):
    """Prove finite value-only types; opaque resources never become providers."""
    primitives = frozenset("bool u8 s8 u16 s16 u32 s32 u64 s64 f32 f64 char string".split())
    remaining, active, memo = [32768], set(), {}

    def value(item, depth=0):
        remaining[0] -= 1
        require(remaining[0] >= 0 and depth <= 32, "compatibility-structural-type-work-bound")
        if item is None:
            return True, 0
        if isinstance(item, str):
            return item in primitives, 0
        require(type(item) is int and item not in active, "compatibility-structural-type-cycle-or-index")
        definition = indexed("types", item)
        if item in memo:
            safe, height = memo[item]
            require(depth + height <= 32, "compatibility-structural-type-depth")
            return safe, height
        require(isinstance(definition, dict) and "kind" in definition, "compatibility-structural-type-definition")
        kind = definition["kind"]
        # Resource, own/borrow, future/stream and unknown forms stay callable
        # unknown imports. The authoritative runtime rejects them separately.
        if not isinstance(kind, dict) or len(kind) != 1:
            return False, 0
        form, body = next(iter(kind.items()))
        children = []
        if form in {"type", "list", "option"}:
            require(body is not None, "compatibility-structural-type-child")
            children = [body]
        elif form in {"record", "variant"}:
            key = "fields" if form == "record" else "cases"
            require(isinstance(body, dict) and set(body) == {key} and isinstance(body[key], list)
                and len(body[key]) <= 4096, "compatibility-structural-type-members")
            for member in body[key]:
                require(isinstance(member, dict) and set(member) == {"name", "type"}
                    and isinstance(member["name"], str) and (form == "variant" or member["type"] is not None),
                    "compatibility-structural-type-member")
                children.append(member["type"])
        elif form == "tuple":
            require(isinstance(body, dict) and set(body) == {"types"} and isinstance(body["types"], list)
                and len(body["types"]) <= 4096 and all(child is not None for child in body["types"]),
                "compatibility-structural-type-tuple")
            children = body["types"]
        elif form == "result":
            require(isinstance(body, dict) and set(body) == {"ok", "err"}, "compatibility-structural-type-result")
            children = list(body.values())
        elif form in {"enum", "flags"}:
            key = "cases" if form == "enum" else "flags"
            require(isinstance(body, dict) and set(body) == {key} and isinstance(body[key], list)
                and len(body[key]) <= 4096 and all(isinstance(member, dict) and set(member) == {"name"}
                    and isinstance(member["name"], str) for member in body[key]), "compatibility-structural-type-tags")
            remaining[0] -= len(body[key])
            require(remaining[0] >= 0, "compatibility-structural-type-work-bound")
        else:
            return False, 0
        active.add(item)
        checked = [value(child, depth + 1) for child in children]
        active.remove(item)
        safe, height = all(child[0] for child in checked), 1 + max((child[1] for child in checked), default=0)
        require(depth + height <= 32, "compatibility-structural-type-depth")
        memo[item] = safe, height
        return safe, height

    return value


def interface_names(graph: dict, world: str | None = None, *, host_interfaces=()) -> dict:
    """Read bounded wasm-tools JSON; do not match import names in source text."""
    require(isinstance(graph, dict) and set(graph) == {"worlds", "interfaces", "types", "packages"}, "compatibility-wit-graph")
    require(all(isinstance(graph[name], list) for name in graph), "compatibility-wit-tables")
    require(len(graph["worlds"]) <= 128 and len(graph["interfaces"]) <= 128
            and len(graph["types"]) <= 4096 and len(graph["packages"]) <= 128, "compatibility-wit-table-limit")

    def indexed(name, index):
        require(type(index) is int and 0 <= index < len(graph[name]), "compatibility-wit-index")
        return graph[name][index]

    def identity(item):
        package = indexed("packages", item["package"])
        base, _, version = package["name"].partition("@")
        return compatibility.token(base + "/" + item["name"] + ("@" + version if version else ""))

    worlds = [item for item in graph["worlds"] if world is None or world in (item["name"], identity(item))]
    require(len(worlds) == 1, "compatibility-selected-world")
    check_type = _structural_type_checker(indexed)
    result = {"typeImports": []}
    for direction in ("imports", "exports"):
        items = worlds[0][direction]
        require(isinstance(items, dict) and len(items) <= 128, "compatibility-wit-item-limit")
        result[direction] = []
        for item in items.values():
            require(isinstance(item, dict) and set(item) == {"interface"}, "compatibility-unqualified-world-item")
            interface = indexed("interfaces", item["interface"]["id"])
            name = identity(interface)
            target = direction
            if direction == "imports" and name not in host_interfaces and interface.get("functions") == {}:
                types = interface.get("types")
                require(isinstance(types, dict) and len(types) <= 4096, "compatibility-structural-interface-types")
                if all(check_type(index)[0] for index in types.values()):
                    target = "typeImports"
            require(name not in result[direction] and (direction != "imports" or name not in result["typeImports"]),
                    "compatibility-wit-duplicate-interface")
            result[target].append(name)
        require(len(set(result[direction])) == len(result[direction]), "compatibility-wit-duplicate-interface")
        result[direction].sort()
    result["typeImports"].sort()
    return result


def inspect(commands, wasm: Path, output: Path, declared: dict) -> dict:
    raw = commands.run("compatibility-final-wit", wasm, "component", "wit", output / "component.wasm", "--json")
    host = read_json(ROOT / "wit/host-abi-phase3-v4.json")
    names = interface_names(decode(raw, 4 * 1024 * 1024), host_interfaces={row["interface"] for row in host["interfaces"]})
    findings = compatibility.import_findings(names["imports"], list(declared["imports"]), host)
    expected_exports = list(declared["exports"])
    if set(names["exports"]) != set(expected_exports):
        findings.append(compatibility.finding("surface-mismatch", "link", "final-component"))
    result = {"componentDigest": digest(read_file(output / "component.wasm", 64 * 1024 * 1024)),
              "hostAbiDigest": digest(encode(host)), "imports": names["imports"],
              "typeImports": names["typeImports"], "findings": findings}
    write_json(output / "compatibility-inspection.json", result)
    if any(item["classification"] in compatibility.BLOCKERS for item in findings):
        raise ValueError("final-component-compatibility-failed; inspect compatibility-inspection.json")
    return result


def package_report(output: Path, files: dict[str, bytes], component: bytes) -> None:
    lock = decode(files["sdk-lock.json"], 8 * 1024 * 1024)
    language = lock.get("language", "rust" if "Cargo.toml" in files else None)
    host = read_json(ROOT / "wit/host-abi-phase3-v4.json")
    inspection_path = output / "compatibility-inspection.json"
    if inspection_path.exists():
        inspection = read_json(inspection_path)
        require(inspection["componentDigest"] == digest(component)
                and inspection["hostAbiDigest"] == digest(encode(host)), "compatibility-stale-inspection")
        findings = inspection["findings"]
    else:
        findings = [compatibility.finding("unresolved-behavior", "link", "not-evaluated")]
    # Reachability, initialization, runtime dispatch and retirement cannot be
    # certified by a final import table or a compiler's successful exit status.
    findings = [*findings, compatibility.finding("unresolved-behavior", "initialization", "not-evaluated"),
                compatibility.finding("lifecycle-unproven", "retirement", "not-evaluated", owner_issue=736)]
    inputs = [{"kind": "sdk", "digest": digest(encode(lock))},
              {"kind": "runtime", "digest": digest(encode(host)), "profile": host["id"]}]
    source_path = output / "source-inputs.json"
    source = read_file(source_path) if source_path.exists() else inventory(files)
    value = compatibility.report(language, digest(source), digest(component), host["id"], inputs, findings)
    write_json(output / "compatibility-report.json", value)


def failure_report(output: Path, language: str, stage: str) -> None:
    """Retain safe known observations when captured inputs exist; never guess errors."""
    try:
        _failure_report(output, language, stage)
    except Exception:
        # Reporting runs while the compiler exception is already propagating.
        # A stale/unreadable report input must never replace that original error.
        try:
            write_json(output / "compatibility-report-failed.json", {
                "schemaVersion": "lsf.guest.compatibility.failure.v1", "status": "unavailable",
                "authority": "none", "reason": "report-input-unavailable-or-stale"})
        except Exception:
            pass  # The caller retains its existing bounded build-failure path.


def _failure_report(output: Path, language: str, stage: str) -> None:
    source_path = output / "source-inputs.json"
    if not source_path.exists():
        return  # Source identity is unavailable; do not fabricate a snapshot.
    host = read_json(ROOT / "wit/host-abi-phase3-v4.json")
    phase = "link" if stage in {"component", "contracts", "compatibility", "package"} else "compile"
    findings = [compatibility.finding("unresolved-behavior", phase, "not-evaluated")]
    inspection_path = output / "compatibility-inspection.json"
    component_path = output / "component.wasm"
    component = read_file(component_path, 64 * 1024 * 1024) if component_path.exists() else None
    if inspection_path.exists():
        inspection = read_json(inspection_path)
        require(component is not None and inspection["componentDigest"] == digest(component), "compatibility-stale-inspection")
        findings = [*inspection["findings"], *findings]
    value = compatibility.report(language, digest(read_file(source_path)),
        digest(component) if component is not None else None, host["id"], [], findings)
    write_json(output / "compatibility-report.json", value)
