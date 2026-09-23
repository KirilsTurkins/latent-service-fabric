"""Authoritative WIT generation and deterministic C spelling compatibility."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Callable

from tools.stage_runtime_wit import stage


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def regular_tree(source: Path, suffix: str, maximum: int = 256) -> list[Path]:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("C WIT source must be a real directory")
    paths = sorted(source.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("C source trees cannot contain symlinks")
    files = [path for path in paths if path.is_file() and path.suffix == suffix]
    if not files or len(files) > maximum or any(path.stat().st_size > 262144 for path in files):
        raise ValueError("C WIT source inventory exceeds its bound or is empty")
    if sum(path.stat().st_size for path in files) > 4 * 1024 * 1024:
        raise ValueError("C WIT source bytes exceed their bound")
    return files


def aliases(header: str) -> str:
    """Alias exact current-version C spellings; never rewrite WIT identities.

    wit-bindgen version-qualifies a namespace when multiple versions of its
    package are present (notably buffered and streaming HTTP). Every alias is
    derived from the generated header; absent APIs are never synthesized.
    """
    tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", header))
    replacements = (("latent_http_0_2_0_client_", "latent_http_client_"),
                    ("latent_http_0_3_0_streaming_", "latent_http_streaming_"),
                    ("latent_blob_0_2_0_blob_", "latent_blob_blob_"))
    mapping = {}
    for old, new in (*replacements, *((a.upper(), b.upper()) for a, b in replacements)):
        for token in sorted(tokens):
            if token.startswith(old):
                alias = new + token[len(old):]
                if alias in tokens or (alias in mapping and mapping[alias] != token):
                    raise ValueError("ambiguous current C capability namespace")
                mapping[alias] = token
    return ("/* Generated from probe.h; do not edit. */\n#ifndef LSF_PROBE_ALIASES_H\n"
            "#define LSF_PROBE_ALIASES_H\n#include \"probe.h\"\n" +
            "".join(f"#define {name} {value}\n" for name, value in sorted(mapping.items())) + "#endif\n")


def generate(run: Callable[..., str], source: Path, world: str, destination: Path) -> tuple[Path, dict]:
    regular_tree(source, ".wit")
    destination.mkdir(parents=True, exist_ok=False)
    staged, generated = destination / "wit", destination / "bindings"
    stage(staged, source)
    generated.mkdir()
    run("wit-bindgen", "c", str(staged), "--world", world,
        "--rename-world", "probe", "--out-dir", str(generated))
    names = {path.name for path in generated.iterdir()}
    if names != {"probe.h", "probe.c", "probe_component_type.o"}:
        raise ValueError("unexpected generated C binding outputs")
    (generated / "probe_aliases.h").write_text(aliases((generated / "probe.h").read_text()), encoding="utf-8")
    names.add("probe_aliases.h")
    lock = {"formatVersion": 1, "world": world,
            "generator": run("wit-bindgen", "--version").strip(),
            "outputs": {name: digest((generated / name).read_bytes()) for name in sorted(names)}}
    return generated, lock


def check_lock(path: Path, actual: dict, *, update: bool = False) -> None:
    if path.is_symlink():
        raise ValueError("C bindings lock cannot be a symlink")
    if update:
        path.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif not path.is_file() or path.stat().st_size > 262144 or json.loads(path.read_text()) != actual:
        raise ValueError("C binding drift: inspect and explicitly update the binding lock")
