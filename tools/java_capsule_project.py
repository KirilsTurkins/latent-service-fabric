"""Independent Java projects, with captured SDK sources and no implicit authority."""
from __future__ import annotations
import json
from pathlib import Path
import re
import tomllib

from tools.java_guest.compiler import sdk_snapshot
from tools.rust_capsule_project import (ROOT, TEMPLATES, TUTORIALS, decode_json, digest,
    fresh, inventory, read_file, snapshot)


def runtime_wit(source: bytes, world: str) -> bytes:
    """Templates visibly declare the two real clock imports needed by TeaVM."""
    text = source.decode()
    pattern = r"\bworld\s+" + re.escape(world) + r"\s*\{"
    if len(re.findall(pattern, text)) != 1:
        raise ValueError("expected exactly one selected template world")
    clocks = "\n    import latent:clock/monotonic@0.1.0;\n    import latent:clock/wall@0.1.0;\n"
    text = re.sub(pattern, lambda match: match[0] + clocks, text)
    return (text + "\nworld runtime-support {" + clocks + "}\n").encode()


def create(directory: Path, template: str, name: str | None = None) -> Path:
    if template not in TEMPLATES:
        raise ValueError("unknown Java capsule template")
    name = name or "my-" + template
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("use a lowercase kebab-case capsule name, at most 64 bytes")
    source = (ROOT / "tools/toolchain-smoke/examples" / ("tutorial_" + template.replace("-", "_"))
              if template in TUTORIALS else ROOT / "examples/rust-capsules" / template)
    vendor = {"sdk/java-guest/" + path: data for path, data in sdk_snapshot(ROOT / "sdk/java-guest").items()}
    vendor.update({"wit/platform/" + path: data for path, data in snapshot(ROOT / "wit/platform").items()})
    for path in ("Cargo.toml", "tools/toolchain.toml", "LICENSE", "NOTICE"):
        vendor[path] = read_file(ROOT / path)
    files = {"vendor/lsf/" + path: data for path, data in vendor.items()}
    files.update({"src/dev/latent/app/Capsule.java": read_file(ROOT / "sdk/java-guest/templates" / (template + ".java")),
                  "wit/world.wit": runtime_wit(read_file(source / "world.wit"), "service"), ".gitignore": b"/target/\n"})
    limits = json.loads(read_file(ROOT / "examples/echo-contract/capsule.json"))["execution"]["limits"]
    limits.update(cpuFuel=1_000_000_000, memoryBytes=67_108_864, wallTimeLimitMillis=120000, logBytes=0)
    if template == "http-status": limits.update(outboundRequests=1)
    project = {"formatVersion": 1, "name": name, "version": "1.0.0", "tenant": "examples",
               "service": "examples/" + name, "world": f"examples:{template}/service@1.0.0", "limits": limits}
    lock = {"formatVersion": 1, "language": "java", "sdk": json.loads(inventory(vendor)),
            "bindings": "lsf-java-wit-v1+wit-bindgen-0.62.0",
            "template": {"name": template, "sourceDigest": digest(files["src/dev/latent/app/Capsule.java"]),
                         "witDigest": digest(files["wit/world.wit"])}}
    files["capsule-project.json"] = json.dumps(project, indent=2).encode() + b"\n"
    files["sdk-lock.json"] = json.dumps(lock, indent=2).encode() + b"\n"
    files["README.md"] = (f"# {name}\n\nEdit `src/dev/latent/app/Capsule.java` and `wit/world.wit`.\n"
        "Keep `vendor/lsf` unchanged. Build with `tools/java_capsule.py` from the SDK checkout.\n"
        "The complete guide is `docs/component-development/java-authoring.md`.\n"
        "WIT declares the runtime clocks; only an operator can grant them. No JVM is deployed.\n").encode()
    directory = fresh(directory)
    for relative, data in sorted(files.items()):
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output: output.write(data)
    return directory


def validate(files: dict[str, bytes]) -> tuple[dict, dict, dict]:
    if not {"capsule-project.json", "sdk-lock.json", "src/dev/latent/app/Capsule.java", "wit/world.wit"} <= files.keys():
        raise ValueError("incomplete Java capsule project")
    project, lock = (decode_json(files[name]) for name in ("capsule-project.json", "sdk-lock.json"))
    if (not isinstance(project, dict) or set(project) != {"formatVersion", "name", "version", "tenant", "service", "world", "limits"}
            or type(project["formatVersion"]) is not int or project["formatVersion"] != 1):
        raise ValueError("unsupported Java capsule project format")
    if not isinstance(project["name"], str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", project["name"]) or len(project["name"]) > 64:
        raise ValueError("invalid Java capsule name")
    if (not all(isinstance(project[key], str) and 0 < len(project[key]) <= 512 for key in ("version", "service", "world"))
            or project["tenant"] is not None and (not isinstance(project["tenant"], str) or not 0 < len(project["tenant"]) <= 128)):
        raise ValueError("invalid capsule identity")
    if (not isinstance(lock, dict) or set(lock) != {"formatVersion", "language", "sdk", "bindings", "template"}
            or type(lock["formatVersion"]) is not int or lock["formatVersion"] != 1 or lock["language"] != "java"
            or lock["bindings"] != "lsf-java-wit-v1+wit-bindgen-0.62.0"):
        raise ValueError("unsupported Java SDK lock")
    vendor = {path.removeprefix("vendor/lsf/"): data for path, data in files.items() if path.startswith("vendor/lsf/")}
    if json.loads(inventory(vendor)) != lock["sdk"]:
        raise ValueError("vendored SDK changed; review and regenerate the SDK source lock")
    # This version deliberately supports Java source dependencies only. Ignored
    # Gradle/JAR overrides would falsely appear to be captured compiler inputs.
    for path in files:
        if path.startswith("vendor/lsf/"): continue
        if path.endswith((".jar", ".class", ".gradle", ".gradle.kts")) or Path(path).name == "pom.xml":
            raise ValueError("binary dependencies and application build scripts require a new reviewed Java recipe")
        if path.startswith("src/") and not path.endswith(".java"):
            raise ValueError("Java application sources must be Java files")
    limits = project["limits"]
    required = set(json.loads(read_file(ROOT / "examples/echo-contract/capsule.json"))["execution"]["limits"])
    if not isinstance(limits, dict) or set(limits) != required:
        raise ValueError("explicit closed invocation budget required")
    if any(type(value) is not int or not 0 <= value < 2**64 for value in limits.values()):
        raise ValueError("Java invocation budgets require finite unsigned full-width integers")
    if not limits["cpuFuel"] or limits["memoryBytes"] <= 4_194_304 or not limits["wallTimeLimitMillis"]:
        raise ValueError("positive fuel, wall-time and memory above the charged exception reservation required")
    return project, lock, tomllib.loads(vendor["tools/toolchain.toml"].decode())
