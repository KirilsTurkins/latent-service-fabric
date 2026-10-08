"""Select an explicit current six-component capture; no historical fallback."""
from pathlib import Path
import re

from tools.rust_capsule_project import read_file
from .current_inputs import CurrentSelection, NAMES, load_current
from .inputs import decode, digest, require

FIELDS = {"sourceCommit", "variant", "reportDigest", "componentDigest", "compilerInputsDigest"}


def selection(args):
    path = getattr(args, "current_selections", None)
    expected = getattr(args, "current_selections_digest", None)
    require((path is None) == (expected is None), "paired-current-java-campaign-inputs")
    if path is None:
        return None
    root = args.portable
    require(isinstance(root, Path) and root.is_absolute() and not root.is_symlink()
            and root.is_dir(), "explicit-current-java-campaign-root")
    rows = selections(root, path, expected)
    return {"portable": str(root), "selectionPath": str(path), "selectionDigest": expected,
            "materials": [{"sourceCommit": row.source_commit, "variant": row.variant,
                           "reportDigest": row.report_digest, "componentDigest": row.component_digest,
                           "compilerInputsDigest": row.compiler_inputs_digest} for _directory, row in rows]}


def selections(root: Path, path: Path, expected_digest: str):
    require(path.is_absolute() and path.is_file() and not path.is_symlink()
            and re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest or ""),
            "explicit-current-campaign-selection-digest")
    raw = read_file(path, 65536)
    require(digest(raw) == expected_digest, "current-campaign-selection-changed")
    value = decode(raw, 65536)
    require(set(value) == {"schemaVersion", "selections"}
            and value["schemaVersion"] == "latent.java.current-campaign-selections.v1",
            "closed-current-campaign-selection")
    rows = value["selections"]
    require(isinstance(rows, list) and len(rows) == 6
            and all(isinstance(row, dict) and set(row) == FIELDS for row in rows),
            "all-six-explicit-current-java-captures-required")
    selected = tuple(CurrentSelection(row["sourceCommit"], row["variant"], row["reportDigest"],
                                     row["componentDigest"], row["compilerInputsDigest"]) for row in rows)
    for row in selected:
        row.validate()
    require({row.variant for row in selected} == set(NAMES)
            and len({row.source_commit for row in selected}) == 1
            and len({row.component_digest for row in selected}) == 6,
            "distinct-six-current-captures-and-single-compiler-source")
    return tuple((root / row.variant, row) for row in selected)


def load(args):
    selected = selections(args.portable, args.current_selections, args.current_selections_digest)
    items = tuple(load_current(directory, row) for directory, row in selected)
    item = next(item for item in items if item.name == "put-once-diagnostics")
    from .diagnostic_inputs import DiagnosticInput, declaration
    from tools.rust_capsule_project import snapshot
    files = snapshot(item.directory / "project")
    raw = files["transaction-diagnostic-inputs.json"]
    selectors = declaration(raw, files)
    legacy = next(row for row in items if row.name == "put-once-legacy-v1")
    require(item.companion_digest == legacy.companion_digest
            and item.requirements_digest == legacy.requirements_digest
            and item.host_abi_digest == legacy.host_abi_digest,
            "same-current-diagnostic-original-binding-requirements-and-abi")
    selected_diagnostic = next(row for _directory, row in selected if row.variant == item.name)
    selection = {"sourceSelection": "explicit-current-report-material-digests",
                 "compilerSource": item.compiler_source,
                 "componentDigest": item.component_digest,
                 "compilerInputsDigest": selected_diagnostic.compiler_inputs_digest,
                 "diagnosticDeclarationDigest": digest(raw)}
    return items, DiagnosticInput(item, selectors, selection, selected_diagnostic.report_digest)
