"""Create editable order-draft projects using the six existing captured SDK owners."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
APPLICATION = ROOT / "examples/stateful-reference"
WORLD = "examples:order-draft/service@1.0.0"
LANGUAGES = ("rust", "c", "typescript", "go", "java", "dotnet")
SOURCES = {
    "rust": ("rust.rs", "src/lib.rs"), "c": ("c.c", "src/main.c"),
    "typescript": ("typescript.ts", "src/main.ts"), "go": ("go.go", "src/main.go"),
    "java": ("java.java", "src/dev/latent/app/Capsule.java"), "dotnet": ("dotnet.cs", "src/Main.cs"),
}


def creator(language: str):
    if language == "rust":
        from tools.rust_capsule_project import create
    elif language == "c":
        from tools.c_capsule_project import create
    elif language == "typescript":
        from tools.typescript_guest.project import create
    elif language == "go":
        from tools.go_capsule_project import create
    elif language == "java":
        from tools.java_capsule_project import create
    elif language == "dotnet":
        from tools.dotnet_guest.project import create
    else:
        raise ValueError("unsupported order-draft guest language")
    return create


def application_world(seed: bytes) -> bytes:
    """Retain the selected language's existing runtime imports without new authority."""
    text = seed.decode("utf8")
    if text.count("world service {") != 1:
        raise ValueError("captured transaction world identity changed")
    body, auxiliary = text.split("world service {", 1)[1].split("}", 1)
    imports = re.findall(r"^\s*import [a-z][a-z0-9:/@.-]+;\s*$", body, re.MULTILINE)
    retained = [line.strip() for line in imports if line.strip() not in {
        "import latent:state/key-value@0.2.0;", "import latent:intents/staging@0.1.0;"}]
    if any(not line.startswith(("import latent:clock/", "import latent:entropy/", "import latent:logging/",
                                "import latent:random/", "import latent:gc/")) for line in retained):
        raise ValueError("unreviewed language runtime import in captured transaction world")
    source = (APPLICATION / "world.wit").read_text(encoding="utf8")
    insertion = "world service {\n" + "".join("    " + line + "\n" for line in retained)
    if auxiliary.strip():
        # Java's maintained creator supplies the closed WASI adapter world as
        # well as the selected service world. Preserve those exact reviewed
        # clock declarations; they grant no additional application authority.
        runtime = (r"\s*world runtime-support \{\s*"
                   r"import latent:clock/monotonic@0\.1\.0;\s*"
                   r"import latent:clock/wall@0\.1\.0;\s*\}\s*")
        if not re.fullmatch(runtime, auxiliary):
            raise ValueError("unreviewed auxiliary language runtime world")
    return (source.replace("world service {\n", insertion, 1) + auxiliary).encode("utf8")


def create(output: Path, language: str, name: str | None = None, draft_id: str = "demo") -> Path:
    if language not in LANGUAGES:
        raise ValueError("unsupported order-draft guest language")
    if not isinstance(draft_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", draft_id):
        raise ValueError("order-draft identity must be bounded lowercase letters, digits and hyphens")
    name = "order-draft-" + language if name is None else name
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("order-draft project name must be bounded lowercase kebab case")
    # The ordinary maintained creator performs fresh-target ownership checks,
    # captures the actual SDK and pins, and selects its supported compiler path.
    project_root = creator(language)(output, "transactional-aggregate", name)
    seed = (project_root / "wit/world.wit").read_bytes()
    selected, destination = SOURCES[language]
    source = (APPLICATION / "guests" / selected).read_bytes()
    if source.count(b"lsf-example-begin: order-draft") != 1:
        raise ValueError("order-draft source region changed")
    (project_root / destination).write_bytes(source)
    world = application_world(seed)
    (project_root / "wit/world.wit").write_bytes(world)
    schema = (APPLICATION / "state-schema.json").read_bytes()
    (project_root / "state-schema.json").write_bytes(schema)
    project_path = project_root / "capsule-project.json"
    project = json.loads(project_path.read_bytes())
    project["world"] = WORLD
    # Keep each language's existing compiler/runtime memory, fuel and watchdog
    # bounds; only narrow the inherited application state/intent allowances.
    if "limits" in project:
        project["limits"].update(stateReadBytes=4096, stateWriteBytes=1024, effectCount=2)
        if project["limits"].get("outboundRequests", 0) != 0 or project["limits"].get("childCalls", 0) != 0:
            raise ValueError("order-draft project cannot inherit immediate HTTP or child authority")
    project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf8", newline="\n")
    declaration_path = project_root / "transaction-binding.json"
    declaration = json.loads(declaration_path.read_bytes())
    declaration["namespace"] = "order-drafts-" + draft_id
    declaration["stateSchema"] = "sha256:" + hashlib.sha256(schema).hexdigest()
    declaration["operations"] = [{"operation": name, "mode": mode,
                                  "inputFormat": "lsf-wit-values-v1", "resultFormat": "lsf-wit-values-v1"}
                                 for name, mode in (("edit", "strict-command"), ("query", "fresh-query"))]
    declaration_path.write_text(json.dumps(declaration, indent=2) + "\n", encoding="utf8", newline="\n")
    from tools.dev_workflow.transaction_binding import validate
    validate(declaration_path.read_bytes(), capsule=project["service"], deployment=project["name"], binding=project["name"])
    # The original SDK lock retains its original template provenance. Edited
    # application source is captured by the normal language build observation.
    authored = {"formatVersion": 1, "application": "order-draft-v1", "language": language, "world": WORLD,
                "draftId": draft_id,
                "source": destination, "sourceDigest": "sha256:" + hashlib.sha256(source).hexdigest(),
                "witDigest": "sha256:" + hashlib.sha256(world).hexdigest(),
                "stateSchema": declaration["stateSchema"], "namespace": declaration["namespace"]}
    (project_root / "order-draft-source.json").write_text(json.dumps(authored, indent=2) + "\n", encoding="utf8", newline="\n")
    return project_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=LANGUAGES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name")
    parser.add_argument("--draft-id", default="demo")
    args = parser.parse_args()
    output = create(args.output, args.language, args.name, args.draft_id)
    print(json.dumps({"project": str(output), "language": args.language, "world": WORLD}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
