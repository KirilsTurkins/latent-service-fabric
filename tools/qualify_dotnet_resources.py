#!/usr/bin/env python3
"""Actual standard CLR lookup evidence; this is not signed capsule qualification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import guest_resources
from tools.build_observation import build_environment, file_identity
from tools.dev_workflow.common import digest, encode
from tools.dotnet_guest.compiler import SDK_VERSION, tree_identity
from tools.dotnet_guest.resources import install
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, checked_path, fresh, read_file, snapshot, write_json

HELPERS = ("tools/qualify_dotnet_resources.py", "tools/guest_resources.py", "tools/dotnet_guest/resources.py",
           "tools/dotnet_guest/compiler.py", "tools/build_observation.py", "tools/rust_capsule_build.py",
           "tools/rust_capsule_project.py", "tools/build_process.py", "tools/build_process_linux.py",
           "tools/build_process_windows.py", "tools/build_process_signals.py", "tools/build_snapshot.py",
           "tools/dev_workflow/common.py")
SCHEMA = "lsf.dotnet.standard-resource-qualification.v1"


def run(dotnet: Path, output: Path) -> dict:
    dotnet, output = checked_path(dotnet), fresh(output)
    started, commands, stage = time.monotonic(), None, "capture"
    recipe = {name: digest(read_file(ROOT / name)) for name in HELPERS}
    try:
        with tempfile.TemporaryDirectory(prefix="lsf-dotnet-resource-qualification-") as owned:
            temporary = Path(owned)
            project = temporary / "project"
            project.mkdir()
            environment = build_environment(temporary)
            environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
                DOTNET_NOLOGO="1", DOTNET_MULTILEVEL_LOOKUP="0", DOTNET_CLI_HOME=str(temporary / "home"),
                NUGET_PACKAGES=str(temporary / "nuget"), DOTNET_CLI_USE_MSBUILD_SERVER="0",
                DOTNET_EnableDiagnostics="0", LC_ALL="C.UTF-8", LANG="C.UTF-8")
            commands = Commands(project, output, environment, deadline_seconds=240, command_seconds=90)
            executable = file_identity(dotnet, "dotnet")
            stage = "compiler-inputs"
            if commands.run("dotnet-version", dotnet, "--version").strip() != SDK_VERSION.encode():
                raise ValueError("pinned .NET SDK 10.0.100 required")
            sdk_lines = commands.run("dotnet-sdks", dotnet, "--list-sdks").decode().splitlines()
            matches = [line[len(SDK_VERSION) + 2:-1] for line in sdk_lines
                       if line.startswith(SDK_VERSION + " [") and line.endswith("]")]
            if len(matches) != 1:
                raise ValueError("unique pinned .NET SDK location required")
            installation = Path(matches[0]).parent
            roots = {"sdk": Path(matches[0]) / SDK_VERSION,
                     "runtime": installation / "shared/Microsoft.NETCore.App/10.0.0",
                     "reference": installation / "packs/Microsoft.NETCore.App.Ref/10.0.0",
                     "hostfxr": installation / "host/fxr"}
            compiler_inputs = tree_identity(roots)
            write_json(output / "compiler-inputs.json", compiler_inputs)
            names = ["data/plain.bin", "data/copy.bin", "data/$(ResourceInjection).bin",
                     "data/@(Injected).bin", "data/a;b.bin", "data/quote'&snowman\u2603.bin",
                     "culture/data.fr.txt", "data/a,b.bin", "data/space inside.bin",
                     "data/[a]=`b.bin", "data/empty.bin", "data/utf8.txt"]
            payloads = [b"\x00\xff\xfe\x80\n"] * (len(names) - 2) + [b"", "Hallo \u2603\n".encode()]
            rows = [{"path": name, "source": "assets/" + str(number) + ".bin",
                     "mediaType": "application/octet-stream"} for number, name in enumerate(names)]
            files = {guest_resources.MANIFEST: encode({"schemaVersion": guest_resources.PROFILE, "resources": rows}),
                     **{row["source"]: payload for row, payload in zip(rows, payloads)},
                     "private.txt": b"unselected bytes"}
            expected = dict(zip(names, [payload.hex() for payload in payloads]))
            (project / "Capsule.csproj").write_bytes(b'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                b'<OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><Nullable>enable</Nullable>'
                b'<EnableDefaultCompileItems>false</EnableDefaultCompileItems><ResourceInjection>expanded</ResourceInjection>'
                b'</PropertyGroup><ItemGroup><Compile Include="Program.cs"/><Injected Include="expanded-item"/>'
                b'</ItemGroup></Project>')
            (project / "global.json").write_bytes(encode({"sdk": {"version": SDK_VERSION, "rollForward": "disable"}}))
            (project / "nuget.config").write_bytes(b'<configuration><packageSources><clear/></packageSources></configuration>')
            (project / "packages.lock.json").write_bytes(encode({"version": 1, "dependencies": {"net10.0": {}}}))
            program = '''using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;
var expected = JsonSerializer.Deserialize<System.Collections.Generic.Dictionary<string,string>>(EXPECTED)!;
var assembly = Assembly.GetExecutingAssembly();
if (!assembly.GetManifestResourceNames().OrderBy(x=>x,StringComparer.Ordinal).SequenceEqual(expected.Keys.OrderBy(x=>x,StringComparer.Ordinal))) throw new Exception("name inventory differs");
if (assembly.GetManifestResourceStream("missing.bin") != null || assembly.GetManifestResourceStream("private.txt") != null) throw new Exception("unselected lookup succeeded");
foreach (var pair in expected) {
    var bytes = Convert.FromHexString(pair.Value);
    var info = assembly.GetManifestResourceInfo(pair.Key) ?? throw new Exception("resource metadata absent");
    if ((info.ResourceLocation & ResourceLocation.Embedded) == 0) throw new Exception("resource is not embedded");
    for (var iteration=0; iteration<8; iteration++) {
        using var first = assembly.GetManifestResourceStream(pair.Key) ?? throw new Exception("resource absent");
        using var second = assembly.GetManifestResourceStream(pair.Key) ?? throw new Exception("second resource absent");
        if (!first.CanRead || !first.CanSeek || first.CanWrite || second.Position != 0) throw new Exception("stream semantics differ");
        first.ReadByte();
        if (second.Position != 0) throw new Exception("streams share position");
        first.Dispose();
        using var copy = new MemoryStream();
        second.CopyTo(copy);
        if (!copy.ToArray().SequenceEqual(bytes)) throw new Exception("resource bytes differ");
        try { first.ReadByte(); throw new Exception("disposed stream readable"); } catch (ObjectDisposedException) {}
    }
}
Console.WriteLine(JsonSerializer.Serialize(new { schemaVersion="lsf.dotnet.standard-resource-result.v1", resourceNames=expected.Keys.OrderBy(x=>x,StringComparer.Ordinal).ToArray(), count=expected.Count, iterations=8, independentStreams=true, closedStreams=true }));
'''.replace("EXPECTED", json.dumps(json.dumps(expected, ensure_ascii=True, separators=(",", ":")), ensure_ascii=True))
            (project / "Program.cs").write_text(program, encoding="utf-8")
            embedded = install(files, project)
            captured = snapshot(project)
            write_json(output / "embedded-resource-inputs.json", embedded.observation)
            for name, payload in captured.items():
                destination = output / "captured-project" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
            stage = "locked-restore"
            commands.run(stage, dotnet, "restore", project / "Capsule.csproj", "--configfile", project / "nuget.config",
                         "--locked-mode", "--packages", temporary / "nuget", "--disable-parallel", "-p:NuGetAudit=false")
            stage = "msbuild"
            commands.run(stage, dotnet, "build", project / "Capsule.csproj", "-c", "Release", "--no-restore",
                         "-nodeReuse:false", "-p:UseSharedCompilation=false")
            stage = "standard-lookup"
            result = json.loads(commands.run(stage, dotnet, project / "bin/Release/net10.0/Capsule.dll"))
            if result != {"schemaVersion": "lsf.dotnet.standard-resource-result.v1", "resourceNames": sorted(names),
                          "count": len(names), "iterations": 8, "independentStreams": True, "closedStreams": True}:
                raise ValueError("actual standard resource result differs from the maintained profile")
            stage = "recheck"
            embedded.check_unchanged()
            if any(read_file(project / name) != value for name, value in captured.items()):
                raise ValueError("observed resource qualification source changed")
            if compiler_inputs != tree_identity(roots) or executable != file_identity(dotnet, "dotnet"):
                raise ValueError("observed .NET compiler inputs changed")
            if recipe != {name: digest(read_file(ROOT / name)) for name in HELPERS}:
                raise ValueError("resource qualification recipe changed")
            record = {"schemaVersion": SCHEMA, "status": "passed", "compiler": "dotnet-msbuild-roslyn-host",
                      "sdkVersion": SDK_VERSION, "seconds": round(time.monotonic() - started, 6),
                      "result": result, "embeddedResourceInputs": embedded.observation, "recipeInputs": recipe,
                      "compilerInputsDigest": digest(encode(compiler_inputs)), "executable": executable,
                      "sourceAndToolsUnchanged": True, "nativeAotGuest": False, "signedInvocations": 0,
                      "scratchStorage": "unsupported", "commands": commands.records}
            write_json(output / "STANDARD-RESOURCE-COMPLETE.json", record)
            return record
    except BaseException as error:
        write_json(output / "STANDARD-RESOURCE-FAILED.json", {"schemaVersion": SCHEMA, "stage": stage,
            "reason": str(error) if isinstance(error, ValueError) else type(error).__name__,
            "nativeAotGuest": False, "signedInvocations": 0, "commands": commands.records if commands else []})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotnet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record = run(args.dotnet, args.output)
    print(json.dumps({key: record[key] for key in ("status", "sdkVersion", "seconds", "nativeAotGuest", "signedInvocations")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
