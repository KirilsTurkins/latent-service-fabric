"""Build separate source-observed Java domain and ordinary HTTP adapter packages."""
from pathlib import Path
import json

from tools.java_capsule_build import build
from tools.java_capsule_project import create
from tools.java_http_composition.revision import create_revision
from tools.java_http_generation.project import generate, check
from tools.java_http_generation.probes import qualify as qualify_generation
from tools.rust_capsule_project import ROOT, digest, read_json, write_json


def projects(output: Path) -> dict[str, Path]:
    result = {}
    for name in ("domain",):
        project = create(output / name, "greeting", "java-http-" + name)
        fixture = ROOT / "examples/java-http-composition" / name
        (project / "src/dev/latent/app/Capsule.java").write_bytes((fixture / "Capsule.java").read_bytes())
        (project / "wit/world.wit").write_bytes((fixture / "world.wit").read_bytes())
        descriptor = read_json(project / "capsule-project.json")
        descriptor["world"] = "examples:java-http-" + name + "/service@1.0.0"
        descriptor["limits"].update(childCalls=4 if name == "adapter" else 0,
                                    memoryBytes=134217728 if name == "adapter" else 67108864)
        (project / "capsule-project.json").write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
        lock = read_json(project / "sdk-lock.json")
        lock["template"] = {"name": "java-http-" + name,
                            "sourceDigest": digest((fixture / "Capsule.java").read_bytes()),
                            "witDigest": digest((fixture / "world.wit").read_bytes())}
        (project / "sdk-lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        result[name] = project
    selection = ROOT / "examples/java-http-composition/routes.json"
    result["adapter"] = generate(result["domain"], selection, output / "adapter")
    check(result["domain"], selection, result["adapter"])
    result["adapter-next"] = create_revision(result["adapter"], output / "adapter-next")
    return result


def compile_pair(output: Path, wasi_sdk: Path, binaries: dict) -> dict[str, Path]:
    selected = projects(output / "projects")
    qualify_generation(selected["domain"], ROOT / "examples/java-http-composition/routes.json",
        selected["adapter"], output / "generation-cases")
    return {name: build(project, output / "builds" / name,
        binaries["examples/capsule_contracts"], binaries["examples/package"],
        "https://github.com/KirilsTurkins/latent-service-fabric", wasi_sdk)
        for name, project in selected.items()}
