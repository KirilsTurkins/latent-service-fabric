"""Independent, captured C projects using the maintained WIT and C SDK."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib

from tools.rust_capsule_project import (ROOT, TEMPLATES, TUTORIALS, decode_json, digest,
    fresh, inventory, read_file, snapshot)


def create(directory: Path, template: str, name: str | None = None) -> Path:
    if template not in TEMPLATES:
        raise ValueError("unknown C capsule template")
    name = name or "my-" + template
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("use a lowercase kebab-case capsule name, at most 64 bytes")
    source = (ROOT / "tools/toolchain-smoke/examples" / ("tutorial_" + template.replace("-", "_"))
              if template in TUTORIALS else ROOT / "examples/rust-capsules" / template)
    vendor = {}
    for folder in ("sdk/c-guest/include", "sdk/c-guest/src", "wit/platform"):
        vendor.update({folder + "/" + path: data for path, data in snapshot(ROOT / folder).items()})
    for path in ("Cargo.toml", "tools/toolchain.toml", "LICENSE", "NOTICE"):
        vendor[path] = read_file(ROOT / path)
    files = {"vendor/lsf/" + path: data for path, data in vendor.items()}
    files.update({"src/main.c": read_file(ROOT / "sdk/c-guest/templates" / (template + ".c")),
                  "wit/world.wit": read_file(source / "world.wit"), ".gitignore": b"/target/\n"})
    if template == "http-status":
        files["wit/deps/http/package.wit"] = read_file(ROOT / "wit/platform/http-v2/package.wit")
    limits = json.loads(read_file(ROOT / "examples/echo-contract/capsule.json"))["execution"]["limits"]
    limits.update(cpuFuel=100_000_000, memoryBytes=4_194_304, wallTimeLimitMillis=1000, logBytes=0)
    if template == "http-status":
        limits.update(cpuFuel=1_000_000_000, memoryBytes=16_777_216, wallTimeLimitMillis=5000, outboundRequests=1)
    project = {"formatVersion": 1, "name": name, "version": "1.0.0", "tenant": "examples",
               "service": "examples/" + name, "world": f"examples:{template}/service@1.0.0", "limits": limits}
    lock = {"formatVersion": 1, "language": "c", "sdk": json.loads(inventory(vendor)),
            "bindings": json.loads(read_file(ROOT / "tools/guest_bindings.lock.json")),
            "template": {"name": template, "sourceDigest": digest(files["src/main.c"]),
                         "witDigest": digest(files["wit/world.wit"])}}
    files["capsule-project.json"] = json.dumps(project, indent=2).encode() + b"\n"
    files["sdk-lock.json"] = json.dumps(lock, indent=2).encode() + b"\n"
    files["README.md"] = (f"# {name}\n\nEdit `src/main.c` and `wit/world.wit`. Keep `vendor/lsf` unchanged.\n"
        "Build with `tools/c_capsule.py` from the SDK checkout. The complete guide is\n"
        "`docs/component-development/c-authoring.md`. No capability is granted by this project.\n").encode()
    directory = fresh(directory)
    for name, data in sorted(files.items()):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(data)
    return directory


def validate(files: dict[str, bytes]) -> tuple[dict, dict, dict]:
    if not {"capsule-project.json", "sdk-lock.json", "src/main.c", "wit/world.wit"} <= files.keys():
        raise ValueError("incomplete C capsule project")
    project, lock = (decode_json(files[name]) for name in ("capsule-project.json", "sdk-lock.json"))
    if (not isinstance(project, dict) or set(project) != {"formatVersion", "name", "version", "tenant", "service", "world", "limits"}
            or type(project["formatVersion"]) is not int or project["formatVersion"] != 1):
        raise ValueError("unsupported capsule project format")
    if not isinstance(project["name"], str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", project["name"]) or len(project["name"]) > 64:
        raise ValueError("invalid C capsule name")
    if not all(isinstance(project[key], str) and 0 < len(project[key]) <= 512 for key in ("version", "tenant", "service", "world")):
        raise ValueError("invalid capsule identity")
    if (not isinstance(lock, dict) or set(lock) != {"formatVersion", "language", "sdk", "bindings", "template"}
            or type(lock["formatVersion"]) is not int or lock["formatVersion"] != 1 or lock["language"] != "c"):
        raise ValueError("unsupported C SDK lock")
    vendor = {path.removeprefix("vendor/lsf/"): data for path, data in files.items() if path.startswith("vendor/lsf/")}
    if json.loads(inventory(vendor)) != lock["sdk"]:
        raise ValueError("vendored SDK changed; review and regenerate the SDK source lock")
    limits = project["limits"]
    required = set(json.loads(read_file(ROOT / "examples/echo-contract/capsule.json"))["execution"]["limits"])
    if not isinstance(limits, dict) or set(limits) != required:
        raise ValueError("explicit closed invocation budget required")
    if any(type(value) is not int or not 0 <= value < 2**64 for value in limits.values()):
        raise ValueError("C invocation budgets require finite unsigned full-width integers")
    if not limits["cpuFuel"] or not limits["memoryBytes"] or not limits["wallTimeLimitMillis"]:
        raise ValueError("positive fuel, memory and wall-time budgets required")
    return project, lock, tomllib.loads(vendor["tools/toolchain.toml"].decode())
