"""Captured compiler distribution and narrowly mounted Linux build execution."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import sys

from tools.application_dependency_store import DependencyError, read_bytes, regular_path
from tools.build_observation import file_identity
from tools.build_process import run_bounded_result
from tools.build_snapshot import canonical, digest


def dependency_paths(data: bytes) -> list[str]:
    """Parse Clang's bounded Make dependency output, including embedded files."""
    if len(data) > 2 * 1024 * 1024:
        raise DependencyError("compiler-preprocessor-dependency-limit")
    try:
        text = data.decode("utf-8").replace("\\\r\n", "").replace("\\\n", "")
    except UnicodeError:
        raise DependencyError("compiler-preprocessor-dependency-format") from None
    if not text.startswith("lsf-inputs:"):
        raise DependencyError("compiler-preprocessor-dependency-format")
    names, token, index = [], [], len("lsf-inputs:")
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 1
            if index >= len(text) or text[index] not in " \\#\t":
                raise DependencyError("compiler-preprocessor-dependency-escape")
            token.append(text[index])
        elif char == "$":
            index += 1
            if index >= len(text) or text[index] != "$":
                raise DependencyError("compiler-preprocessor-dependency-variable")
            token.append("$")
        elif char.isspace():
            if token:
                names.append("".join(token))
                token = []
        elif char in "\0:#":
            raise DependencyError("compiler-preprocessor-dependency-format")
        else:
            token.append(char)
        index += 1
    if token:
        names.append("".join(token))
    if not names or len(names) > 8192 or any(len(name) > 32768 for name in names):
        raise DependencyError("compiler-preprocessor-dependency-limit")
    return names


def distribution(root: Path) -> list[dict]:
    """Hash the real compiler/sysroot, not only its version-printing executable."""
    root = regular_path(root).resolve(strict=True)
    rows, total, count = [], 0, 0
    pending = [root]
    while pending:
        parent = pending.pop()
        for path in sorted(parent.iterdir()):
            count += 1
            if count > 32768:
                raise DependencyError("compiler-distribution-entry-limit")
            regular_path(path)
            if path.is_dir():
                pending.append(path)
                continue
            item = (file_identity(path, "compiler-file", 512 * 1024 * 1024) if path.stat().st_size else
                    {"digest": digest(b""), "size": 0})
            total += item["size"]
            if total > 2 * 1024**3:
                raise DependencyError("compiler-distribution-byte-limit")
            rows.append({"path": path.relative_to(root).as_posix(), "digest": item["digest"], "size": item["size"]})
    if not rows:
        raise DependencyError("compiler-distribution-empty")
    return sorted(rows, key=lambda row: row["path"])


