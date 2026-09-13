#!/usr/bin/env python3
"""Check tracked Markdown links/fences and the existing SVG contract, without builds."""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import posixpath
import re
import subprocess
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
DEFINITION = re.compile(r"^ {0,3}\[([^]\n]+)\]:\s*(.*)$")


def tracked_files(root: Path) -> set[str]:
    """Use NUL delimiters so Git quoting cannot change an exact tracked filename."""
    output = subprocess.check_output(
        ["git", "-c", "gc.auto=0", "ls-files", "-z"], cwd=root
    )
    return {name.decode("utf-8") for name in output.split(b"\0") if name}


def prose(text: str, source: str, errors: list[str]) -> str:
    """Remove fenced examples, preserving line numbers and checking fence closure."""
    output: list[str] = []
    opened: tuple[str, int, int] | None = None
    for number, line in enumerate(text.splitlines(), 1):
        # A block quote may contain a fenced example too.
        candidate = re.sub(r"^(?: {0,3}> ?)+", "", line)
        match = FENCE.match(candidate)
        if opened is not None:
            if match and match[1][0] == opened[0] and len(match[1]) >= opened[1] and not match[2].strip():
                opened = None
            output.append("")
        elif match and not (match[1][0] == "`" and "`" in match[2]):
            opened = (match[1][0], len(match[1]), number)
            output.append("")
        else:
            output.append(line)
    if opened is not None:
        errors.append(f"{source}:{opened[2]}: unclosed {opened[0] * opened[1]} fence")
    return re.sub(r"<!--.*?-->", "", "\n".join(output), flags=re.S)


