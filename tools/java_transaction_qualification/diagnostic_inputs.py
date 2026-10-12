"""Select one separately measured diagnostic guest without changing FF9 inputs.

The explicit digests identify retained compiler evidence. They neither grant
native authority nor qualify any fault. The original archive and receipt are
copied byte for byte; no compiler/controller receipt is reconstructed.
"""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import io
from pathlib import Path
import re
import tarfile

from tools.rust_capsule_project import inventory, read_file, snapshot

from .inputs import (ComponentInput, MAX_COMPONENT_BYTES, REQUIRED_IMPORTS,
                     TOOL_PRODUCER_SOURCE, WORLD, decode, digest, require)

NAME = "put-once-diagnostics"
PREFIX = "capture/" + NAME + "/"
SELECTORS = {"trapAfterStage": "4294967293", "loopAfterStage": "4294967294",
             "memoryAfterStage": "4294967292"}
ARGUMENTS = ("diagnostic_capture", "diagnostic_receipt", "diagnostic_source_commit",
             "diagnostic_component_digest", "diagnostic_capture_digest", "diagnostic_receipt_digest")
LIMITS = {"cpuFuel": 1000000000, "memoryBytes": 67108864, "wallTimeLimitMillis": 120000,
          "childCalls": 0, "outboundRequests": 0, "stateReadBytes": 4194304,
          "stateWriteBytes": 2097152, "blobReadBytes": 0, "blobWriteBytes": 0,
          "logBytes": 0, "effectCount": 1}


def selection(args):
    values = {name: getattr(args, name, None) for name in ARGUMENTS}
    present = [value is not None for value in values.values()]
    require(not any(present) or all(present), "complete-explicit-diagnostic-inputs-required")
    if not any(present):
        return None
    require(getattr(args, "recovery_helper", None) is None,
            "diagnostic-and-offline-programs-require-separate-bounded-candidates")
    for name in ("diagnostic_capture", "diagnostic_receipt"):
        path = values[name]
        require(isinstance(path, Path) and path.is_absolute() and path.is_file() and not path.is_symlink(),
                "original-diagnostic-regular-input-required")
        values[name] = str(path)
    require(re.fullmatch(r"[0-9a-f]{40}", values["diagnostic_source_commit"] or ""),
            "explicit-diagnostic-source-required")
    require(all(isinstance(values[name], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", values[name])
                for name in ("diagnostic_component_digest", "diagnostic_capture_digest", "diagnostic_receipt_digest")),
            "explicit-diagnostic-evidence-digests-required")
    return values


def archive(raw):
    """Decode the captured regular files with fixed compressed/unpacked bounds."""
    require(0 < len(raw) <= 64 * 1024 * 1024, "diagnostic-capture-byte-bound")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        unpacked = compressed.read(128 * 1024 * 1024 + 1)
    require(len(unpacked) <= 128 * 1024 * 1024, "diagnostic-unpacked-byte-bound")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(unpacked), mode="r:") as captured:
        for member in captured:
            name = member.name
            require(len(files) < 1024 and member.isfile() and name.startswith(PREFIX)
                    and member.type == tarfile.REGTYPE and set(member.pax_headers) <= {"path", "mtime"}
                    and member.pax_headers.get("path", name) == name
                    and re.fullmatch(r"[0-9]{1,20}(?:\.[0-9]{1,12})?", member.pax_headers.get("mtime", "0")),
                    "diagnostic-capture-regular-member-required")
            relative = name[len(PREFIX):]
            require(relative and len(relative.encode()) <= 512 and "\\" not in relative
                    and all(part not in {"", ".", ".."} for part in relative.split("/"))
                    and len(relative.split("/")) <= 16 and not any(ord(c) < 32 or ord(c) == 127 for c in relative)
                    and relative not in files and 0 <= member.size <= MAX_COMPONENT_BYTES,
                    "diagnostic-capture-member-bound")
            files[relative] = captured.extractfile(member).read(member.size + 1)
            require(len(files[relative]) == member.size, "diagnostic-capture-member-size")
        require(not any(unpacked[captured.offset:]), "diagnostic-capture-nonzero-trailing-bytes")
    require(files, "nonempty-diagnostic-compiler-capture")
    return files


