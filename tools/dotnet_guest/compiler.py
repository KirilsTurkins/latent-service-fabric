"""Pinned C# NativeAOT build with exact WIT and closed, explicitly clocked WASI."""
from __future__ import annotations
import json
from pathlib import Path
import platform
import re
import shlex
import shutil
import sys
import tempfile
from tools.build_observation import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot, write_json
from tools.dotnet_guest.sdk import install as install_sdk

SDK_VERSION = "10.0.100"
COMPONENT_VERSION = "0.8.0-preview00011"


def runtime_inputs(root: Path) -> bytes:
    files = {"sdk/dotnet-guest/runtime/" + name: value
             for name, value in snapshot(root / "sdk/dotnet-guest/runtime").items()}
    for name in ("Cargo.toml", "Cargo.lock", "tools/toolchain-smoke/examples/dotnet_closed_runtime.rs"):
        files[name] = read_file(root / name)
    return inventory(files)


def tree_identity(roots: dict[str, Path]) -> dict:
    rows, total = [], 0
    for prefix, root in sorted(roots.items()):
        if not root.is_dir() or root.is_symlink():
            raise ValueError("compiler input root is not a regular directory:" + prefix)
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                resolved = path.resolve(strict=True)
                if resolved != root and root not in resolved.parents:
                    raise ValueError("compiler input symlink leaves the captured tool root")
                # The canonical target is also inventoried under this root;
                # preserve the logical link identity without following a cycle.
                target = resolved.relative_to(root).as_posix().encode()
                rows.append({"path": prefix + "/" + path.relative_to(root).as_posix(),
                             "digest": digest(target), "size": len(target), "kind": "symlink"})
                total += len(target)
                if len(rows) > 65536 or total > 4 * 1024**3:
                    raise ValueError("finite .NET compiler input closure exceeded")
                continue
            if path.is_dir():
                continue
            row = file_identity(path, "compiler-file", 512 * 1024 * 1024) if path.stat().st_size else {
                "digest": digest(read_file(path)), "size": 0}
            total += row["size"]
            rows.append({"path": prefix + "/" + path.relative_to(root).as_posix(), "digest": row["digest"], "size": row["size"]})
            if len(rows) > 65536 or total > 4 * 1024**3:
                raise ValueError("finite .NET compiler input closure exceeded")
    return {"files": rows, "bytes": total}


def packages(lock: dict, directory: Path, content_hash) -> dict[str, Path]:
    result = {}
    for target in lock["dependencies"].values():
        for name, value in target.items():
            identity = name.lower() + "/" + value["resolved"]
            path = directory / identity
            archive = path / (name.lower() + "." + value["resolved"] + ".nupkg")
            if not archive.is_file() or archive.is_symlink() or archive.stat().st_size > 512 * 1024 * 1024:
                raise ValueError("missing or oversized locked NuGet archive:" + identity)
            if content_hash(archive) != value["contentHash"]:
                raise ValueError("NuGet content hash differs from the exact dependency lock:" + identity)
            result["nuget/" + identity] = path
    return result