def without_code(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return " " * len(match[0])

    return re.sub(r"(?<!`)(`+)(?!`)(.*?)\1(?!`)", replace, text, flags=re.S)


def destination(text: str, start: int) -> tuple[str, int] | None:
    """Read a CommonMark-style destination, including balanced URL parentheses."""
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    if index == len(text):
        return None
    if text[index] == "<":
        end = text.find(">", index + 1)
        if end < 0 or "\n" in text[index:end]:
            return None
        return text[index + 1:end], end + 1
    first = index
    depth = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            index += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
        elif char.isspace() and depth == 0:
            break
        index += 1
    return (text[first:index], index) if depth == 0 else None


def reference_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def links(text: str) -> Iterable[str]:
    text = without_code(text)
    definitions: dict[str, str] = {}
    lines = text.splitlines()
    for number, line in enumerate(lines):
        match = DEFINITION.match(line)
        if match and (found := destination(match[2], 0)) is not None:
            definitions.setdefault(reference_key(match[1]), found[0])
            lines[number] = ""
    text = "\n".join(lines)
    # A bracket stack preserves both destinations in a linked image. Consuming
    # reference labels also avoids counting [text][reference] twice.
    stack: list[int] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            stack.append(index)
        if char != "]" or not stack:
            index += 1
            continue
        label = text[stack.pop() + 1:index]
        end = index + 1
        if end < len(text) and text[end] == "(":
            found = destination(text, end + 1)
            if found is not None:
                target, tail = found
                remainder = text[tail:]
                closed = re.match(r"\s*(?:\"[^\"\n]*\"|'[^'\n]*'|\([^\n)]*\))?\s*\)", remainder)
                if closed:
                    yield target
                    index = tail + closed.end()
                    continue
        elif end < len(text) and text[end] == "[":
            close = text.find("]", end + 1)
            if close >= 0:
                key = reference_key(text[end + 1:close] or label)
                if key in definitions:
                    yield definitions[key]
                index = close + 1
                continue
        elif reference_key(label) in definitions:
            yield definitions[reference_key(label)]
        index = end


def heading_anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    used: set[str] = set()
    counts: dict[str, int] = {}
    previous = ""
    for line in text.splitlines():
        match = re.match(r"^ {0,3}#{1,6}(?:\s+|$)(.*)$", line)
        heading = None
        if match:
            heading = re.sub(r"\s+#+\s*$", "", match[1]).strip()
        elif previous.strip() and re.fullmatch(r" {0,3}(?:=+|-+)\s*", line):
            heading = previous.strip()
        if heading is not None:
            heading = re.sub(r"!?\[([^]]*)\]\([^)]*\)", r"\1", heading)
            heading = html.unescape(re.sub(r"<[^>]+>", "", heading)).lower()
            base = "".join(
                char for char in heading
                if char.isalnum() or char in "-_ " or unicodedata.category(char).startswith("M")
            ).replace(" ", "-")
            slug = base
            while slug in used:
                counts[base] = counts.get(base, 0) + 1
                slug = f"{base}-{counts[base]}"
            used.add(slug)
            anchors.add(slug)
        previous = line
    for tag in re.findall(r"<[^>]+>", without_code(text)):
        anchors.update(html.unescape(value) for value in re.findall(r"\b(?:id|name)\s*=\s*['\"]([^'\"]+)['\"]", tag))
    return anchors


def ordinary_path(root: Path, relative: str) -> bool:
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            return False
    return current.exists()


def svg_errors(root: Path, paths: list[Path], require_documents: bool = False) -> list[str]:
    # A private module instance reuses the authoritative SVG rules while replacing
    # only file enumeration. It neither walks untracked outputs nor reads JSON.
    spec = importlib.util.spec_from_file_location(
        "_docs_svg_rules", Path(__file__).with_name("validate_repository.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.files_with_suffix = lambda suffix, root: iter(paths)
    module.validate_svg(root)
    if require_documents:
        module.ROOT = root
        module.validate_required_docs()
    return list(module.ERRORS)


def validate_docs(root: Path = ROOT, tracked_paths: Iterable[str] | None = None,
                  *, require_documents: bool = True) -> dict:
    root = root.resolve()
    tracked = set(tracked_paths) if tracked_paths is not None else tracked_files(root)
    errors: list[str] = []
    directories = {"."}
    for path in tracked:
        parent = posixpath.dirname(path)
        while parent:
            directories.add(parent)
            parent = posixpath.dirname(parent)
    documents: dict[str, str] = {}
    svgs: list[Path] = []
    for name in sorted(tracked):
        if Path(name).suffix.lower() not in {".md", ".svg"}:
            continue
        path = root / name
        if not ordinary_path(root, name) or not path.is_file():
            errors.append(f"{name}: tracked document is missing or crosses a symlink")
            continue
        if path.suffix.lower() == ".svg":
            svgs.append(path)
        else:
            try:
                content = path.read_text(encoding="utf-8")
                if not content.strip():
                    errors.append(f"{name}: empty Markdown document")
                documents[name] = prose(content, name, errors)
            except (OSError, UnicodeError) as exc:
                errors.append(f"{name}: cannot read UTF-8 Markdown: {type(exc).__name__}")
    anchors = {name: heading_anchors(text) for name, text in documents.items()}
    local_targets = tracked | directories
    checked_links = checked_anchors = 0
    for source, text in documents.items():
        for raw in links(text):
            raw = html.unescape(re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]^_`{|}~])", r"\1", raw))
            try:
                parsed = urllib.parse.urlsplit(raw)
                if parsed.scheme or parsed.netloc:
                    continue
                if re.search(r"%(?![0-9a-fA-F]{2})", raw):
                    raise ValueError("invalid percent encoding")
                path = urllib.parse.unquote(parsed.path, errors="strict")
                fragment = urllib.parse.unquote(parsed.fragment, errors="strict")
                if "\\" in path or "\0" in path or path.startswith("/"):
                    raise ValueError("non-portable local path")
            except (ValueError, UnicodeError):
                errors.append(f"{source}: invalid local URL {raw!r}")
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(source), path)) if path else source
            checked_links += 1
            if target not in local_targets or not ordinary_path(root, target):
                errors.append(f"{source}: missing or case-wrong local target {raw!r} ({target})")
                continue
            if fragment and target in anchors:
                checked_anchors += 1
                if fragment not in anchors[target]:
                    errors.append(f"{source}: missing anchor {raw!r} ({target})")
            elif fragment and target.lower().endswith(".svg"):
                try:
                    ids = {node.get("id") for node in ET.parse(root / target).iter()}
                    checked_anchors += 1
                    if fragment not in ids:
                        errors.append(f"{source}: missing SVG anchor {raw!r}")
                except (OSError, ET.ParseError):
                    pass  # The shared SVG validator reports the parse failure.
    errors.extend(svg_errors(root, svgs, require_documents))
    return {"documents": len(documents), "svgs": len(svgs), "local_links": checked_links,
            "anchors": checked_anchors, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        report = validate_docs(args.root)
    except (OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: cannot enumerate documentation: {type(exc).__name__}")
        return 1
    print(json.dumps(report, indent=2))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
