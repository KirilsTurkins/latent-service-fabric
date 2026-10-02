"""Identify scheduling-checkpoint classes from captured bytecode/source ownership.

No application class is loaded or initialized in the compiler host. The index
is an SDK compiler input and its exact bytes are retained with the recipe.
"""
from __future__ import annotations

from pathlib import Path
import zipfile


def source_file(data: bytes) -> str | None:
    if not 10 <= len(data) <= 16 * 1024 * 1024 or data[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("invalid-java-class-origin")
    cursor = 8

    def number(width: int) -> int:
        nonlocal cursor
        if width > len(data) - cursor: raise ValueError("truncated-java-class-origin")
        value = int.from_bytes(data[cursor:cursor + width], "big")
        cursor += width
        return value

    def skip(size: int) -> None:
        nonlocal cursor
        if size > len(data) - cursor: raise ValueError("truncated-java-class-origin")
        cursor += size

    strings, index, count = {}, 1, number(2)
    while index < count:
        tag = number(1)
        if tag == 1:
            length = number(2)
            if length > len(data) - cursor: raise ValueError("truncated-java-class-origin")
            strings[index] = data[cursor:cursor + length]
            skip(length)
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18): skip(4)
        elif tag in (5, 6): skip(8); index += 1
        elif tag in (7, 8, 16, 19, 20): skip(2)
        elif tag == 15: skip(3)
        else: raise ValueError("invalid-java-class-origin-tag")
        index += 1
    skip(6)
    skip(number(2) * 2)
    for _kind in range(2):
        for _member in range(number(2)):
            skip(6)
            for _attribute in range(number(2)):
                skip(2); skip(number(4))
    source = None
    for _attribute in range(number(2)):
        name, length = strings.get(number(2)), number(4)
        if name == b"SourceFile":
            if source is not None or length != 2: raise ValueError("invalid-java-class-origin-source")
            raw = strings.get(number(2))
            source = (raw.replace(b"\xc0\x80", b"\0").decode("utf-8", "surrogatepass")
                      .encode("utf-16", "surrogatepass").decode("utf-16")) if raw else None
            if not source or "/" in source or "\\" in source: raise ValueError("invalid-java-class-origin-source")
        else: skip(length)
    if cursor != len(data): raise ValueError("invalid-java-class-origin-tail")
    return source


def checkpoint_index(classes: Path, application_sources: set[str], application_classpath: tuple[Path, ...]) -> bytes:
    selected = set()
    for path in sorted(classes.rglob("*.class")):
        logical = path.relative_to(classes)
        source = source_file(path.read_bytes())
        if source is not None and (logical.parent / source).as_posix() in application_sources:
            selected.add(logical.with_suffix("").as_posix().replace("/", "."))
    for jar in application_classpath:
        with zipfile.ZipFile(jar) as archive:
            for name in archive.namelist():
                if name.endswith(".class") and not name.startswith("META-INF/"):
                    if name.startswith("/") or ".." in name.split("/"):
                        raise ValueError("invalid-java-class-origin-path")
                    selected.add(name[:-6].replace("/", "."))
    if not selected or len(selected) > 65536: raise ValueError("unresolved-java-class-origin")
    return ("\n".join(sorted(selected)) + "\n").encode("utf-8")