def declaration(raw, files):
    value = decode(raw)
    flags = {"componentCompiled", "stateExecutionQualified", "cancellationQualified",
             "fuelExhaustionQualified", "freshInstanceQualified"}
    base = {"schemaVersion", "selectors", "selectedBusinessDelta", "freshInstanceRequired", "faultAfter",
            "originalSourceDigest", "sourceDigest", "helperDigest", "worldDigest", "companionDigest", "requirementsDigest"}
    selectors = value.get("selectors")
    require(selectors in ({name: SELECTORS[name] for name in ("trapAfterStage", "loopAfterStage")}, SELECTORS),
            "closed-compiled-diagnostic-selector-set")
    if "memoryAfterStage" in selectors:
        flags |= {"memoryExhaustionQualified", "crashBeforeCommitQualified"}
    require(set(value) == base | flags and value["schemaVersion"] == "latent.java.transaction-diagnostic-inputs.v1"
            and value["selectedBusinessDelta"] == "1" and value["freshInstanceRequired"] is True
            and value["faultAfter"] == ["state-put", "captured-put-once-intent"]
            and all(value[name] is False for name in flags), "diagnostic-declaration-is-not-runtime-proof")
    for name in ("originalSourceDigest", "sourceDigest", "helperDigest", "worldDigest", "companionDigest", "requirementsDigest"):
        require(isinstance(value[name], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value[name]),
                "diagnostic-declaration-digest")
    for field, path in (("sourceDigest", "src/dev/latent/app/Capsule.java"),
                        ("worldDigest", "wit/world.wit"), ("companionDigest", "transaction-binding.json"),
                        ("requirementsDigest", "deferred-http-requirements.json")):
        require(path in files and digest(files[path]) == value[field], "diagnostic-source-association")
    return dict(selectors)


@dataclass(frozen=True)
class DiagnosticInput:
    item: ComponentInput
    selectors: dict
    selected: dict
    report_digest: str

    def observation(self):
        return {"input": self.item.observation(), "selection": self.selected, "selectors": self.selectors,
                "compilerReportDigest": self.report_digest, "faultExecutionQualified": False,
                "crashBeforeCommitQualified": False}


def validate(files, receipt_raw, selected):
    required = {"report.json", "compiled/component.wasm", "source-inputs.json", "source.tar.gz",
                "recipe-inputs.json", "compiler-inputs.json", "project/transaction-binding.json",
                "project/transaction-profile.json", "project/deferred-http-requirements.json",
                "project/transaction-diagnostic-inputs.json", "project/capsule-project.json"}
    require(isinstance(files, dict) and required <= set(files), "complete-diagnostic-compiler-materials-required")
    report_raw = files["report.json"]
    report, receipt = decode(report_raw), decode(receipt_raw)
    require(receipt.get("schemaVersion") == "latent.java.transaction-diagnostic-compiler-process.v2"
            and receipt.get("sourceCommit") == selected["diagnostic_source_commit"]
            and receipt.get("originalToolProducer") == TOOL_PRODUCER_SOURCE
            and all(receipt.get(name) is True for name in ("compilerOnly", "compiled", "componentExportAvailable"))
            and receipt.get("signedNodeExecutionQualified") is False,
            "actual-separate-diagnostic-compiler-receipt-required")
    require(report.get("schemaVersion") == "latent.transaction-guest.compiler.v1"
            and report.get("language") == "java" and report.get("variant") == NAME and report.get("world") == WORLD
            and report.get("evidenceKind") == "authored-component-compiler" and report.get("status") == "compiled"
            and report.get("compiled") is True and report.get("workingTreeChanged") is False
            and report.get("signedNodeExecutionQualified") is False and report.get("admissionRejectionQualified") is False
            and report.get("sourceRevision") == selected["diagnostic_source_commit"],
            "actual-diagnostic-compiler-report-required")
    details = report.get("details")
    require(isinstance(details, dict) and set(details) == {"bindings", "commands", "tools"}
            and isinstance(details["commands"], list) and 0 < len(details["commands"]) <= 64
            and all(isinstance(row, dict) and type(row.get("exitCode")) is int and row["exitCode"] == 0
                    and isinstance(row.get("stage"), str) for row in details["commands"])
            and {"java-to-c", "c-to-wasm", "component-new", "component-validate", "compiled-wit"}
            <= {row["stage"] for row in details["commands"]}, "actual-successful-diagnostic-compiler-stages")
    component = files["compiled/component.wasm"]
    require(component.startswith(b"\0asm\x0d\0\x01\0") and 0 < len(component) <= MAX_COMPONENT_BYTES
            and type(report.get("componentBytes")) is int and type(receipt.get("componentBytes")) is int
            and len(component) == report["componentBytes"] == receipt["componentBytes"]
            and digest(component) == report.get("componentDigest") == receipt.get("componentDigest")
            == selected["diagnostic_component_digest"], "original-diagnostic-component-identity")
    project = {name[8:]: raw for name, raw in files.items() if name.startswith("project/")}
    require(inventory(project) == files["source-inputs.json"], "original-diagnostic-project-inventory")
    for field, path in (("sourceDigest", "source-inputs.json"), ("sourceArchiveDigest", "source.tar.gz"),
                        ("recipeDigest", "recipe-inputs.json"), ("companionDigest", "project/transaction-binding.json"),
                        ("deferredHttpRequirementsDigest", "project/deferred-http-requirements.json"),
                        ("diagnosticInputDigest", "project/transaction-diagnostic-inputs.json")):
        require(digest(files[path]) == report.get(field), "original-diagnostic-compiler-materials")
    for field in ("companionDigest", "deferredHttpRequirementsDigest"):
        require(receipt.get(field) == report[field], "diagnostic-process-material-association")
    closure = files["compiler-inputs.json"]
    require(receipt.get("compilerClosure") == {"bytes": len(closure), "sha256": digest(closure)},
            "original-diagnostic-compiler-closure")
    profile = decode(project["transaction-profile.json"])
    require(profile.get("hostAbiDigest") == report.get("hostAbiDigest"), "diagnostic-actual-abi-association")
    imports = report.get("actualImports")
    require(isinstance(imports, list) and 0 < len(imports) <= 16 and all(isinstance(v, str) for v in imports)
            and len(imports) == len(set(imports)) and REQUIRED_IMPORTS <= set(imports)
            and set(imports) <= REQUIRED_IMPORTS | {"latent:clock/monotonic@0.1.0", "latent:clock/wall@0.1.0"},
            "diagnostic-provider-free-command-imports")
    project_value = decode(project["capsule-project.json"])
    limits = project_value.get("limits")
    require(isinstance(limits, dict) and set(limits) == set(LIMITS)
            and all(type(value) is int for value in limits.values()) and limits == LIMITS,
            "unchanged-original-diagnostic-budget")
    requirements = decode(project["deferred-http-requirements.json"])
    require(requirements.get("authority") == {"installed": False, "ruleGranted": False, "executionQualified": False},
            "diagnostic-requirements-grant-no-authority")
    selectors = declaration(project["transaction-diagnostic-inputs.json"], project)
    return report, selectors


