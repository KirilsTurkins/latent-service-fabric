"""Review tripwire for the one audited native-loader exception.

Rust's deny/forbid lints enforce unsafe-code policy. This source guard also makes
changes to the reviewed exception and its dependency pin explicit in CI; it is
not a Rust parser or a substitute for reviewing provenance and owner lifetimes.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

CRATE = "crates/latent-wasmtime"
LOADER = f"{CRATE}/src/aot/loader.rs"
ALLOW = '''#[allow(
    unsafe_code,
    reason = "the sole native loader accepts only a private proof over authenticated immutable bytes"
)]'''
FUNCTION = '''fn deserialize_authenticated(
    engine: &Engine,
    proof: &AuthenticatedNative<'_>,
) -> Result<Component, PlatformError> {
    unsafe { Component::deserialize(engine, proof.bytes()) }.map_err(|_| load_failed())
}'''


def compact(text: str) -> str:
    # The allowlisted function has no strings or block comments. Requiring this
    # exact shape is deliberately stricter than accepting arbitrary Rust syntax.
    return re.sub(r"\s+", "", re.sub(r"(?m)//[^\n]*", "", text))


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    workspace = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]
    if workspace["lints"]["rust"].get("unsafe_code") != "forbid":
        errors.append("workspace unsafe_code must remain forbid")
    engine = workspace["dependencies"]["wasmtime"]
    if engine.get("version") != "=47.0.3" or engine.get("default-features") is not False:
        errors.append("native loader requires review of the pinned Wasmtime engine")
    if "parallel-compilation" in engine.get("features", []):
        errors.append("isolated compiler must not enable parallel-compilation")
    for member in workspace["members"]:
        manifest = tomllib.loads((root / member / "Cargo.toml").read_text(encoding="utf-8"))
        lints = manifest.get("lints", {})
        if member == CRATE:
            if lints != {"rust": {"unsafe_code": "deny"}, "clippy": workspace["lints"]["clippy"]}:
                errors.append("Wasmtime must preserve all workspace lints except its audited deny")
        elif member == "tools/toolchain-smoke":
            # Existing generated wasm export probes do not inherit workspace
            # lints; this change must not introduce a second native exception.
            if lints:
                errors.append("toolchain probe lint policy changed; review separately")
        elif lints != {"workspace": True}:
            errors.append(f"{member} must inherit workspace unsafe-code prohibition")
    if "#![deny(unsafe_code)]" not in (root / CRATE / "src/lib.rs").read_text(encoding="utf-8"):
        errors.append("Wasmtime crate must deny unsafe code outside the audited function")
    loader = (root / LOADER).read_text(encoding="utf-8")
    if loader.count(ALLOW) != 1:
        errors.append("native loader must have exactly its reviewed unsafe allowance")
    start = loader.find("fn deserialize_authenticated(")
    end = loader.find("\nfn load_failed()", start)
    if start < 0 or end < 0 or compact(loader[start:end]) != compact(FUNCTION):
        errors.append("audited deserialize function changed; review its proof and copied-load safety")
    if start >= 0 and not loader[:start].rstrip().endswith(ALLOW):
        errors.append("unsafe allowance must apply only to the private deserialize function")
    unsafe = re.compile(r"\bunsafe\s*(?:\{|fn\b|impl\b|trait\b|extern\b)")
    lowered = re.compile(r"#\s*!?\s*\[\s*(?:allow|expect)\s*\([^]]*\bunsafe_code\b", re.S)
    for path in (root / CRATE).rglob("*.rs"):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        if relative == LOADER:
            source = source.replace(ALLOW, "", 1)
            if start >= 0 and end >= 0:
                source = source.replace(loader[start:end], "", 1)
        if unsafe.search(source) or lowered.search(source):
            errors.append(f"unreviewed unsafe code or allowance in {relative}")
    return errors
