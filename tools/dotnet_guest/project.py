"""Independent C# sources and authoritative WIT, with an immutable SDK capture."""
from __future__ import annotations
import json
from pathlib import Path
import re
import tomllib
from tools.rust_capsule_project import (ROOT, TEMPLATES, TUTORIALS, decode_json, digest,
    fresh, inventory, read_file, snapshot)

CLOCK = "latent:clock/monotonic@0.1.0"


def project_xml(template: bytes) -> bytes:
    value = template.decode().replace('World="probe"', 'World="service"')
    value = value.replace("<TargetFramework>net10.0</TargetFramework>",
        "<TargetFramework>net10.0</TargetFramework>\n    <Nullable>enable</Nullable>\n"
        "    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>")
    value = value.replace("<ItemGroup>", '<ItemGroup>\n    <Compile Include="src/**/*.cs" />\n    <Compile Include="lsf/*.cs" />')
    return value.encode()


def declare_runtime(world: str) -> str:
    if world.count("world service {") != 1:
        raise ValueError("C# template world drift")
    return world.replace("world service {", "world service {\n    import " + CLOCK + ";")


def create(directory: Path, template: str, name: str | None = None) -> Path:
    if template not in TEMPLATES:
        raise ValueError("unknown C# capsule template")
    name = "my-" + template if name is None else name
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("use a lowercase kebab-case capsule name, at most 64 bytes")
    source = (ROOT / "tools/toolchain-smoke/examples" / ("tutorial_" + template.replace("-", "_"))
              if template in TUTORIALS else ROOT / "examples/rust-capsules" / template)
    vendor = {}
    for folder in ("sdk/dotnet-guest/runtime", "sdk/dotnet-guest/ownership",
                   "sdk/dotnet-guest/capabilities", "wit/platform"):
        vendor.update({folder + "/" + path: data for path, data in snapshot(ROOT / folder).items()})
    for path in ("Cargo.toml", "Cargo.lock", "tools/toolchain.toml", "LICENSE", "NOTICE",
                 "tools/toolchain-smoke/examples/dotnet_closed_runtime.rs", "tools/dotnet_guest_bindings.py",
                 "sdk/dotnet-guest/global.json", "sdk/dotnet-guest/nuget.config",
                 "sdk/dotnet-guest/probes/smoke/Smoke.csproj", "sdk/dotnet-guest/probes/smoke/packages.lock.json"):
        vendor[path] = read_file(ROOT / path)
    files = {"vendor/lsf/" + path: data for path, data in vendor.items()}
    files.update({"src/Main.cs": read_file(ROOT / "sdk/dotnet-guest/templates" / (template + ".cs")),
        "Capsule.csproj": project_xml(vendor["sdk/dotnet-guest/probes/smoke/Smoke.csproj"]),
        "global.json": vendor["sdk/dotnet-guest/global.json"],
        "wit/world.wit": declare_runtime(read_file(source / "world.wit").decode()).encode(),
        ".gitignore": b"/target/\n"})
    for package in ("clock",) + (("http-v2",) if template == "http-status" else ()):
        files.update({"wit/deps/" + package + "/" + path: data
                      for path, data in snapshot(ROOT / "wit/platform" / package).items()})
    limits = json.loads(read_file(ROOT / "examples/echo-contract/capsule.json"))["execution"]["limits"]
    limits.update(cpuFuel=1_000_000_000, memoryBytes=134_217_728, wallTimeLimitMillis=120000, logBytes=0)
    if template == "http-status":
        limits["outboundRequests"] = 1
    project = {"formatVersion": 1, "name": name, "version": "1.0.0", "tenant": "examples",
               "service": "examples/" + name, "world": f"examples:{template}/service@1.0.0", "limits": limits}
    lock = {"formatVersion": 1, "language": "dotnet", "sdk": json.loads(inventory(vendor)),
            "template": {"name": template, "sourceDigest": digest(files["src/Main.cs"]),
                         "witDigest": digest(files["wit/world.wit"])}}
    files["capsule-project.json"] = json.dumps(project, indent=2).encode() + b"\n"
    files["sdk-lock.json"] = json.dumps(lock, indent=2).encode() + b"\n"
    files["README.md"] = (f"# {name}\n\nEdit `src/Main.cs` and `wit/world.wit`. Keep `vendor/lsf` unchanged.\n"
        "`tools/dotnet_capsule.py build` creates the pinned NativeAOT project from these sources.\n"
        "The GC monotonic-clock import requires an explicit operator grant.\n"
        "No .NET process, thread pool, timer or event loop belongs to a deployed capsule.\n").encode()
    directory = fresh(directory)
    for path, data in sorted(files.items()):
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(data)
    return directory


