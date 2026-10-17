"""Source-bound finite error messages in the captured WASI System.Net.Http BCL.

No application handler, package-name routing, runtime executor or authority is
introduced. The shared locked framework assembly stays immutable. A private
derived assembly is bound into the existing NativeAOT reference list only for
the explicitly declared candidate standard HTTP profile.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
import xml.etree.ElementTree as XML

from tools.build_observation import file_identity
from tools.dotnet_guest import runtime
from tools.rust_capsule_project import digest, inventory, read_file, snapshot, write_json

SOURCE_DIGEST = "sha256:3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587"
CECIL_DIGEST = "sha256:2590bbe9492beef92f4dc1a34513d7ddafaeb6ab91eb618b84f6ee6c2b9c46d7"
MAX_ASSEMBLY = 512 * 1024
MAX_RECEIPT = 64 * 1024
MAX_RSP = 1024 * 1024
MARKERS = tuple("latent-http-" + value for value in (
    "request-too-large", "response-too-large", "deadline-exceeded", "cancelled",
    "budget-exhausted", "tls-failed", "connection-failed", "unavailable", "uncertain", "invalid-state"))
PACKAGE = "runtime.wasi-wasm.microsoft.dotnet.ilcompiler.llvm/10.0.0-rc.1.26306.1/runtimes/wasi-wasm"
METHOD = "System.String System.Net.Http.WasiHttpInterop::ErrorCodeToString(WasiHttpWorld.wit.imports.wasi.http.v0_2_0.ITypes/ErrorCode)"

SYNC_READ = {
    "profile": "dotnet-wasi-sync-response-read-v1",
    "method": "System.Int32 System.Net.Http.WasiInputStream::Read(System.Byte[],System.Int32,System.Int32)",
    "asyncMethod": "System.Threading.Tasks.Task`1<System.Int32> System.Net.Http.WasiInputStream::ReadAsync(System.Byte[],System.Int32,System.Int32,System.Threading.CancellationToken)",
    "modifiedOriginalMethods": 1,
    "completion": "original-ReadAsync-TaskAwaiter",
    "bufferValidation": "original-Stream.ValidateBufferArguments",
    "emptyRead": "zero-without-provider-contact",
    "disposal": "original-ObjectDisposedException.ThrowIf",
    "generatedHelpers": 0,
    "newHostImports": 0,
    "defaultClientComponentQualified": False,
}


def validate_sync_read(value: dict) -> None:
    digests = {"originalReadBodyDigest", "originalAsyncBodyDigest"}
    if (type(value) is not dict or set(value) != set(SYNC_READ) | digests | {"unchangedOriginalMethods"}
            or any(type(value.get(key)) is not type(expected) or value[key] != expected
                   for key, expected in SYNC_READ.items())
            or any(type(value.get(key)) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value[key]) is None
                   for key in digests)
            or type(value.get("unchangedOriginalMethods")) is not int
            or not 500 <= value["unchangedOriginalMethods"] <= 10000):
        raise ValueError("http-sync-read-rewrite-receipt")


def source_paths(tools: Path) -> tuple[Path, Path]:
    return tuple(tools / "packages" / PACKAGE / folder / "System.Net.Http.dll"
                 for folder in ("lib", "native-hidden"))


def cecil_path(tools: Path) -> Path:
    return tools / "packages/microsoft.net.illink.tasks/10.0.0/tools/net/Mono.Cecil.dll"


def require_digest(path: Path, expected: str, name: str) -> dict:
    identity = file_identity(path, name, MAX_ASSEMBLY)
    if identity["digest"] != expected:
        raise ValueError("http-error-port-unsupported-material:" + name)
    return identity


def install(sdk: Path, tools: Path, dotnet: Path, run) -> None:
    source = tools / "http-errors-source"
    source.mkdir(mode=0o700)
    before = snapshot(sdk / "tools/http-errors")
    for name, data in before.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    cecil = cecil_path(tools)
    require_digest(cecil, CECIL_DIGEST, "http-error-cecil")
    for path in source_paths(tools):
        require_digest(path, SOURCE_DIGEST, "http-error-framework")
    config = tools / "http-errors-nuget.config"
    config.write_text('<configuration><packageSources><clear /></packageSources></configuration>\n', encoding="utf-8")
    run("http-errors-build", dotnet, "build", source / "HttpErrors.csproj", "-c", "Release",
        "--output", tools / "http-errors", "--artifacts-path", tools / "http-errors-artifacts",
        "-p:LsfCecilPath=" + str(cecil), "-p:RestoreConfigFile=" + str(config),
        "-p:NuGetAudit=false", "-nodeReuse:false")
    if snapshot(sdk / "tools/http-errors") != before or snapshot(source) != before:
        raise ValueError("http-error-port-source-changed-during-build")
    require_digest(tools / "http-errors/Mono.Cecil.dll", CECIL_DIGEST, "http-error-cecil")


def verify_installed(sdk: Path, tools: Path) -> dict:
    if snapshot(tools / "http-errors-source") != snapshot(sdk / "tools/http-errors"):
        raise ValueError("http-error-port-installed-source-drift")
    require_digest(tools / "http-errors/Mono.Cecil.dll", CECIL_DIGEST, "http-error-cecil")
    return file_identity(tools / "http-errors/HttpErrors.dll", "dotnet-http-errors-tool", MAX_ASSEMBLY)


def msbuild_literal(path: Path) -> str:
    # MSBuild escapes must be applied before XML serialization. User/tool paths
    # are literal file identities, not property, item or wildcard expressions.
    value = str(path)
    if len(value) > 4096 or any(ord(char) < 32 for char in value):
        raise ValueError("http-error-port-path-limit")
    for char, escaped in (("%", "%25"), ("$", "%24"), ("@", "%40"), (";", "%3B"),
                          ("*", "%2A"), ("?", "%3F"), ("'", "%27"), ("(", "%28"), (")", "%29")):
        value = value.replace(char, escaped)
    return value


@dataclass
class HttpErrorPort:
    source: Path
    originals: tuple[Path, Path]
    assembly: Path
    retained: Path
    targets: Path
    reference_receipt: Path
    identity: dict
    source_identity: bytes
    target_identity: bytes
    evidence: dict
    task_wait_port: object | None = None

    def recheck(self) -> None:
        if self.task_wait_port is not None:
            self.task_wait_port.recheck()
            if self.evidence["synchronousRead"]["taskWaitDerivedDigest"] != self.task_wait_port.identity["digest"]:
                raise ValueError("http-sync-read-CoreLib-identity-drift")
        if inventory(snapshot(self.source)) != self.source_identity:
            raise ValueError("http-error-port-source-input-changed")
        for path in self.originals:
            require_digest(path, SOURCE_DIGEST, "http-error-framework")
        if file_identity(self.assembly, "dotnet-http-errors-derived", MAX_ASSEMBLY) != self.identity:
            raise ValueError("http-error-port-derived-input-changed")
        if file_identity(self.retained, "dotnet-http-errors-derived", MAX_ASSEMBLY) != self.identity:
            raise ValueError("http-error-port-retained-input-changed")
        if read_file(self.targets, MAX_RECEIPT) != self.target_identity:
            raise ValueError("http-error-port-target-changed")

    def finish(self, project: Path, evidence: Path) -> dict:
        self.recheck()
        references = read_file(self.reference_receipt, MAX_RECEIPT).decode("utf-8-sig").splitlines()
        if not 1 <= len(references) <= 512 or references.count(str(self.assembly)) != 1:
            raise ValueError("http-error-port-reference-binding")
        if any(Path(path).name == "System.Net.Http.dll" and path != str(self.assembly) for path in references):
            raise ValueError("http-error-port-original-reference-survived")
        responses = list((project / "obj").rglob("*.rsp"))
        if len(responses) > 64:
            raise ValueError("http-error-port-response-file-count")
        matched, total = [], 0
        for path in responses:
            body = read_file(path, MAX_RSP)
            total += len(body)
            if total > 4 * MAX_RSP:
                raise ValueError("http-error-port-response-file-bytes")
            lines = body.decode("utf-8-sig").splitlines()
            http_references = [line[3:] for line in lines
                               if line.startswith("-r:") and Path(line[3:].strip('"')).name == "System.Net.Http.dll"]
            if http_references:
                if http_references != [str(self.assembly)]:
                    raise ValueError("http-error-port-native-aot-reference-drift")
                if self.task_wait_port is not None:
                    core_references = [line[3:] for line in lines if line.startswith("-r:") and
                        Path(line[3:].strip('"')).name == "System.Private.CoreLib.dll"]
                    if core_references != [str(self.task_wait_port.assembly)]:
                        raise ValueError("http-sync-read-joined-CoreLib-reference-drift")
                matched.append({"digest": digest(body), "size": len(body)})
        if len(matched) != 1:
            raise ValueError("http-error-port-native-aot-reference-not-observed")
        result = {**self.evidence, "nativeAotReferenceBinding": {
            "referenceListDigest": digest(read_file(self.reference_receipt, MAX_RECEIPT)),
            "responseFiles": matched}, "defaultClientComponentQualified": False}
        write_json(evidence / "http-error-port.json", result)
        return result


def prepare(sdk: Path, tools: Path, dotnet: Path, declared: list[str], project: Path,
            output: Path, evidence: Path, run, *, protect_inputs=None, task_wait_port=None) -> HttpErrorPort | None:
    if not {runtime.CLOCK, runtime.HTTP, runtime.ACTIVATION} <= set(declared):
        return None
    if task_wait_port is not None:
        # No source-only opt-in: the separately authenticated CoreLib must have
        # been prepared successfully and remain immutable through the build.
        from tools.dotnet_guest.task_wait import Port
        if type(task_wait_port) is not Port:
            raise ValueError("http-sync-read-authenticated-task-wait-required")
        task_wait_port.recheck()
        if inventory(snapshot(sdk / "tools/http-errors")) != task_wait_port.source_identity:
            raise ValueError("http-sync-read-task-wait-source-drift")
    tool = verify_installed(sdk, tools)
    originals = source_paths(tools)
    sources = [require_digest(path, SOURCE_DIGEST, "http-error-framework") for path in originals]
    owned = output / "http-error-port"
    owned.mkdir(mode=0o700)
    assembly, targets = owned / "System.Net.Http.dll", owned / "HttpErrors.targets"
    receipt = owned / "rewrite.json"
    target_identity = read_file(sdk / "tools/http-errors/HttpErrors.targets", MAX_RECEIPT)
    targets.write_bytes(target_identity)
    source_identity = inventory(snapshot(sdk / "tools/http-errors"))
    mode = ("--sync-read",) if task_wait_port is not None else ()
    run("http-errors-rewrite", dotnet, tools / "http-errors/HttpErrors.dll", *mode, originals[0], assembly, receipt)
    result = json.loads(read_file(receipt, MAX_RECEIPT))
    if (set(result) != {"patch", "sourceDigest", "outputDigest", "cecilDigest", "method", "categories",
                       "arbitraryPayloadDisclosure", "defaultClientComponentQualified"} |
                       ({"synchronousRead"} if task_wait_port is not None else set())
            or result["patch"] != "latent.dotnet.http-errors.v1" or result["sourceDigest"] != SOURCE_DIGEST
            or result["cecilDigest"] != CECIL_DIGEST or result["categories"] != list(MARKERS)
            or result["method"] != METHOD
            or result["arbitraryPayloadDisclosure"] is not False or result["defaultClientComponentQualified"] is not False):
        raise ValueError("http-error-port-rewrite-receipt")
    if task_wait_port is not None:
        validate_sync_read(result["synchronousRead"])
        task_wait_port.recheck()
    identity = file_identity(assembly, "dotnet-http-errors-derived", MAX_ASSEMBLY)
    if identity["digest"] != result["outputDigest"]:
        raise ValueError("http-error-port-rewrite-output-drift")
    retained = evidence / "derived-System.Net.Http.dll"
    with retained.open("xb") as destination:
        destination.write(read_file(assembly, MAX_ASSEMBLY))
    if protect_inputs is not None:
        # Derived framework inputs stay immutable in the compiler namespace,
        # including while approved NuGet build code runs in its owned workspace.
        protect_inputs(assembly, targets)
    reference_receipt = owned / "native-aot-references.txt"
    document = XML.fromstring(read_file(project / "Capsule.csproj", MAX_RECEIPT))
    properties = XML.SubElement(document, "PropertyGroup")
    for name, path in (("LsfHttpErrorOriginalPublic", originals[0]), ("LsfHttpErrorOriginalPrivate", originals[1]),
                       ("LsfHttpErrorAssembly", assembly), ("LsfHttpErrorReferenceReceipt", reference_receipt)):
        XML.SubElement(properties, name).text = msbuild_literal(path)
    XML.SubElement(document, "Import", Project=msbuild_literal(targets))
    (project / "Capsule.csproj").write_bytes(XML.tostring(document, encoding="utf-8", xml_declaration=True))
    captured = {**result, "frameworkInputs": sources, "tool": tool, "sourceCaptureDigest": digest(source_identity),
                "targetsDigest": digest(target_identity), "derived": identity, "nativeAotReferenceBinding": None}
    if task_wait_port is not None:
        captured["synchronousRead"] = {**result["synchronousRead"],
            "taskWaitDerivedDigest": task_wait_port.identity["digest"]}
    write_json(evidence / "http-error-port-preparation.json", captured)
    return HttpErrorPort(sdk / "tools/http-errors", originals, assembly, retained, targets, reference_receipt, identity,
                         source_identity, target_identity, captured, task_wait_port)
