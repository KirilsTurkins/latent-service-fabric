"""Embed the bounded captured selection for ordinary Assembly resource lookup."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

from tools import guest_resources
from tools.dev_workflow.common import digest, encode
from tools.rust_capsule_project import read_file, snapshot

PROFILE = "lsf.dotnet.embedded-resources.v1"


def msbuild_literal(value: str) -> str:
    # XML escaping alone does not stop MSBuild property/item expansion. Keep
    # each logical name literal through evaluation and item-list processing.
    # https://learn.microsoft.com/visualstudio/msbuild/special-characters-to-escape
    return "".join("%%%02X" % ord(character) if character in "%$@();'*?" else character
                   for character in value)


@dataclass(frozen=True)
class EmbeddedResources:
    observation: dict
    project: Path
    project_bytes: bytes
    objects: dict[str, bytes]

    def check_unchanged(self) -> None:
        if read_file(self.project / "Capsule.csproj") != self.project_bytes:
            raise ValueError("generated embedded resource project changed during compilation")
        current = snapshot(self.project / "resources") if self.objects else {}
        if current != self.objects:
            raise ValueError("generated embedded resource bytes changed during compilation")


def install(files: dict[str, bytes], project: Path, *, additional_resources=()) -> EmbeddedResources | None:
    selected = guest_resources.select(files, additional_resources=additional_resources)
    if selected is None:
        return None
    project_path = project / "Capsule.csproj"
    original = read_file(project_path)
    objects = {path.rsplit("/", 1)[1] + ".bin": payload for path, payload in selected.objects.items()}
    generated = original
    if selected.rows:
        root = ET.fromstring(original)
        if root.tag != "Project" or root.findall(".//EmbeddedResource"):
            raise ValueError("embedded resource compiler template differs from its closed profile")
        properties = ET.SubElement(root, "PropertyGroup")
        ET.SubElement(properties, "EnableDefaultEmbeddedResourceItems").text = "false"
        items = ET.SubElement(root, "ItemGroup")
        for row in selected.rows:
            path = "resources/" + row["digest"][7:] + ".bin"
            item = ET.SubElement(items, "EmbeddedResource", {"Include": path})
            ET.SubElement(item, "LogicalName").text = msbuild_literal(row["path"])
            # A name containing a culture-like segment must remain in the
            # assembly, rather than silently become a satellite resource.
            ET.SubElement(item, "WithCulture").text = "false"
        generated = ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
        directory = project / "resources"
        directory.mkdir()
        for name, payload in sorted(objects.items()):
            with (directory / name).open("xb") as stream:
                stream.write(payload)
        project_path.write_bytes(generated)
    base = {"schemaVersion": PROFILE, "packagingProfile": guest_resources.PROFILE,
            "manifestDigest": digest(files[guest_resources.MANIFEST]) if guest_resources.MANIFEST in files else None,
            "dependencyLockDigest": digest(files["latent.dependencies.lock.json"])
                if "latent.dependencies.lock.json" in files else None,
            "count": len(selected.rows), "bytes": selected.total_bytes,
            "resources": selected.rows, "projectDigest": digest(generated),
            "scratchStorage": "unsupported"}
    return EmbeddedResources({**base, "identity": digest(encode(base))}, project, generated, objects)
