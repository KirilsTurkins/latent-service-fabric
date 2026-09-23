"""Editable outside-checkout TypeScript projects, with a captured SDK and WIT."""
from __future__ import annotations
import json
from pathlib import Path
import re
import tomllib
from tools.rust_capsule_project import (ROOT, TEMPLATES, TUTORIALS, decode_json, digest,
    fresh, inventory, read_file, snapshot)


def create(directory: Path, template: str, name: str | None = None) -> Path:
    if template not in TEMPLATES:
        raise ValueError("unknown TypeScript capsule template")
    name = name or "my-" + template
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("use a lowercase kebab-case capsule name, at most 64 bytes")
    source = (ROOT / "tools/toolchain-smoke/examples" / ("tutorial_" + template.replace("-", "_"))
              if template in TUTORIALS else ROOT / "examples/rust-capsules" / template)
    vendor = {}
    for folder in ("sdk/typescript-guest/runtime", "sdk/typescript-guest/capabilities", "wit/platform"):
        vendor.update({folder + "/" + path: data for path, data in snapshot(ROOT / folder).items()})
    for path in ("Cargo.toml", "tools/toolchain.toml", "LICENSE", "NOTICE",
                 "sdk/typescript-guest/tools/package.json", "sdk/typescript-guest/tools/package-lock.json"):
        vendor[path] = read_file(ROOT / path)
    files = {"vendor/lsf/" + path: data for path, data in vendor.items()}
    files.update({"src/main.ts": read_file(ROOT / "sdk/typescript-guest/templates" / (template + ".ts")),
                  "wit/world.wit": read_file(source / "world.wit"), ".gitignore": b"/target/\n"})
    if template == "http-status":
        files["wit/deps/http/package.wit"] = read_file(ROOT / "wit/platform/http-v2/package.wit")
    limits = json.loads(read_file(ROOT / "examples/echo-contract/capsule.json"))["execution"]["limits"]
    limits.update(cpuFuel=1_000_000_000, memoryBytes=134_217_728, wallTimeLimitMillis=5000, logBytes=0)
    if template == "http-status":
        limits["outboundRequests"] = 1
    project = {"formatVersion": 1, "name": name, "version": "1.0.0", "tenant": "examples",
               "service": "examples/" + name, "world": f"examples:{template}/service@1.0.0", "limits": limits}
    lock = {"formatVersion": 1, "language": "typescript", "sdk": json.loads(inventory(vendor)),
            "template": {"name": template, "sourceDigest": digest(files["src/main.ts"]),
                         "witDigest": digest(files["wit/world.wit"])}}
    files["capsule-project.json"] = json.dumps(project, indent=2).encode() + b"\n"
    files["sdk-lock.json"] = json.dumps(lock, indent=2).encode() + b"\n"
    files["README.md"] = (f"# {name}\n\nEdit `src/main.ts` and `wit/world.wit`. Keep `vendor/lsf` unchanged.\n"
        "`tools/typescript_capsule.py build` generates authoritative typed bindings,\n"
        "typechecks all application sources, and compiles the actual application.\n"
        "No capability is granted by this project. The compiler is build-time only.\n").encode()
    directory = fresh(directory)
    for path, data in sorted(files.items()):
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(data)
    return directory


def validate(files: dict[str, bytes]) -> tuple[dict, dict, dict]:
    if not {"capsule-project.json", "sdk-lock.json", "src/main.ts", "wit/world.wit"} <= files.keys():
        raise ValueError("incomplete TypeScript capsule project")
    project, lock = (decode_json(files[name]) for name in ("capsule-project.json", "sdk-lock.json"))
    if (not isinstance(project, dict) or set(project) != {"formatVersion", "name", "version", "tenant", "service", "world", "limits"}
            or type(project["formatVersion"]) is not int or project["formatVersion"] != 1):
        raise ValueError("unsupported capsule project format")
    if not isinstance(project["name"], str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", project["name"]) or len(project["name"]) > 64:
        raise ValueError("invalid TypeScript capsule name")
    if not all(isinstance(project[key], str) and 0 < len(project[key]) <= 512 for key in ("version", "service", "world")):
        raise ValueError("invalid capsule identity")
    if project["tenant"] is not None and not (isinstance(project["tenant"], str) and 0 < len(project["tenant"]) <= 512):
        raise ValueError("invalid optional tenant identity")
    if (not isinstance(lock, dict) or set(lock) != {"formatVersion", "language", "sdk", "template"}
            or type(lock["formatVersion"]) is not int or lock["formatVersion"] != 1 or lock["language"] != "typescript"):
        raise ValueError("unsupported TypeScript SDK lock")
    vendor = {path.removeprefix("vendor/lsf/"): data for path, data in files.items() if path.startswith("vendor/lsf/")}
    if json.loads(inventory(vendor)) != lock["sdk"]:
        raise ValueError("vendored SDK changed; review and regenerate the SDK source lock")
    if any(Path(path).name in {"package.json", "package-lock.json", "tsconfig.json"} for path in files if not path.startswith("vendor/lsf/")):
        raise ValueError("application package/config overrides require a reviewed dependency capture extension")
    limits = project["limits"]
    required = set(json.loads(read_file(ROOT / "examples/echo-contract/capsule.json"))["execution"]["limits"])
    if not isinstance(limits, dict) or set(limits) != required:
        raise ValueError("explicit closed invocation budget required")
    if any(type(value) is not int or not 0 <= value < 2**64 for value in limits.values()):
        raise ValueError("invocation budgets require finite unsigned full-width integers")
    if not limits["cpuFuel"] or not limits["memoryBytes"] or not limits["wallTimeLimitMillis"]:
        raise ValueError("positive fuel, memory and wall-time budgets required")
    return project, lock, tomllib.loads(vendor["tools/toolchain.toml"].decode())
