"""Compile verified immutable bytes into a narrow standard ClassLoader port."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import stat

from tools import guest_resources
from tools.application_dependency_store import regular_path, read_bytes
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import inventory, read_file, snapshot

PROFILE = "java-immutable-classloader-v1"
CLASSLIB = {"path": "org/teavm/teavm-classlib/0.15.0/teavm-classlib-0.15.0.jar",
            "sha256": "7d805be4670a892a34c89d9d750a8afd65e2f8201b7b3a10343634ea19d1c410",
            "size": 17718996, "platform": "any"}
METHOD = "java.lang.ClassLoader.getResourceAsStream(Ljava/lang/String;)Ljava/io/InputStream;"
PACKAGE = "dev.latent.guest.resources"
CHUNK = 4096
PART_CHUNKS = 8


def source_inputs(directory: Path) -> dict[str, bytes]:
    """Read every declared lookup name, including target and dot directories.

    General project snapshots deliberately exclude those directories and have
    different filename rules; they cannot implement classpath lookup capture.
    """
    directory = regular_path(directory)
    if not directory.is_dir():
        raise ValueError("Java immutable resource directory missing")
    pending, files, spellings, leaves = [directory], {}, {}, set()
    visited = total = 0
    while pending:
        for path in sorted(pending.pop().iterdir()):
            regular_path(path)
            visited += 1
            if visited > guest_resources.MAX_COUNT * 17:
                raise ValueError("Java immutable resource entry limit")
            logical = path.relative_to(directory).as_posix()
            guest_resources.name(logical)
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                pending.append(path)
                continue
            guest_resources.register(logical, spellings, leaves)
            data = read_bytes(path, guest_resources.MAX_FILE)
            total += len(data)
            if len(files) >= guest_resources.MAX_COUNT or total > guest_resources.MAX_TOTAL:
                raise ValueError("Java immutable resource byte or count limit")
            files[logical] = data
    return dict(sorted(files.items()))


def materialize(files: dict[str, bytes], source: bytes, additional_resources, directory: Path) -> Path | None:
    # The common assembler verifies exact application/dependency ownership,
    # logical aliases and finite byte/count limits before any compiler reads.
    # This private preparation index is not published as component evidence;
    # package_inputs later assembles the signed index with the real component.
    selected = guest_resources.capture(files, b"", source, additional_resources=additional_resources)
    if selected is None:
        return None
    directory.mkdir()
    for row in selected.index["resources"]:
        target = directory / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(selected.objects[row["object"]])
    expected = {row["path"]: selected.objects[row["object"]] for row in selected.index["resources"]}
    if source_inputs(directory) != expected:
        raise ValueError("Java immutable resource selection changed")
    return directory


def generated_sources(files: dict[str, bytes]) -> dict[str, bytes]:
    """Bounded literal Java; each open creates its own byte array and stream."""
    sources = {}
    cases = []
    for number, (name, data) in enumerate(sorted(files.items())):
        encoded = base64.b64encode(data).decode("ascii")
        chunks = [encoded[index:index + CHUNK] for index in range(0, len(encoded), CHUNK)]
        data_class = f"Data{number:04d}"
        calls = []
        for part, offset in enumerate(range(0, len(chunks), PART_CHUNKS)):
            part_class = data_class + f"Part{part:04d}"
            body = "\n".join("        value.append(" + json.dumps(chunk) + ");"
                             for chunk in chunks[offset:offset + PART_CHUNKS])
            sources[part_class + ".java"] = (f"package {PACKAGE};\n"
                f"final class {part_class} {{\n    private {part_class}() {{}}\n"
                f"    static void append(StringBuilder value) {{\n{body}\n    }}\n}}\n").encode()
            calls.append(f"        {part_class}.append(value);")
        sources[data_class + ".java"] = (f"package {PACKAGE};\n"
            f"final class {data_class} {{\n    private {data_class}() {{}}\n"
            "    static java.io.InputStream open() {\n"
            f"        StringBuilder value = new StringBuilder({len(encoded)});\n" + "\n".join(calls) + "\n"
            "        return new java.io.ByteArrayInputStream(java.util.Base64.getDecoder().decode(value.toString()));\n"
            "    }\n}\n").encode()
        cases.append("            case " + json.dumps(name, ensure_ascii=True) + f": return {data_class}.open();")
    sources["ImmutableResources.java"] = (f"package {PACKAGE};\n"
        "public final class ImmutableResources {\n    private ImmutableResources() {}\n"
        "    public static java.io.InputStream open(String name) {\n"
        "        java.util.Objects.requireNonNull(name);\n        switch (name) {\n" + "\n".join(cases) + "\n"
        "            default: return null;\n        }\n    }\n}\n").encode()
    return dict(sorted(sources.items()))


def stage(sdk: Path, resource_directory: Path, project: Path) -> dict:
    lock = json.loads(read_file(sdk / "feasibility/dependencies.lock.json"))
    if [row for row in lock.get("artifacts", []) if row.get("path") == CLASSLIB["path"]] != [CLASSLIB]:
        raise ValueError("Java immutable resource classlib preimage changed")
    files = source_inputs(resource_directory)
    generated = generated_sources(files)
    java_root = project / "src/main/java"
    sdk_sources = snapshot(sdk / "resources/compiler")
    if not sdk_sources:
        raise ValueError("Java immutable resource compiler port missing from captured SDK")
    source_files = {**sdk_sources, **{PACKAGE.replace(".", "/") + "/" + name: data
                                    for name, data in generated.items()}}
    if len(source_files) != len(sdk_sources) + len(generated):
        raise ValueError("Java immutable resource SDK source collision")
    for name, data in source_files.items():
        target = java_root / name
        if target.exists():
            raise ValueError("Java immutable resource source collision")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    service = project / "src/main/resources/META-INF/services/org.teavm.vm.spi.TeaVMPlugin"
    from tools.java_guest.compiler import stage_sdk_service
    stage_sdk_service(service, "META-INF/services/org.teavm.vm.spi.TeaVMPlugin",
                      read_file(sdk / "resources/services/META-INF/services/org.teavm.vm.spi.TeaVMPlugin"))
    with (project / "build.gradle").open("a", encoding="utf-8") as build:
        build.write("\ndependencies { compileOnly 'org.teavm:teavm-core:0.15.0' }\n")
    identity = {"profile": PROFILE, "lookup": "exact-case-sensitive-no-ambient-fallback",
        "streamOwnership": "fresh-decoded-byte-array-per-open", "classlibPreimage": CLASSLIB,
        "method": METHOD, "resourceInputs": json.loads(inventory(files)),
        "generatedSources": json.loads(inventory(generated)),
        "compilerPortSources": json.loads(inventory(sdk_sources))}
    return {**identity, "identity": digest(canonical(identity))}


def recheck(resource_directory: Path, receipt: dict) -> None:
    if json.loads(inventory(source_inputs(resource_directory))) != receipt["resourceInputs"]:
        raise ValueError("Java immutable resource compiler inputs changed")
