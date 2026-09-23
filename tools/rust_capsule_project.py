"""Standalone Rust project creation from the maintained SDK and canonical examples.

No subprocesses, keys, grants, runtime changes or unpinned package resolution.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib

ROOT = Path(__file__).resolve().parents[1]
TUTORIALS = ("greeting", "word-count", "shipping")
TEMPLATES = (*TUTORIALS, "http-status", "recovery")
MAX_FILES = 4096
MAX_FILE = 4 * 1024 * 1024
MAX_SOURCE = 32 * 1024 * 1024
SDK_DIRECTORIES = ("sdk/rust-guest", "crates/latent-component-bindings",
                   "wit/platform", "examples/echo-contract/wit")


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def write_json(path: Path, value: object) -> None:
    with path.open("xb") as output:
        output.write(json.dumps(value, indent=2, ensure_ascii=False).encode() + b"\n")


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def decode_json(data: bytes):
    depth, quoted, escaped = 0, False, False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 64:
                raise ValueError("JSON nesting limit exceeded")
        elif byte in (93, 125):
            depth -= 1
    def nonfinite(_value):
        raise ValueError("non-finite JSON number")
    try:
        return json.loads(data, object_pairs_hook=object_pairs, parse_constant=nonfinite)
    except (RecursionError, UnicodeError) as error:
        raise ValueError("invalid or overly nested JSON document") from error


def read_json(path: Path, maximum: int = MAX_FILE):
    return decode_json(read_file(path, maximum))


def read_file(path: Path, maximum: int = MAX_FILE) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise ValueError("source must be a bounded regular file")
    # O_NOFOLLOW closes the final-segment link race. Parent directories are
    # caller-owned; this is not a hostile-filesystem or trusted-build sandbox.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        data = source.read(maximum + 1)
        after = os.fstat(source.fileno())
    if (len(data) > maximum or len(data) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ValueError("source changed during capture")
    return data


def checked_path(path: Path) -> Path:
    path = path.absolute()
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise ValueError("symlink paths are not supported")
    return path.resolve(strict=False)


def snapshot(root: Path) -> dict[str, bytes]:
    root = checked_path(root)
    if not root.is_dir():
        raise ValueError("project directory does not exist")
    files, total, visited = {}, 0, 0
    pending = [root]
    while pending:
        parent = pending.pop()
        for path in sorted(parent.iterdir()):
            if parent == root and path.name in {".git", "target"}:
                continue
            visited += 1
            if visited > MAX_FILES:
                raise ValueError("project entry limit exceeded")
            relative = path.relative_to(root).as_posix()
            if any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) or part in {".", ".."}
                   for part in Path(relative).parts):
                raise ValueError("nonportable project path")
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                pending.append(path)
                continue
            data = read_file(path)
            total += len(data)
            if total > MAX_SOURCE:
                raise ValueError("project source byte limit exceeded")
            files[relative] = data
    return dict(sorted(files.items()))


def inventory(files: dict[str, bytes]) -> bytes:
    return canonical({path: {"digest": digest(data), "size": len(data)}
                      for path, data in sorted(files.items())})


def fresh(directory: Path) -> Path:
    directory = checked_path(directory)
    if directory.exists():
        raise ValueError("choose a fresh output directory")
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(mode=0o700)
    return directory


def locked_dependencies(name: str) -> bytes:
    """Use a reviewed Cargo-generated lock, allowing only the root name to vary."""
    raw = (ROOT / "tools/rust_capsule.lock").read_text()
    reviewed = tomllib.loads(raw)
    authoritative = tomllib.loads((ROOT / "Cargo.lock").read_text())
    packages = {(p["name"], p["version"], p.get("source")): p
                for p in authoritative["package"]}
    template = "latent-capsule-template"
    for package in reviewed["package"]:
        if package["name"] == template:
            continue
        if package["name"] == name:
            raise ValueError("project name collides with a dependency")
        original = packages.get((package["name"], package["version"], package.get("source")))
        if original is None or original.get("checksum") != package.get("checksum"):
            raise ValueError("standalone lock drift: regenerate and review tools/rust_capsule.lock")
    needle = f'name = "{template}"'
    if raw.count(needle) != 1:
        raise ValueError("standalone lock must contain one template root")
    return raw.replace(needle, f'name = "{name}"').encode()


def sdk_files() -> dict[str, bytes]:
    files = {}
    for directory in SDK_DIRECTORIES:
        files.update({directory + "/" + path: data for path, data in snapshot(ROOT / directory).items()})
    root = tomllib.loads((ROOT / "Cargo.toml").read_text())
    original = (ROOT / "Cargo.toml").read_text()
    # Keep the authoritative inheritance tables byte-for-byte. Only workspace
    # membership changes in this isolated, vendored SDK workspace.
    tables = original[original.index("[workspace.package]"):]
    files["Cargo.toml"] = ("[workspace]\nresolver = \"2\"\nmembers = [\"sdk/rust-guest\", \"crates/latent-component-bindings\"]\n\n" + tables).encode()
    for name in ("rust-toolchain.toml", "LICENSE", "NOTICE"):
        files[name] = read_file(ROOT / name)
    if not root["workspace"]["dependencies"]["wit-bindgen"].startswith("="):
        raise ValueError("binding generator must be exactly pinned")
    return files


def create(directory: Path, template: str, name: str | None = None) -> Path:
    if template not in TEMPLATES:
        raise ValueError("unknown capsule template")
    name = name or "my-" + template
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("use a lowercase kebab-case Cargo package name, at most 64 bytes")
    pins = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
    if template in TUTORIALS:
        source = ROOT / "tools/toolchain-smoke/examples" / ("tutorial_" + template.replace("-", "_"))
        code = read_file(source / "component.rs").decode()
        old = f'path: "examples/tutorial_{template.replace("-", "_")}"'
        if code.count(old) != 1:
            raise ValueError("canonical tutorial binding location changed")
        code = code.replace(old, 'path: "wit"')
    else:
        source = ROOT / "examples/rust-capsules" / template
        code = read_file(source / "component.rs").decode()
    wit = read_file(source / "world.wit")
    vendor = sdk_files()
    files = {"src/lib.rs": code.encode(), "wit/world.wit": wit,
             "Cargo.lock": locked_dependencies(name),
             "rust-toolchain.toml": read_file(ROOT / "rust-toolchain.toml"),
             ".gitignore": b"/target/\n",
             "README.md": (f"# {name}\n\nEdit `src/lib.rs` and `wit/world.wit`; keep `vendor/lsf` unchanged.\n"
                           "Build with the LSF Rust capsule authoring command described in\n"
                           "`docs/component-development/rust-authoring.md` in the SDK checkout.\n"
                           "No provider or capability grant is installed by this project.\n").encode()}
    files.update({"vendor/lsf/" + path: data for path, data in vendor.items()})
    files["Cargo.toml"] = f'''[package]
name = "{name}"
version = "1.0.0"
edition = "2021"
rust-version = "{pins['rust']['msrv']}"
license = "Apache-2.0"
publish = false

[workspace]

[lib]
crate-type = ["cdylib"]

[target.'cfg(target_arch = "wasm32")'.dependencies]
wit-bindgen = "={pins['rust']['dependencies']['wit-bindgen']}"
latent-guest = {{ path = "vendor/lsf/sdk/rust-guest" }}

[profile.release]
opt-level = "s"
lto = true
codegen-units = 1
panic = "abort"
'''.encode()
    # Cargo includes in-tree path dependencies in the author workspace. Keep
    # their inherited metadata/dependency/lint tables identical to the SDK.
    files["Cargo.toml"] += b"\n[workspace.package]" + vendor["Cargo.toml"].split(b"[workspace.package]", 1)[1]
    if template == "http-status":
        files["wit/deps/http/package.wit"] = read_file(ROOT / "wit/platform/http-v2/package.wit")
    limits = json.loads((ROOT / "examples/echo-contract/capsule.json").read_text())["execution"]["limits"]
    limits.update(cpuFuel=100_000_000, memoryBytes=4_194_304, wallTimeLimitMillis=1000, logBytes=0)
    if template == "http-status":
        limits.update(outboundRequests=1, memoryBytes=16_777_216, cpuFuel=1_000_000_000, wallTimeLimitMillis=5000)
    project = {"formatVersion": 1, "name": name, "version": "1.0.0", "tenant": "examples",
               "service": "examples/" + name, "world": f"examples:{template}/service@1.0.0",
               "limits": limits}
    files["capsule-project.json"] = json.dumps(project, indent=2).encode() + b"\n"
    pin = {"formatVersion": 1, "toolchain": pins,
           "sdk": json.loads(inventory(vendor)),
           "bindings": read_json(ROOT / "tools/guest_bindings.lock.json"),
           "template": {"name": template, "source": source.relative_to(ROOT).as_posix(),
                        "componentDigest": digest(read_file(source / "component.rs")), "witDigest": digest(wit)}}
    files["sdk-lock.json"] = json.dumps(pin, indent=2).encode() + b"\n"
    directory = fresh(directory)
    for path, data in sorted(files.items()):
        output = directory / path
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(data)
    return directory
