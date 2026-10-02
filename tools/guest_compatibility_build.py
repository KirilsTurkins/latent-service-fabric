"""Inspect emitted imports and bind conservative observations to package bytes."""
from __future__ import annotations

from pathlib import Path

from tools import guest_compatibility as compatibility
from tools.dev_workflow.common import decode, encode, digest, require
from tools.rust_capsule_project import ROOT, inventory, read_file, read_json, write_json

RECIPE = ("tools/guest_compatibility.py", "tools/guest_compatibility_build.py",
          "tools/dev_workflow/common.py", "wit/host-abi-phase3-v4.json")

DEFAULT_PROFILE = "lsf-host-abi-phase3-v4"
HOST_MANIFESTS = {
    DEFAULT_PROFILE: "wit/host-abi-phase3-v4.json",
    "lsf-host-abi-phase3-v5": "wit/host-abi-phase3-v5.json",
}
V5_INTERFACES = frozenset({
    "latent:runtime/activation@0.1.0", "latent:network/streams@0.1.0"})


def declared_host_abi(surface: dict) -> str:
    """Select the frozen profile from authoritative declared WIT interfaces.

    Emitted imports, provider installation and grants cannot select a profile.
    Unsupported interface versions remain unknown to either frozen manifest.
    """
    require(isinstance(surface, dict) and isinstance(surface.get("imports"), (list, dict)),
            "compatibility-declared-imports")
    imports = list(surface["imports"])
    require(len(imports) <= 128, "compatibility-declared-import-limit")
    for name in imports:
        compatibility.token(name)
    require(len(set(imports)) == len(imports), "compatibility-declared-import-limit")
    return "lsf-host-abi-phase3-v5" if V5_INTERFACES.intersection(imports) else DEFAULT_PROFILE


def host_manifest(profile: str) -> dict:
    require(isinstance(profile, str) and profile in HOST_MANIFESTS, "compatibility-unsupported-host-profile")
    host = read_json(ROOT / HOST_MANIFESTS[profile])
    require(host.get("id") == profile, "compatibility-host-profile-identity")
    return host


def capture_host_recipe(output: Path, files: dict[str, bytes], recorded: bytes, surface: dict) -> bytes:
    """Capture a declared profile before its first use without extending V4 inputs.

    Some adapters derive authoritative staged WIT after compilation. The host
    manifest observes that surface; it does not influence guest compilation.
    An added manifest cannot hide changes to any originally captured recipe.
    """
    selected = HOST_MANIFESTS[declared_host_abi(surface)]
    if selected in files:
        return recorded
    require(inventory({name: read_file(ROOT / name) for name in files}) == recorded,
            "compatibility-stale-recipe")
    raw = read_file(ROOT / selected)
    host = decode(raw, 8 * 1024 * 1024)
    require(isinstance(host, dict) and host.get("id") == declared_host_abi(surface),
            "compatibility-host-profile-identity")
    updated = inventory({**files, selected: raw})
    (output / "recipe-inputs.json").write_bytes(updated)
    files[selected] = raw
    return updated


def inspection_manifest(output: Path, inspection: dict | None) -> dict:
    if inspection is not None:
        profile = inspection.get("hostAbiProfile", DEFAULT_PROFILE)
    else:
        surface_path = output / "surface.json"
        profile = declared_host_abi(read_json(surface_path)) if surface_path.exists() else DEFAULT_PROFILE
    return host_manifest(profile)


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


def inspect(commands, wasm: Path, output: Path, declared: dict,
            *, host_abi_profile: str = DEFAULT_PROFILE) -> dict:
    host = host_manifest(host_abi_profile)
    raw = commands.run("compatibility-final-wit", wasm, "component", "wit", output / "component.wasm", "--json")
    names = interface_names(decode(raw, 4 * 1024 * 1024))
    findings = compatibility.import_findings(names["imports"], list(declared["imports"]), host)
    expected_exports = list(declared["exports"])
    if set(names["exports"]) != set(expected_exports):
        findings.append(compatibility.finding("surface-mismatch", "link", "final-component"))
    result = {"componentDigest": digest(read_file(output / "component.wasm", 64 * 1024 * 1024)),
              "hostAbiDigest": digest(encode(host)), "imports": names["imports"], "findings": findings}
    if host_abi_profile != DEFAULT_PROFILE:
        result["hostAbiProfile"] = host_abi_profile
    write_json(output / "compatibility-inspection.json", result)
    if any(item["classification"] in compatibility.BLOCKERS for item in findings):
        raise ValueError("final-component-compatibility-failed; inspect compatibility-inspection.json")
    return result


def package_report(output: Path, files: dict[str, bytes], component: bytes) -> None:
    lock = decode(files["sdk-lock.json"], 8 * 1024 * 1024)
    language = lock.get("language", "rust" if "Cargo.toml" in files else None)
    inspection_path = output / "compatibility-inspection.json"
    inspection = read_json(inspection_path) if inspection_path.exists() else None
    host = inspection_manifest(output, inspection)
    if inspection is not None:
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


def retain_report(output: Path, value: dict, *, kind: str) -> None:
    """Keep a diagnostic beside an existing immutable package/shared report."""
    require(kind in {"failure", "raw"}, "compatibility-diagnostic-kind")
    target = output / "compatibility-report.json"
    if target.exists():
        # A packaged report already has an asset digest. A raw-component
        # report also describes different bytes from the final component.
        # Preserve those identities instead of replacing their report.
        target = output / ("compatibility-" + kind + "-report.json")
    write_json(target, value)


def _failure_report(output: Path, language: str, stage: str) -> None:
    source_path = output / "source-inputs.json"
    if not source_path.exists():
        return  # Source identity is unavailable; do not fabricate a snapshot.
    phase = "link" if stage in {"component", "contracts", "compatibility", "package"} else "compile"
    findings = [compatibility.finding("unresolved-behavior", phase, "not-evaluated")]
    inspection_path = output / "compatibility-inspection.json"
    inspection = read_json(inspection_path) if inspection_path.exists() else None
    host = inspection_manifest(output, inspection)
    component_path = output / "component.wasm"
    component = read_file(component_path, 64 * 1024 * 1024) if component_path.exists() else None
    if inspection is not None:
        require(component is not None and inspection["componentDigest"] == digest(component)
                and inspection["hostAbiDigest"] == digest(encode(host)), "compatibility-stale-inspection")
        findings = [*inspection["findings"], *findings]
    value = compatibility.report(language, digest(read_file(source_path)),
        digest(component) if component is not None else None, host["id"], [], findings)
    retain_report(output, value, kind="failure")