class Isolation:
    def __init__(self, workspace: Path, tools: dict[str, Path], distributions: dict[str, Path]):
        if sys.platform != "linux" or not (sandbox := shutil.which("bwrap")) or not (loader_probe := shutil.which("ldd")):
            raise DependencyError("captured-compiler-isolation-requires-linux-bubblewrap")
        self.workspace = regular_path(workspace).resolve(strict=True)
        self.read_only_inputs: list[Path] = []
        self.child_path: Path | None = None
        self.sandbox = regular_path(Path(sandbox)).resolve(strict=True)
        self.tools = {name: regular_path(path).resolve(strict=True) for name, path in tools.items()}
        self.distributions = {name: regular_path(path).resolve(strict=True) for name, path in distributions.items()}
        self.before = {name: distribution(root) for name, root in self.distributions.items()}
        self.tool_before = {name: file_identity(path, name) for name, path in self.tools.items()}
        self.sandbox_before = file_identity(self.sandbox, "build-sandbox")
        self.shared: dict[str, dict] = {}
        probe_identity = file_identity(Path(loader_probe), "loader-dependency-observer")
        for tool in self.tools.values():
            result = run_bounded_result([loader_probe, str(tool)], self.workspace, {"PATH": os.defpath, "LC_ALL": "C"}, 10, 16384)
            text = (result.stdout + result.stderr).decode("utf-8")
            if result.returncode and "not a dynamic executable" not in text and "statically linked" not in text:
                raise DependencyError("compiler-runtime-library-observation-failed")
            if "not found" in text:
                raise DependencyError("compiler-runtime-library-missing")
            for name in re.findall(r"(?:=>\s*)?(/[^\s()]+)", text):
                if any(Path(name).resolve(strict=True).is_relative_to(root) for root in self.distributions.values()):
                    continue  # Already bound by the complete selected distribution.
                if not name.startswith(("/lib/", "/lib64/", "/usr/lib/")):
                    raise DependencyError("compiler-runtime-library-outside-system-root")
                path = Path(name).resolve(strict=True)
                self.shared[name] = file_identity(path, "compiler-host-library", 64 * 1024 * 1024)
        self.receipt = {"formatVersion": 1, "profile": "linux-captured-compiler-namespaces-v1",
            "distributions": self.before, "tools": self.tool_before, "sandbox": self.sandbox_before,
            "loaderObserver": probe_identity, "hostRuntimeLibraries": self.shared,
            "network": "denied", "ambientHome": "absent", "credentials": "not-inherited",
            "boundary": "trusted-single-user-compiler-host-not-hardened-multitenant-vm"}

    def wrap(self, tool: Path, arguments: list[str], cwd: Path, environment: dict[str, str]) -> list[str]:
        if Path(tool).resolve(strict=True) not in self.tools.values():
            raise DependencyError("compiler-executable-not-captured")
        cwd = regular_path(cwd).resolve(strict=True)
        if cwd != self.workspace and self.workspace not in cwd.parents:
            raise DependencyError("compiler-working-directory-outside-captured-workspace")
        command = [str(self.sandbox), "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
                   "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/home",
                   "--setenv", "HOME", "/home", "--setenv", "PATH", str(self.child_path) if self.child_path else "/nonexistent",
                   "--bind", str(self.workspace), str(self.workspace)]
        for root in self.distributions.values():
            command += ["--ro-bind", str(root), str(root)]
        for root in self.read_only_inputs:
            command += ["--ro-bind", str(root), str(root)]
        for selected in self.tools.values():
            if any(selected.is_relative_to(root) for root in self.distributions.values()):
                continue
            command += ["--ro-bind", str(selected), str(selected)]
        for name in self.shared:
            command += ["--ro-bind", str(Path(name).resolve(strict=True)), name]
        for key in ("LC_ALL", "LANG", "TZ", "ZIG_GLOBAL_CACHE_DIR", "ZIG_LOCAL_CACHE_DIR",
                    "CARGO_HOME", "CARGO_NET_OFFLINE", "CARGO_TARGET_DIR", "CARGO_INCREMENTAL", "CARGO_BUILD_JOBS",
                    "RUSTC", "RUSTDOC", "RUSTUP_AUTO_INSTALL", "RUSTUP_TOOLCHAIN",
                    "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER", "LSF_CAPTURED_ZIG"):
            if key in environment:
                command += ["--setenv", key, environment[key]]
        go_fixed = {"GOTOOLCHAIN": "local", "GOWORK": "off", "GOENV": "off", "CGO_ENABLED": "0",
                    "GOPROXY": "off", "GOSUMDB": "off", "GOOS": "wasip1", "GOARCH": "wasm"}
        for key, expected in go_fixed.items():
            if key in environment:
                if environment[key] != expected:
                    raise DependencyError("captured-go-compiler-policy-invalid:" + key)
                command += ["--setenv", key, expected]
        for key in ("GOROOT", "GOCACHE", "GOMODCACHE", "GOFLAGS"):
            if key in environment:
                command += ["--setenv", key, environment[key]]
        return [*command, "--chdir", str(cwd), "--", str(tool), *arguments]

    def enable_children(self, directory: Path):
        """Expose only an explicitly captured SDK executable directory."""
        directory = regular_path(directory).resolve(strict=True)
        if not any(directory.is_relative_to(root) for root in self.distributions.values()):
            raise DependencyError("compiler-child-directory-outside-captured-distribution")
        entries = [regular_path(path).resolve(strict=True) for path in directory.iterdir()]
        if not entries or any(not path.is_file() or path not in self.tools.values() for path in entries):
            raise DependencyError("compiler-child-executable-not-captured")
        self.child_path = directory
        owner = next(name for name, root in self.distributions.items() if directory.is_relative_to(root))
        self.receipt["childExecutables"] = {"distribution": owner, "directory": directory.relative_to(self.distributions[owner]).as_posix(), "tools": {
            name: self.tool_before[name] for name, path in self.tools.items() if path in entries}}

    def protect_inputs(self, *roots: Path):
        for root in roots:
            root = regular_path(root).resolve(strict=True)
            if not root.is_relative_to(self.workspace) or root == self.workspace:
                raise DependencyError("compiler-read-only-inputs-outside-owned-workspace")
            if root not in self.read_only_inputs:
                self.read_only_inputs.append(root)

    def observe_inputs(self, depfile: Path) -> list[dict]:
        rows = []
        for name in dependency_paths(read_bytes(depfile, 2 * 1024 * 1024)):
            path = Path(name)
            if not path.is_absolute():
                path = self.workspace / path
            path = regular_path(path).resolve(strict=True)
            if path.is_relative_to(self.workspace):
                owner = "captured-build-workspace"
            elif matches := [name for name, root in self.distributions.items() if path.is_relative_to(root)]:
                owner = matches[0]
            elif any(path == Path(name).resolve(strict=True) for name in self.shared):
                owner = "captured-compiler-host-library"
            else:
                raise DependencyError("compiler-preprocessor-read-outside-captured-inputs")
            item = file_identity(path, "preprocessor-input", 64 * 1024 * 1024) if path.stat().st_size else {
                "digest": digest(b""), "size": 0}
            rows.append({"path": str(path), "owner": owner, "digest": item["digest"], "size": item["size"]})
        return rows

    def check_unchanged(self):
        if self.before != {name: distribution(root) for name, root in self.distributions.items()}:
            raise DependencyError("compiler-distribution-or-sysroot-mutated")
        if self.tool_before != {name: file_identity(path, name) for name, path in self.tools.items()}:
            raise DependencyError("compiler-executable-mutated")
        if self.sandbox_before != file_identity(self.sandbox, "build-sandbox"):
            raise DependencyError("compiler-sandbox-mutated")
        for name, expected in self.shared.items():
            if file_identity(Path(name).resolve(strict=True), "compiler-host-library", 64 * 1024 * 1024) != expected:
                raise DependencyError("compiler-host-runtime-mutated")
        for row in self.receipt.get("preprocessorInputs", []):
            path = regular_path(Path(row["path"])).resolve(strict=True)
            item = file_identity(path, "preprocessor-input", 64 * 1024 * 1024) if path.stat().st_size else {
                "digest": digest(b""), "size": 0}
            if item["digest"] != row["digest"] or item["size"] != row["size"]:
                raise DependencyError("compiler-preprocessor-input-mutated")
