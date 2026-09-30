"""Observed WIT/binding inputs and independent generated adapter project."""
from pathlib import Path
import json
import tempfile

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.java_capsule_project import create, validate
from tools.java_guest.bindings import generate as bindings
from tools.java_guest.surface import surface
from tools.java_http_generation import adapter, client
from tools.java_http_generation.selection import selected, PROFILE
from tools.rust_capsule_project import (ROOT, canonical, checked_path, digest, fresh,
    inventory, read_file, read_json, snapshot)
from tools.stage_runtime_wit import copy_wit_tree, dependencies

RECIPE = ("tools/java_http_adapter.py", "tools/java_http_generation/selection.py",
    "tools/java_http_generation/adapter.py", "tools/java_http_generation/client.py",
    "tools/java_http_generation/client-runtime.mjs", "tools/java_http_generation/project.py",
    "tools/java_guest/bindings.py", "tools/java_guest/model.py", "tools/java_guest/java.py",
    "tools/java_guest/c.py", "tools/java_guest/surface.py")


def rendered(domain: Path, selection_path: Path) -> tuple[dict, dict[str, bytes], dict]:
    captured = snapshot(domain)
    project, _, pins = validate(captured)
    selection_bytes = read_file(selection_path, 65536)
    selection = read_json(selection_path, 65536)
    recipe = inventory({name: read_file(ROOT / name) for name in RECIPE})
    with tempfile.TemporaryDirectory(prefix="lsf-java-http-wit-") as owned:
        temporary = Path(owned)
        environment = build_environment(temporary)

        def run(stage, *arguments):
            result = run_bounded_result(list(map(str, arguments)), cwd=temporary, env=environment,
                timeout_seconds=60, max_output_bytes=4 * 1024 * 1024)
            if result.returncode != 0:
                raise ValueError(stage + ": " + result.stderr.decode("utf-8", "replace")[:4096])
            return result.stdout.decode("utf-8")

        for tool, printed, version in (("wasm-tools", "wasm-tools", pins["contracts"]["wasm-tools"]),
                                      ("wit-bindgen", "wit-bindgen-cli", pins["rust"]["dependencies"]["wit-bindgen"])):
            if run("toolchain", tool, "--version").split()[:2] != [printed, version]:
                raise ValueError("toolchain: " + tool + " must match the captured exact pin " + version)
        wit = temporary / "wit"
        for name, data in captured.items():
            if not name.startswith("wit/"): continue
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for package in dependencies(wit, domain / "vendor/lsf/wit/platform"):
            copy_wit_tree(package, wit / "deps" / package.name)
        generated = bindings(run, wit, project["world"], temporary / "bindings")
        graph = json.loads(run("wit-parse", "wasm-tools", "component", "wit", wit, "--json"))
        authoritative = surface(graph, project["world"])
        routes = selected(authoritative, selection)
        outputs = {"src/dev/latent/app/Capsule.java": adapter.source(selection, routes),
                   "wit/world.wit": adapter.wit(selection["adapterName"]),
                   **{"http/" + name: data for name, data in client.files(routes).items()}}
        if sum(map(len, outputs.values())) > 1024 * 1024:
            raise ValueError("generated-code: finite one MiB output limit exceeded")
        observation = {"profile": PROFILE, "domainWorld": project["world"],
            "domainSourceDigest": digest(inventory(captured)), "domainWit": json.loads(inventory(snapshot(wit))),
            "domainBindings": generated, "selectionDigest": digest(selection_bytes),
            "recipeDigest": digest(recipe), "outputs": json.loads(inventory(outputs)),
            "authority": "no-keys-grants-provider-bindings-or-http-trigger-authority"}
        if (snapshot(domain) != captured or read_file(selection_path, 65536) != selection_bytes
                or inventory({name: read_file(ROOT / name) for name in RECIPE}) != recipe):
            raise ValueError("generation-inputs: inputs changed during generation")
        return selection, outputs, observation


def generate(domain: Path, selection_path: Path, output: Path) -> Path:
    domain, selection_path, output = map(checked_path, (domain, selection_path, output))
    if output == domain or domain in output.parents or output in domain.parents:
        raise ValueError("generation-output: choose a fresh directory outside the domain project")
    selection, outputs, observation = rendered(domain, selection_path)
    output = create(output, "greeting", selection["adapterName"])
    for name, data in outputs.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    descriptor = read_json(output / "capsule-project.json")
    descriptor["world"] = "examples:" + selection["adapterName"] + "/service@1.0.0"
    descriptor["limits"].update(childCalls=4, memoryBytes=134217728)
    (output / "capsule-project.json").write_bytes(canonical(descriptor) + b"\n")
    lock = read_json(output / "sdk-lock.json")
    lock["template"] = {"name": PROFILE, "sourceDigest": digest(outputs["src/dev/latent/app/Capsule.java"]),
                        "witDigest": digest(outputs["wit/world.wit"])}
    (output / "sdk-lock.json").write_bytes(canonical(lock) + b"\n")
    (output / "http/selection.json").write_bytes(read_file(selection_path, 65536))
    (output / "http/generation.json").write_bytes(canonical(observation) + b"\n")
    (output / "README.md").write_bytes(("# " + selection["adapterName"] + "\n\nGenerated from an authoritative typed Java domain and explicit routes.\n"
        "Regenerate through `tools/java_http_adapter.py`; run `check` before building.\n"
        "The node requires explicit clock grants, local-service binding/grant and pinned HTTP trigger.\n"
        "The additional local-service hop remains part of this profile. No latency change is measured.\n").encode())
    validate(snapshot(output))
    return output


def check(domain: Path, selection_path: Path, output: Path) -> Path:
    output = checked_path(output)
    actual = snapshot(output)
    with tempfile.TemporaryDirectory(prefix="lsf-java-http-check-") as owned:
        expected = generate(domain, selection_path, Path(owned) / "adapter")
        if snapshot(expected) != actual:
            raise ValueError("stale-generation: WIT, routes, SDK, recipe or generated files changed; generate a fresh adapter")
    return output