class Compiler:
    def __init__(self, tools: Path, commands, vendor: Path, *, offline: bool = False):
        if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
            raise ValueError("the pinned NativeAOT LLVM compiler is qualified only on Linux x86-64")
        self.tools, self.commands, self.vendor = tools.resolve(strict=True), commands, vendor
        self.offline = offline
        self.sdk = vendor / "sdk/dotnet-guest"
        self.dotnet = Path(shutil.which("dotnet", path=commands.environment["PATH"]) or "missing-dotnet").resolve(strict=True)
        self.wasm = Path(shutil.which("wasm-tools", path=commands.environment["PATH"]) or "missing-wasm-tools").resolve(strict=True)
        self.bindgen = Path(shutil.which("wit-bindgen", path=commands.environment["PATH"]) or "missing-wit-bindgen").resolve(strict=True)
        commands.environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1",
            DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1", DOTNET_CLI_HOME=str(tools / "cli-home"), DOTNET_ROLL_FORWARD="Disable",
            NUGET_PACKAGES=str(tools / "packages"), LSF_WIT_BINDGEN=str(self.bindgen), LSF_WASM_TOOLS=str(self.wasm),
            DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE="true", MSBUILDDISABLENODEREUSE="1",
            DOTNET_CLI_USE_MSBUILD_SERVER="0", DOTNET_EnableDiagnostics="0", DOTNET_EnableDiagnostics_IPC="0",
            LC_ALL="C.UTF-8", LANG="C.UTF-8")
        if commands.run("dotnet-version", self.dotnet, "--version").strip() != SDK_VERSION.encode():
            raise ValueError(".NET SDK 10.0.100 is required")
        if commands.run("wasm-tools-version", self.wasm, "--version").split()[:2] != [b"wasm-tools", b"1.254.0"]:
            raise ValueError("unreviewed component validator")
        if commands.run("wit-bindgen-version", self.bindgen, "--version").strip() != b"wit-bindgen-cli 0.62.0":
            raise ValueError("unreviewed WIT generator")
        sdks = commands.run("dotnet-sdks", self.dotnet, "--list-sdks").decode()
        matches = re.findall(r"(?m)^10\.0\.100 \[(.+)\]$", sdks)
        if len(matches) != 1:
            raise ValueError("unique pinned .NET SDK location required")
        installation = Path(matches[0]).parent
        self.roots = {"dotnet-sdk": Path(matches[0]) / SDK_VERSION,
                      "dotnet-runtime": installation / "shared/Microsoft.NETCore.App/10.0.0",
                      "dotnet-ref": installation / "packs/Microsoft.NETCore.App.Ref/10.0.0",
                      "dotnet-hostfxr": installation / "host/fxr"}
        self.roots["package-hash"] = tools / "package-hash"
        if snapshot(tools / "package-hash-source") != snapshot(self.sdk / "tools/package-hash"):
            raise ValueError("NuGet content-hash source differs from the captured SDK")
        self.roots.update(packages(json.loads(read_file(self.sdk / "probes/smoke/packages.lock.json")), tools / "packages",
            lambda archive: commands.run("nuget-content-hash", self.dotnet, tools / "package-hash/PackageHash.dll", archive).decode().strip()))
        self.wasi_sdk = Path(json.loads(read_file(tools / "wasi-sdk.json"))["path"]).resolve(strict=True)
        if read_file(self.wasi_sdk / "VERSION").decode().splitlines() != [
                "29.0", "wasi-libc: ac020b86fd44", "llvm: 222fc11f2b8f", "llvm-version: 21.1.4", "config: f992bcc08219"]:
            raise ValueError("WASI SDK compiler version drift")
        self.roots["wasi-sdk"] = self.wasi_sdk
        self.runtime = tools / "runtime.wasm"
        if read_file(tools / "runtime-inputs.json") != runtime_inputs(vendor):
            raise ValueError("installed closed runtime source capture differs from the project SDK")
        self.wac = tools / "packages/bytecodealliance.componentize.dotnet.wasm.sdk" / COMPONENT_VERSION / "tools/linux-x64/wac"
        self.materials = [file_identity(path, name) for name, path in (
            ("dotnet", self.dotnet), ("wasm-tools", self.wasm), ("wit-bindgen", self.bindgen), ("closed-runtime", self.runtime))]
        self.before = tree_identity(self.roots)

    def compile(self, work: Path, world: str, output: Path):
        output.mkdir()
        command, source = self.commands, work / "wit"
        generated = output / "generated"
        binding = work / "vendor/lsf/tools/dotnet_guest_bindings.py"
        command.run("bindings", sys.executable, "-I", "-B", binding, "c-sharp", source, "--world", world,
            "--runtime", "native-aot", "--with-wit-results", "--out-dir", generated)
        command.run("bindings-drift", sys.executable, "-I", "-B", binding, "c-sharp", source, "--world", world,
            "--runtime", "native-aot", "--with-wit-results", "--out-dir", generated, "--check")
        receipt = json.loads(read_file(generated / "bindings.json", 16 * 1024 * 1024))
        project = output / "project"
        project.mkdir()
        for name, data in snapshot(work / "src").items():
            if not name.endswith(".cs"):
                raise ValueError("unsupported C# application input; put sources in src/*.cs")
            path = project / "src" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for name, data in {
            "Capsule.csproj": read_file(work / "Capsule.csproj"),
            "global.json": read_file(self.sdk / "global.json"),
            "nuget.config": read_file(self.sdk / "nuget.config"),
            "packages.lock.json": read_file(self.sdk / "probes/smoke/packages.lock.json"),
            "component.wit": command.run("canonical-wit", self.wasm, "component", "wit", source, "--no-docs"),
        }.items():
            (project / name).write_bytes(data)
        facades = install_sdk(self.sdk, generated, project / "lsf")
        if self.offline:
            # All locked packages must already be present. An empty source list
            # prohibits restore from silently reaching the network on a miss.
            (project / "nuget.config").write_text(
                '<configuration><packageSources><clear /></packageSources></configuration>\n', encoding="utf-8")
        command.run("locked-restore", self.dotnet, "restore", project / "Capsule.csproj", "--configfile",
            project / "nuget.config", "--locked-mode", "--packages", self.tools / "packages", "--disable-parallel",
            "-p:NuGetAudit=false")
        # The upstream SDK interpolates WitBindgenExe into a shell Exec task.
        # Give it one ASCII-only owned path. Actual Python/source paths remain
        # literal quoted arguments, including spaces, Unicode and metacharacters.
        # This finite wrapper is private and retired after the owned process.
        with tempfile.TemporaryDirectory(prefix="lsf-dotnet-bindgen-", dir="/tmp") as wrapper_root:
            wrapper = Path(wrapper_root) / "wit-bindgen"
            script = "#!/bin/sh\nexec " + shlex.join([sys.executable, "-I", "-B", str(binding)]) + ' "$@"\n'
            if len(script.encode()) > 16384:
                raise ValueError("binding wrapper path limit exceeded")
            wrapper.write_text(script, encoding="utf-8")
            wrapper.chmod(0o700)
            command.run("native-aot", self.dotnet, "build", project / "Capsule.csproj", "-c", "Release", "--no-restore",
                "-nodeReuse:false", "-p:UseSharedCompilation=false", "-p:WasiSdkRoot=" + str(self.wasi_sdk),
                "-p:WitBindgenExe=" + str(wrapper))
        actual = list((project / "obj").rglob("bindings.json"))
        if len(actual) != 1 or json.loads(read_file(actual[0], 16 * 1024 * 1024))["outputs"] != receipt["outputs"]:
            raise ValueError("actual NativeAOT binding inputs differ from independent drift generation")
        raw = project / "bin/Release/net10.0/wasi-wasm/publish/Capsule.wasm"
        component = output / "component.wasm"
        command.run("closed-runtime-composition", self.wac, "plug", raw, "--plug", self.runtime, "-o", component)
        command.run("validate", self.wasm, "validate", component)
        surface = command.run("surface", self.wasm, "component", "wit", component).decode()
        if "import wasi:" in surface or "wasi_snapshot_preview1" in surface:
            raise ValueError("ambient WASI import survived the closed runtime composition")
        (output / "component.wit").write_text(surface, encoding="utf-8")
        return component, {"bindings": receipt, "capabilities": facades,
            "filesDigest": digest(json.dumps(receipt["outputs"], sort_keys=True).encode())}

    def check_unchanged(self):
        if tree_identity(self.roots) != self.before:
            raise ValueError("observed .NET compiler inputs changed during build")
        after = [file_identity(path, name) for name, path in (
            ("dotnet", self.dotnet), ("wasm-tools", self.wasm), ("wit-bindgen", self.bindgen), ("closed-runtime", self.runtime))]
        if after != self.materials:
            raise ValueError(".NET compiler or runtime adapter changed during build")
