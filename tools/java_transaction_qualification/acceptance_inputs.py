"""Select the original sealed value/child captures without granting authority."""
from dataclasses import dataclass
import gzip
import io
import json
from pathlib import Path
import re
import tarfile

from tools.rust_capsule_project import inventory, read_file, snapshot
from . import compiler_exports
from .inputs import ComponentInput, WORLD, decode, digest, require

VALUE = "put-once-values"
CHILD = "forbidden-child"
STATE = {"latent:state/key-value@0.2.0", "latent:intents/staging@0.1.0"}
CLOCKS = {"latent:clock/monotonic@0.1.0", "latent:clock/wall@0.1.0"}
CALL = "latent:service/invoke@0.1.0"
SELECTORS = {"highBit": "4294967280", "unsignedMaximum": "4294967281"}
UNSIGNED = {"highBit": "9223372036854775808", "unsignedMaximum": "18446744073709551615"}
PATH_ARGUMENTS = {"acceptance_export_root", "acceptance_process_receipt", "acceptance_export_receipt",
                  "acceptance_export_census"}
ARGUMENTS = ("acceptance_export_root", "acceptance_process_receipt", "acceptance_process_receipt_digest",
             "acceptance_export_receipt", "acceptance_export_receipt_digest", "acceptance_export_census",
             "acceptance_export_census_digest", "acceptance_source_commit",
             "acceptance_value_component_digest", "acceptance_child_component_digest")


