"""A maintained compatible adapter revision with distinct observed guest bytes."""
from pathlib import Path
import json

from tools.java_capsule_project import create, validate
from tools.rust_capsule_project import digest, inventory, read_json, snapshot, write_json


def create_revision(parent: Path, output: Path) -> Path:
    original = snapshot(parent)
    project, _, _ = validate(original)
    source = original["src/dev/latent/app/Capsule.java"]
    marker = b'"route-not-selected"'
    if source.count(marker) != 1 or project["limits"]["cpuFuel"] <= 1:
        raise ValueError("compatible revision requires the maintained adapter and finite CPU budget")
    source = source.replace(marker, b'"route-not-selected-compatible-revision"')
    output = create(output, "greeting", "java-http-adapter-next")
    (output / "src/dev/latent/app/Capsule.java").write_bytes(source)
    (output / "wit/world.wit").write_bytes(original["wit/world.wit"])
    descriptor = read_json(output / "capsule-project.json")
    for field in ("tenant", "service", "world", "limits"):
        descriptor[field] = project[field]
    descriptor["version"] = "1.0.1"
    descriptor["limits"]["cpuFuel"] -= 1
    (output / "capsule-project.json").write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
    lock = read_json(output / "sdk-lock.json")
    lock["template"] = {"name": "latent.java-http.compatible-revision.v1", "sourceDigest": digest(source),
        "witDigest": digest(original["wit/world.wit"])}
    (output / "sdk-lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    write_json(output / "revision.json", {"schemaVersion": "latent.java-http.compatible-revision.v1",
        "parentInputsDigest": digest(inventory(original)), "change": "bounded-unselected-route-message",
        "contract": "unchanged-exact-buffered-web-export", "authority": "independent-build-sign-and-admission-required"})
    (output / "README.md").write_text("# Compatible Java HTTP adapter revision\n\n"
        "This independently compiled revision changes the bounded body for unselected routes.\n"
        "It preserves the parent's exact WIT and service identity, with a new package name/version\n"
        "and one less CPU fuel. Build, sign and admit it independently before canary or rollback.\n",
        encoding="utf-8")
    validate(snapshot(output))
    if snapshot(parent) != original:
        raise ValueError("compatible adapter parent changed during revision construction")
    return output
