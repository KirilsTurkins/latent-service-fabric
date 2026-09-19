"""Read tracked text as data; redact secrets and use local reviewed static rules."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re

from tools.security_common import POLICY, changed_paths, decode_json, digest, read_file, require, run, tracked_paths
from tools.security_findings import Finding, finding
from tools.security_install import verify_tool

BINARY_SUFFIXES = frozenset({".gz", ".zip", ".wasm", ".png", ".jpg", ".jpeg", ".gif", ".ico",
                             ".pdf", ".woff", ".woff2", ".exe", ".dll", ".pdb", ".a", ".so", ".bin"})
MAX_TEXT_BYTES = 384 * 1024 * 1024
MAX_TEXT_FILE_BYTES = 16 * 1024 * 1024
SOURCE_ROOTS = frozenset({"apps", "crates", "sdk", "tools", "examples", "tests"})
TEXT_SUFFIXES = frozenset({".md", ".svg", ".rs", ".py", ".go", ".java", ".cs", ".c", ".h", ".cpp", ".hpp",
                          ".js", ".ts", ".mjs", ".cjs", ".tsx", ".sh", ".ps1", ".yml", ".yaml", ".json",
                          ".toml", ".txt", ".lock", ".xml", ".pem", ".key", ".crt"})


def staged_name(path: str) -> str:
    return digest(path.encode("utf-8")) + ".txt"


def stage_text(repo: Path, destination: Path, paths: list[str] | None = None) -> tuple[list[str], int]:
    destination.mkdir(parents=True, exist_ok=False)
    staged, total, binaries = [], 0, 0
    for path in tracked_paths(repo) if paths is None else paths:
        name = PurePosixPath(path)
        if name.suffix in BINARY_SUFFIXES or re.search(r"\.tar\.gz\.part-[0-9]+$", name.name):
            binaries += 1
            continue
        payload = read_file(repo, path, MAX_TEXT_FILE_BYTES)
        if b"\0" in payload:
            require(name.suffix not in TEXT_SUFFIXES, "binary-content-in-text-surface")
            binaries += 1
            continue
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError:
            require(False, "unknown-text-encoding")
        total += len(payload)
        require(total <= MAX_TEXT_BYTES, "text-tree-size-limit")
        target = destination / staged_name(path)
        target.write_bytes(payload)
        target.chmod(0o600)
        staged.append(path)
    return staged, binaries


def scan_secrets(staged: Path, paths: list[str], binary: Path, scratch: Path) -> list[Finding]:
    empty_ignore = scratch / "empty.gitleaksignore"
    empty_ignore.write_text("", encoding="utf-8")
    status, output = run([
        str(binary), "dir", str(staged), "--config", str(POLICY / "gitleaks.toml"),
        "--redact=100", "--no-banner", "--no-color", "--log-level=error", "--ignore-gitleaks-allow",
        "--gitleaks-ignore-path", str(empty_ignore), "--report-format=json", "--report-path=-",
        "--exit-code=10", "--timeout=120", "--max-decode-depth=2", "--max-archive-depth=0",
    ], scratch, timeout=135, accepted=(0, 10))
    report = decode_json(output)
    require(isinstance(report, list) and len(report) <= 10000, "invalid-gitleaks-report")
    require(status == (10 if report else 0), "gitleaks-exit-report-mismatch")
    findings = []
    names = {staged_name(path): path for path in paths}
    for entry in report:
        name = Path(entry["File"]).name
        require(name in names, "gitleaks-unscanned-path")
        path = names[name]
        findings.append(finding("gitleaks", entry["RuleID"], path, line=entry["StartLine"],
                                column=entry["StartColumn"],
                                content=read_file(staged, name, MAX_TEXT_FILE_BYTES)))
    return findings


def secrets(repo: Path, scratch: Path, tools: Path, base: str = "") -> tuple[list[Finding], dict]:
    staged = scratch / "tracked-text"
    selected = None
    if base and base != "0" * 40:
        _, revision = run(["git", "-C", str(repo), "rev-parse", "HEAD"], scratch, timeout=15)
        present = set(tracked_paths(repo))
        selected = [path for path in changed_paths(repo, base, revision.decode().strip()) if path in present]
    paths, binaries = stage_text(repo, staged, selected)
    binary = verify_tool("gitleaks", tools)
    findings = scan_secrets(staged, paths, binary, scratch) if paths else []
    return findings, {"text_files": len(paths), "binary_files_not_scanned": binaries,
                      "scope": "changed-present-files" if selected is not None else "all-tracked-files",
                      "history": "GitHub secret scanning; this job checks the selected tracked snapshot"}


def source_findings(repo: Path, paths: list[str]) -> list[Finding]:
    document = decode_json(read_file(POLICY, "source-rules.json"))
    require(document.get("schema") == 1 and 0 < len(document["rules"]) <= 32, "invalid-source-rules")
    rules = [(entry, re.compile(entry["pattern"])) for entry in document["rules"]]
    findings = []
    total = 0
    for path in paths:
        relative = PurePosixPath(path)
        if relative.parts[0] not in SOURCE_ROOTS:
            continue
        selected = [(entry, pattern) for entry, pattern in rules if relative.suffix in entry["extensions"]]
        if not selected:
            continue
        payload = read_file(repo, path)
        total += len(payload)
        require(total <= MAX_TEXT_BYTES, "source-tree-size-limit")
        text = payload.decode("utf-8")
        for entry, pattern in selected:
            for match in pattern.finditer(text):
                findings.append(finding("source", entry["id"], path, line=text.count("\n", 0, match.start()) + 1,
                                        column=match.start() - text.rfind("\n", 0, match.start()),
                                        content=payload))
                require(len(findings) <= 10000, "source-finding-limit")
    return findings


def workflow_findings(repo: Path, paths: list[str], binary: Path, scratch: Path) -> list[Finding]:
    from tools.validate_workflow_actions import validate_repository

    _, _, pin_failures = validate_repository(repo)
    require(not pin_failures, "workflow-action-pin-policy")
    selected = [path for path in paths if (path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml")))
                or PurePosixPath(path).name in {"action.yml", "action.yaml"}
                or path == ".github/dependabot.yml"]
    require(0 < len(selected) <= 256, "workflow-count-limit")
    for path in selected:
        read_file(repo, path, 128 * 1024)
    _, output = run([str(binary), "--offline", "--no-config", "--no-ignores", "--no-exit-codes",
                     "--strict-collection", "--no-progress", "--persona=regular", "--format=json-v1",
                     *[str(repo / path) for path in selected]], scratch, timeout=120)
    report = decode_json(output)
    require(isinstance(report, list) and len(report) <= 10000, "invalid-zizmor-report")
    findings = []
    for entry in report:
        primary = [location for location in entry["locations"] if location["symbolic"]["kind"] == "Primary"]
        require(bool(primary), "missing-zizmor-location")
        location = primary[0]
        path = Path(location["symbolic"]["key"]["Local"]["verbatim_path"]).relative_to(repo).as_posix()
        require(path in selected, "zizmor-unscanned-path")
        line = location["concrete"]["location"]["start_point"]["row"] + 1
        column = location["concrete"]["location"]["start_point"]["column"] + 1
        findings.append(finding("zizmor", entry["ident"], path, line=line, column=column, content=read_file(repo, path)))
    return findings


def static(repo: Path, scratch: Path, tools: Path) -> tuple[list[Finding], dict]:
    paths = tracked_paths(repo)
    findings = source_findings(repo, paths)
    binary = verify_tool("zizmor", tools)
    findings.extend(workflow_findings(repo, paths, binary, scratch))
    return findings, {"source_rules": "local source-rules.json", "workflow_rules": "zizmor regular/offline, no ignores",
                      "tracked_files": len(paths), "action_pin_policy": "#281"}
