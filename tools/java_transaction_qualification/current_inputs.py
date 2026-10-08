"""Explicit current authored Java selections; preserved historical input pins stay intact.

These independent report/material digests are test-input custody, never compiler,
signing, current publication or execution authority. No fallback rewrites r3.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import gzip
import io
import tarfile
import re

from tools.rust_capsule_project import checked_path, inventory, read_file, snapshot
from .inputs import ComponentInput, MAX_COMPONENT_BYTES, REQUIRED_IMPORTS, VARIANTS, WORLD, decode, digest, require

NAMES = (*VARIANTS, "put-once-diagnostics")
SUCCESS_STAGES = {"java-to-c", "c-to-wasm", "component-new", "component-validate", "compiled-wit"}


@dataclass(frozen=True)
class CurrentSelection:
    source_commit: str
    variant: str
    report_digest: str
    component_digest: str
    compiler_inputs_digest: str

    def validate(self):
        require(re.fullmatch(r"[0-9a-f]{40}", self.source_commit or "")
                and self.variant in NAMES, "explicit-current-java-source-and-variant")
        require(all(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value)
                    for value in (self.report_digest, self.component_digest, self.compiler_inputs_digest)),
                "explicit-current-java-material-digests")


def validate_materials(files: dict[str, bytes], selected: CurrentSelection) -> dict:
    """Bounded digest/shape validation only; synthetic callers gain no execution claim."""
    selected.validate()
    required = {"report.json", "component.wasm", "source-inputs.json", "source.tar.gz", "recipe-inputs.json", "compiler-inputs.json"}
    require(isinstance(files, dict) and required <= set(files) and len(files) <= 4096
            and all(isinstance(name, str) and isinstance(raw, bytes) for name, raw in files.items()),
            "complete-current-java-materials")
    limits = {"report.json": 262144, "component.wasm": MAX_COMPONENT_BYTES, "source.tar.gz": 32 * 1024 * 1024,
              "source-inputs.json": 4 * 1024 * 1024, "recipe-inputs.json": 4 * 1024 * 1024,
              "compiler-inputs.json": 4 * 1024 * 1024}
    require(all(0 < len(raw) <= limits.get(name, 16 * 1024 * 1024) for name, raw in files.items())
            and sum(map(len, files.values())) <= 128 * 1024 * 1024,
            "current-java-material-byte-bounds")
    report_raw = files["report.json"]
    require(digest(report_raw) == selected.report_digest, "current-java-report-digest")
    report = decode(report_raw)
    require(report.get("schemaVersion") == "latent.transaction-guest.compiler.v1"
            and report.get("language") == "java" and report.get("variant") == selected.variant
            and report.get("evidenceKind") == "authored-component-compiler" and report.get("world") == WORLD
            and report.get("sourceRevision") == selected.source_commit and report.get("status") == "compiled"
            and report.get("compiled") is True and report.get("workingTreeChanged") is False
            and report.get("signedNodeExecutionQualified") is False and report.get("admissionRejectionQualified") is False,
            "current-java-compiler-report-shape")
    component = files["component.wasm"]
    require(component.startswith(b"\0asm\x0d\0\x01\0") and 0 < len(component) <= MAX_COMPONENT_BYTES
            and type(report.get("componentBytes")) is int and len(component) == report["componentBytes"]
            and digest(component) == selected.component_digest == report.get("componentDigest"),
            "current-java-component-identity")
    project = {name[8:]: raw for name, raw in files.items() if name.startswith("project/")}
    require(all(name and "\\" not in name and ":" not in name and not name.startswith("/")
                and len(name.encode()) <= 512 and len(name.split("/")) <= 32
                and all(part not in {"", ".", ".."} for part in name.split("/")) for name in project),
            "current-java-project-path-bounds")
    require(project and inventory(project) == files["source-inputs.json"], "current-java-captured-project")
    for field, path in (("sourceDigest", "source-inputs.json"), ("sourceArchiveDigest", "source.tar.gz"),
                        ("recipeDigest", "recipe-inputs.json"), ("companionDigest", "project/transaction-binding.json")):
        require(path in files and digest(files[path]) == report.get(field), "current-java-compiler-material-identity")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(files["source.tar.gz"])) as compressed:
            unpacked = compressed.read(128 * 1024 * 1024 + 1)
        require(len(unpacked) <= 128 * 1024 * 1024, "current-java-source-archive-bound")
        archived = {}
        with tarfile.open(fileobj=io.BytesIO(unpacked), mode="r:") as source:
            for member in source:
                require(member.isfile() and member.type == tarfile.REGTYPE and member.name in project
                        and member.name not in archived and member.size == len(project[member.name])
                        and not member.pax_headers, "current-java-source-archive-members")
                archived[member.name] = source.extractfile(member).read(member.size + 1)
        require(archived == project, "current-java-source-archive-project-mismatch")
    except (OSError, EOFError, tarfile.TarError) as error:
        raise ValueError("current-java-source-archive-format") from error
    require(digest(files["compiler-inputs.json"]) == selected.compiler_inputs_digest,
            "current-java-compiler-closure-identity")
    profile = decode(project["transaction-profile.json"])
    require(profile.get("hostAbiDigest") == report.get("hostAbiDigest"), "current-java-captured-profile")
    imports = report.get("actualImports")
    require(isinstance(imports, list) and 0 < len(imports) <= 16 and len(imports) == len(set(imports))
            and all(isinstance(item, str) for item in imports) and REQUIRED_IMPORTS <= set(imports)
            and set(imports) <= REQUIRED_IMPORTS | {"latent:clock/monotonic@0.1.0", "latent:clock/wall@0.1.0", "latent:http/client@0.2.0"}
            and (("latent:http/client@0.2.0" in imports) == (selected.variant == "forbidden-http")),
            "current-java-actual-transaction-imports")
    details = report.get("details")
    commands = details.get("commands") if isinstance(details, dict) else None
    require(isinstance(commands, list) and 0 < len(commands) <= 64
            and all(isinstance(row, dict) and isinstance(row.get("stage"), str)
                    and type(row.get("exitCode")) is int and row["exitCode"] == 0 for row in commands)
            and SUCCESS_STAGES <= {row["stage"] for row in commands}, "current-java-successful-compiler-stages")
    if selected.variant.startswith("put-once-"):
        requirements = project.get("deferred-http-requirements.json")
        require(requirements is not None and digest(requirements) == report.get("deferredHttpRequirementsDigest"),
                "current-java-original-effect-requirements")
        require(decode(requirements).get("authority") == {"installed": False, "ruleGranted": False, "executionQualified": False},
                "current-java-requirements-create-no-authority")
    return report


def load_current(directory: Path, selected: CurrentSelection) -> ComponentInput:
    """Use an explicit independent current selection, preserving all original reports."""
    directory = checked_path(directory)
    project = snapshot(directory / "project")
    files = {"project/" + name: raw for name, raw in project.items()}
    for name in ("report.json", "source-inputs.json", "source.tar.gz", "recipe-inputs.json", "compiler-inputs.json"):
        files[name] = read_file(directory / name, 32 * 1024 * 1024)
    # A caller's separate custody step places exact compiler bytes here; this
    # API never writes or guesses the component's output path.
    files["component.wasm"] = read_file(directory / "component.wasm", MAX_COMPONENT_BYTES)
    report = validate_materials(files, selected)
    return ComponentInput(selected.variant, directory, report["componentDigest"], report["companionDigest"],
                          report["sourceDigest"], selected.source_commit, report["hostAbiDigest"],
                          report.get("deferredHttpRequirementsDigest"))