def selection(args):
    values = {name: getattr(args, name, None) for name in ARGUMENTS}
    enabled = getattr(args, "value_child_acceptance_only", False)
    require(type(enabled) is bool, "explicit-value-child-programme")
    if not enabled and not any(value is not None for value in values.values()):
        return None
    require(enabled and all(value is not None for value in values.values()),
            "complete-explicit-value-child-materials")
    from .diagnostic_inputs import ARGUMENTS as diagnostic_arguments
    require(all(getattr(args, name, None) is None for name in diagnostic_arguments)
            and getattr(args, "current_selections", None) is None
            and getattr(args, "current_selections_digest", None) is None
            and getattr(args, "recovery_helper", None) is None
            and getattr(args, "reviewed_policy_environment", None) is None
            and getattr(args, "reviewed_policy_environment_digest", None) is None
            and not getattr(args, "pending_restore_only", False),
            "value-child-programme-requires-separate-candidate")
    require(getattr(args, "prepare_authority_only", False)
            or getattr(args, "resume_candidate", None) is not None,
            "value-child-programme-requires-stopped-candidate-review")
    for name in PATH_ARGUMENTS:
        path = values[name]
        require(isinstance(path, Path) and path.is_absolute() and not path.is_symlink()
                and (path.is_dir() if name == "acceptance_export_root" else path.is_file()),
                "regular-original-value-child-input")
        values[name] = str(path)
    require(re.fullmatch(r"[0-9a-f]{40}", values["acceptance_source_commit"] or ""),
            "explicit-value-child-compiler-source")
    for name in set(ARGUMENTS) - PATH_ARGUMENTS - {"acceptance_source_commit"}:
        require(isinstance(values[name], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", values[name]),
                "explicit-value-child-material-digest")
    require(values["acceptance_value_component_digest"] != values["acceptance_child_component_digest"],
            "distinct-original-value-child-components")
    return values


def declaration(raw, project):
    value = decode(raw)
    claims = {"componentCompiled", "signedStateExecutionQualified", "unsignedRoundtripQualified",
              "utf8RoundtripQualified", "absentOptionalQualified"}
    fields = {"schemaVersion", "selectors", "expectedUnsignedValues", "utf8Text", "utf8PayloadDigest",
              "absentOptionalRequired", "freshInstanceRequired", "originalSourceDigest", "sourceDigest",
              "worldDigest", "companionDigest"}
    require(set(value) == fields | claims and value["schemaVersion"] == "latent.java.transaction-value-inputs.v1"
            and value["selectors"] == SELECTORS and value["expectedUnsignedValues"] == UNSIGNED
            and value["absentOptionalRequired"] is True and value["freshInstanceRequired"] is True
            and all(value[name] is False for name in claims), "value-declaration-is-not-runtime-proof")
    text = value["utf8Text"]
    require(isinstance(text, str) and 0 < len(text.encode()) <= 1024 and not text.isascii(),
            "bounded-original-nonascii-value")
    require(value["utf8PayloadDigest"] == digest(json.dumps([None, text], ensure_ascii=False,
            separators=(",", ":")).encode()), "original-null-utf8-payload-digest")
    for field in ("originalSourceDigest", "sourceDigest", "worldDigest", "companionDigest", "utf8PayloadDigest"):
        require(isinstance(value[field], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value[field]),
                "original-value-declaration-digest")
    for field, path in (("sourceDigest", "src/dev/latent/app/Capsule.java"), ("worldDigest", "wit/world.wit"),
                        ("companionDigest", "transaction-binding.json")):
        require(path in project and digest(project[path]) == value[field], "original-value-source-association")
    return value


def validate(exported, selected, name):
    require(name in {VALUE, CHILD}, "closed-original-value-child-variant")
    files = exported.files
    required = {"report.json", "compiled/component.wasm", "source-inputs.json", "source.tar.gz",
                "recipe-inputs.json", "compiler-inputs.json", "project/transaction-binding.json",
                "project/transaction-profile.json", "project/capsule-project.json"}
    require(required <= set(files), "complete-original-value-child-materials")
    report = decode(files["report.json"])
    require(report.get("schemaVersion") == "latent.transaction-guest.compiler.v1"
            and report.get("language") == "java" and report.get("variant") == name
            and report.get("world") == WORLD and report.get("evidenceKind") == "authored-component-compiler"
            and report.get("sourceRevision") == selected["acceptance_source_commit"]
            and report.get("status") == "compiled" and report.get("compiled") is True
            and report.get("workingTreeChanged") is False
            and report.get("signedNodeExecutionQualified") is False
            and report.get("admissionRejectionQualified") is False, "original-value-child-compiler-report")
    details = report.get("details")
    require(isinstance(details, dict) and set(details) == {"bindings", "commands", "tools"}
            and isinstance(details["commands"], list) and 0 < len(details["commands"]) <= 64
            and all(isinstance(row, dict) and type(row.get("exitCode")) is int and row["exitCode"] == 0
                    and isinstance(row.get("stage"), str) for row in details["commands"])
            and {"java-to-c", "c-to-wasm", "component-new", "component-validate", "compiled-wit"}
            <= {row["stage"] for row in details["commands"]}, "actual-value-child-compiler-stages")
    identity = exported.identity
    component = files["compiled/component.wasm"]
    expected = selected["acceptance_value_component_digest" if name == VALUE else "acceptance_child_component_digest"]
    require(component.startswith(b"\0asm\x0d\0\x01\0") and 0 < len(component) <= compiler_exports.MAX_FILE_BYTES
            and len(component) == report.get("componentBytes") == identity.get("componentBytes")
            and digest(component) == expected == report.get("componentDigest") == identity.get("componentDigest"),
            "original-value-child-component-identity")
    project = {path[8:]: raw for path, raw in files.items() if path.startswith("project/")}
    require(inventory(project) == files["source-inputs.json"], "original-value-child-source-inventory")
    for field, path in (("sourceDigest", "source-inputs.json"), ("sourceArchiveDigest", "source.tar.gz"),
                        ("recipeDigest", "recipe-inputs.json"), ("companionDigest", "project/transaction-binding.json")):
        require(digest(files[path]) == report.get(field) == identity.get(field), "original-value-child-material-identity")
    require(digest(files["compiler-inputs.json"]) == identity["compilerInputsDigest"],
            "original-value-child-compiler-closure")
    require(decode(project["transaction-profile.json"]).get("hostAbiDigest") == report.get("hostAbiDigest"),
            "original-value-child-captured-profile")
    imports = report.get("actualImports")
    mandatory = STATE | ({CALL} if name == CHILD else set())
    require(isinstance(imports, list) and all(isinstance(row, str) for row in imports)
            and len(imports) == len(set(imports)) and mandatory <= set(imports) <= mandatory | CLOCKS,
            "actual-value-child-closed-imports")
    # The authored project and archive must be the same original regular bytes.
    with gzip.GzipFile(fileobj=io.BytesIO(files["source.tar.gz"])) as compressed:
        unpacked = compressed.read(128 * 1024 * 1024 + 1)
    require(len(unpacked) <= 128 * 1024 * 1024, "original-value-child-archive-bound")
    archived = {}
    with tarfile.open(fileobj=io.BytesIO(unpacked), mode="r:") as archive:
        for member in archive:
            require(member.isfile() and member.type == tarfile.REGTYPE and member.name in project
                    and member.name not in archived and member.size == len(project[member.name])
                    and set(member.pax_headers) <= {"path"}
                    and member.pax_headers.get("path", member.name) == member.name,
                    "original-value-child-archive-member")
            archived[member.name] = archive.extractfile(member).read(member.size + 1)
    require(archived == project, "original-value-child-archive-project")
    value = None
    if name == VALUE:
        require("transaction-value-inputs.json" in project and "deferred-http-requirements.json" in project,
                "original-value-declaration-and-requirements")
        value = declaration(project["transaction-value-inputs.json"], project)
        require(digest(project["deferred-http-requirements.json"]) == report.get("deferredHttpRequirementsDigest")
                == identity["requirementsDigest"], "original-value-effect-requirements")
    else:
        require(identity["requirementsDigest"] is None and "deferred-http-requirements.json" not in project,
                "forbidden-child-cannot-obtain-dispatch-authority")
    return report, value


@dataclass(frozen=True)
class AcceptanceInputs:
    items: tuple[ComponentInput, ...]
    value: dict
    selected: dict

    def observation(self):
        return {"programme": "signed-java-values-and-forbidden-child", "selection": self.selected,
                "inputs": [item.observation() for item in self.items], "valueDeclaration": self.value,
                "signedExecutionQualified": False}


def load(args, output):
    selected = selection(args)
    if selected is None:
        return None
    items, value = [], None
    for name in (VALUE, CHILD):
        exported = compiler_exports.load(Path(selected["acceptance_export_root"]),
            Path(selected["acceptance_process_receipt"]), selected["acceptance_process_receipt_digest"],
            Path(selected["acceptance_export_receipt"]), selected["acceptance_export_receipt_digest"],
            Path(selected["acceptance_export_census"]), selected["acceptance_export_census_digest"],
            selected["acceptance_source_commit"], name)
        report, declaration_value = validate(exported, selected, name)
        if declaration_value is not None:
            value = declaration_value
        retained = {path: raw for path, raw in exported.files.items() if path.startswith("project/")
                    or path in {"report.json", "source-inputs.json", "source.tar.gz", "recipe-inputs.json", "compiler-inputs.json"}}
        retained.update({"component.wasm": exported.files["compiled/component.wasm"],
            "original-process-receipt.json": exported.process, "original-export-receipt.json": exported.seal,
            "original-export-census.json": exported.census})
        directory = output / name
        if not directory.exists():
            directory.mkdir(mode=0o700, parents=True)
            for path, raw in retained.items():
                target = directory / path
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(raw)
                target.chmod(0o600)
        for path, raw in retained.items():
            require(read_file(directory / path, compiler_exports.MAX_FILE_BYTES) == raw,
                    "retained-original-value-child-drift")
        require(inventory(snapshot(directory / "project")) == retained["source-inputs.json"],
                "retained-original-value-child-project")
        items.append(ComponentInput(name, directory, report["componentDigest"], report["companionDigest"],
            report["sourceDigest"], report["sourceRevision"], report["hostAbiDigest"], exported.identity["requirementsDigest"]))
    require(items[0].host_abi_digest == items[1].host_abi_digest, "same-original-value-child-abi")
    return AcceptanceInputs(tuple(items), value, selected)