def validate(files: dict[str, bytes]) -> tuple[dict, dict, dict]:
    if not {"capsule-project.json", "sdk-lock.json", "src/Main.cs", "wit/world.wit"} <= files.keys():
        raise ValueError("incomplete C# capsule project")
    project, lock = (decode_json(files[name]) for name in ("capsule-project.json", "sdk-lock.json"))
    if (not isinstance(project, dict) or set(project) != {"formatVersion", "name", "version", "tenant", "service", "world", "limits"}
            or type(project["formatVersion"]) is not int or project["formatVersion"] != 1):
        raise ValueError("unsupported capsule project format")
    if not isinstance(project["name"], str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", project["name"]) or len(project["name"]) > 64:
        raise ValueError("invalid C# capsule name")
    if not all(isinstance(project[key], str) and 0 < len(project[key]) <= 512 for key in ("version", "service", "world")):
        raise ValueError("invalid capsule identity")
    if project["tenant"] is not None and not (isinstance(project["tenant"], str) and 0 < len(project["tenant"]) <= 512):
        raise ValueError("invalid optional tenant identity")
    if (not isinstance(lock, dict) or set(lock) != {"formatVersion", "language", "sdk", "template"}
            or type(lock["formatVersion"]) is not int or lock["formatVersion"] != 1 or lock["language"] != "dotnet"):
        raise ValueError("unsupported C# SDK lock")
    vendor = {path.removeprefix("vendor/lsf/"): data for path, data in files.items() if path.startswith("vendor/lsf/")}
    if json.loads(inventory(vendor)) != lock["sdk"]:
        raise ValueError("vendored SDK changed; review and regenerate the SDK source lock")
    for path in files:
        if path.startswith("vendor/lsf/") or path in {"Capsule.csproj", "global.json"}:
            continue
        if Path(path).suffix.lower() in {".csproj", ".props", ".targets", ".sln", ".config"} or Path(path).name in {"global.json", "packages.lock.json"}:
            raise ValueError("application MSBuild/package overrides require a reviewed capture extension")
    if files.get("Capsule.csproj") != project_xml(vendor["sdk/dotnet-guest/probes/smoke/Smoke.csproj"]):
        raise ValueError("application project compiler configuration differs from its reviewed SDK template")
    if files.get("global.json") != vendor["sdk/dotnet-guest/global.json"]:
        raise ValueError("application .NET SDK version differs from its pinned template")
    if not re.fullmatch(r"[a-z][a-z0-9-]*:[a-z][a-z0-9-]*/service@[0-9]+\.[0-9]+\.[0-9]+", project["world"]):
        raise ValueError("the supported C# profile requires a versioned service world")
    limits = project["limits"]
    required = set(json.loads(read_file(ROOT / "examples/echo-contract/capsule.json"))["execution"]["limits"])
    if not isinstance(limits, dict) or set(limits) != required:
        raise ValueError("explicit closed invocation budget required")
    if any(type(value) is not int or not 0 <= value < 2**64 for value in limits.values()):
        raise ValueError("invocation budgets require finite unsigned full-width integers")
    if not limits["cpuFuel"] or not limits["memoryBytes"] or not limits["wallTimeLimitMillis"]:
        raise ValueError("positive fuel, memory and wall-time budgets required")
    return project, lock, tomllib.loads(vendor["tools/toolchain.toml"].decode())