def load(args, output):
    selected = selection(args)
    if selected is None:
        return None
    require(output.is_absolute() and not output.is_symlink(), "private-retained-diagnostic-root")
    capture = read_file(Path(selected["diagnostic_capture"]), 64 * 1024 * 1024)
    receipt = read_file(Path(selected["diagnostic_receipt"]), 262144)
    require(digest(capture) == selected["diagnostic_capture_digest"]
            and digest(receipt) == selected["diagnostic_receipt_digest"], "pinned-diagnostic-evidence-byte-identity")
    files = archive(capture)
    report, selectors = validate(files, receipt, selected)
    # Copies carry original bytes, not regenerated compiler observations.
    if not output.exists():
        output.mkdir(mode=0o700)
        retained = {name: files[name] for name in ("report.json", "source-inputs.json", "source.tar.gz",
                                                 "recipe-inputs.json", "compiler-inputs.json")}
        retained.update({name: raw for name, raw in files.items() if name.startswith("project/")})
        retained.update({"component.wasm": files["compiled/component.wasm"], "compiler-process-receipt.json": receipt,
                         "original-compiler-capture.tar.gz": capture})
        for name, raw in retained.items():
            path = output / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open("xb") as target:
                target.write(raw)
            path.chmod(0o600)
    require(inventory(snapshot(output / "project")) == files["source-inputs.json"]
            and read_file(output / "component.wasm", MAX_COMPONENT_BYTES) == files["compiled/component.wasm"]
            and all(read_file(output / name, 64 * 1024 * 1024) == raw for name, raw in
                    (("original-compiler-capture.tar.gz", capture), ("compiler-process-receipt.json", receipt),
                     ("report.json", files["report.json"]), ("source-inputs.json", files["source-inputs.json"]),
                     ("source.tar.gz", files["source.tar.gz"]), ("recipe-inputs.json", files["recipe-inputs.json"]),
                     ("compiler-inputs.json", files["compiler-inputs.json"]))), "retained-diagnostic-evidence-drift")
    item = ComponentInput(NAME, output, report["componentDigest"], report["companionDigest"], report["sourceDigest"],
                          report["sourceRevision"], report["hostAbiDigest"], report["deferredHttpRequirementsDigest"])
    return DiagnosticInput(item, selectors, selected, digest(files["report.json"]))
