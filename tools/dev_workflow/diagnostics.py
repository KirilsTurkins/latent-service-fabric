"""Bounded compiler locations mapped only to explicitly captured source files."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from . import paths
from .common import integer, members, require

MAX_DIAGNOSTICS = 32
BUILD_START = "LSF build-start"
BUILD_END = "LSF build-end"
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
COLON = re.compile(r"^(.*?):([0-9]+)(?::([0-9]+))?:\s*(?:(error|warning|note|fatal error)(?:\s+([A-Za-z0-9_-]+))?:\s*)?(.*)$")
PARENS = re.compile(r"^(.*?)\(([0-9]+),([0-9]+)\):\s*(error|warning)\s*([A-Za-z0-9_-]*):\s*(.*)$")


def clean(value: str) -> str:
    return "".join(" " if ord(character) < 32 or ord(character) == 127 else character
                   for character in ANSI.sub("", value))[:1024]


def validate(values: list) -> list:
    require(isinstance(values, list) and len(values) <= MAX_DIAGNOSTICS, "compiler-diagnostic-count")
    for value in values:
        members(value, {"path", "line", "column", "severity", "code", "message"})
        paths.relative(value["path"])
        for name in ("line", "column"):
            integer(value[name], 1, 10000000)
        require(value["severity"] in {"error", "warning", "note"}, "compiler-diagnostic-severity")
        require(isinstance(value["code"], str) and re.fullmatch(r"[A-Za-z0-9_-]{0,80}", value["code"]), "compiler-diagnostic-code")
        require(isinstance(value["message"], str) and value["message"] == clean(value["message"]), "compiler-diagnostic-message")
    return values


def collect(stdout: bytes, stderr: bytes, source: Path, working: Path, inputs: set[str]) -> list:
    result, seen = [], set()
    aliases = {paths.alias(name): name for name in inputs}

    def add(name, line, column, severity, code, message):
        if len(result) >= MAX_DIAGNOSTICS or not isinstance(name, str) or not isinstance(message, str):
            return
        candidate = Path(name)
        if not candidate.is_absolute():
            candidate = working / candidate
        candidate = Path(os.path.normpath(candidate))
        if not candidate.is_relative_to(source):
            return
        relative = aliases.get(paths.alias(candidate.relative_to(source).as_posix()))
        if relative is None or type(line) is not int or type(column) is not int or not (1 <= line <= 10000000 and 1 <= column <= 10000000):
            return
        diagnostic = {"path": relative, "line": line, "column": column, "severity": "error" if severity == "fatal error" else severity,
                      "code": code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_-]{0,80}", code) else "",
                      "message": clean(message)}
        if diagnostic["severity"] not in {"error", "warning", "note"}:
            diagnostic["severity"] = "error"
        key = tuple(diagnostic.values())
        if key not in seen:
            seen.add(key)
            result.append(diagnostic)

    for raw in (stderr, stdout):
        for line in raw.decode("utf-8", errors="replace").splitlines()[:4096]:
            if len(line) > 16384:
                continue
            if line.startswith("{"):
                try:
                    document = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if not isinstance(document, dict):
                    continue
                diagnostic = document.get("message", {}) if document.get("reason") == "compiler-message" else document
                if not isinstance(diagnostic, dict) or not isinstance(diagnostic.get("spans"), list):
                    continue
                code = diagnostic.get("code") or {}
                for span in diagnostic["spans"][:32]:
                    if isinstance(span, dict) and span.get("is_primary") is True:
                        add(span.get("file_name"), span.get("line_start"), span.get("column_start"),
                            diagnostic.get("level"), code.get("code") if isinstance(code, dict) else "", diagnostic.get("message"))
                continue
            match = PARENS.fullmatch(ANSI.sub("", line)) or COLON.fullmatch(ANSI.sub("", line))
            if match:
                name, row, column, level, code, message = match.groups()
                add(name, int(row), int(column or "1"), level or "error", code or "", message)
    return validate(result)


def for_host(values: list, source: Path) -> list:
    return [{**value, "hostPath": str(source / value["path"])} for value in validate(values)]


def editor_lines(values: list) -> list[str]:
    result = []
    for value in values:
        record = {key: entry for key, entry in value.items() if key != "hostPath"}
        validate([record])
        path = value.get("hostPath")
        require(isinstance(path, str) and all(ord(character) >= 32 for character in path), "editor-diagnostic-path")
        severity = "info" if value["severity"] == "note" else value["severity"]
        result.append(f"LSF {path}:{value['line']}:{value['column']}: {severity} {value['code']}: {value['message']}")
    return result
