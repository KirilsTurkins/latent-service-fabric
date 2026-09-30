"""Inspect emitted imports and bind conservative observations to package bytes."""
from __future__ import annotations

from pathlib import Path

from tools import guest_compatibility as compatibility
from tools.dev_workflow.common import decode, encode, digest, require
from tools.rust_capsule_project import ROOT, inventory, read_file, read_json, write_json

RECIPE = ("tools/guest_compatibility.py", "tools/guest_compatibility_build.py",
          "tools/dev_workflow/common.py", "wit/host-abi-phase3-v4.json")


def interface_names(graph: dict, world: str | None = None) -> dict:
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
    result = {}
    for direction in ("imports", "exports"):
        items = worlds[0][direction]
        require(isinstance(items, dict) and len(items) <= 128, "compatibility-wit-item-limit")
        result[direction] = []
        for item in items.values():
            require(isinstance(item, dict) and set(item) == {"interface"}, "compatibility-unqualified-world-item")
            result[direction].append(identity(indexed("interfaces", item["interface"]["id"])))
        require(len(set(result[direction])) == len(result[direction]), "compatibility-wit-duplicate-interface")
        result[direction].sort()
    return result


def inspect(commands, wasm: Path, output: Path, declared: dict) -> dict:
    raw = commands.run("compatibility-final-wit", wasm, "component", "wit", output / "component.wasm", "--json")
    names = interface_names(decode(raw, 4 * 1024 * 1024))
    host = read_json(ROOT / "wit/host-abi-phase3-v4.json")
    findings = compatibility.import_findings(names["imports"], list(declared["imports"]), host)
    expected_exports = list(declared["exports"])
    if set(names["exports"]) != set(expected_exports):
        findings.append(compatibility.finding("surface-mismatch", "link", "final-component"))
    result = {"componentDigest": digest(read_file(output / "component.wasm", 64 * 1024 * 1024)),
              "hostAbiDigest": digest(encode(host)), "imports": names["imports"], "findings": findings}
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
