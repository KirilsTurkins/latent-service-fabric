#!/usr/bin/env python3
"""Build a native Windows/Linux frontend and Linux helper, without publishing."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import zipfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_workflow.common import HOST_ABI, PROTOCOL, digest, encode, require
from tools.dev_distribution import file_digest, frontend_files, project_notices

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_RESOURCES = (
    "schemas/node-providers.schema.json",
    "schemas/outbound-stream-provider.schema.json",
    "schemas/outbound-stream-rotation.schema.json",
    "schemas/dev-composition-input.schema.json",
    "schemas/static-site-budget.schema.json",
    "contracts/dev/composition-support-v1.json",
    "contracts/http/browser-response-ownership-v1.json",
)


def preflight_resources() -> tuple[tuple[str, bytes], ...]:
    """Snapshot the canonical contracts verbatim; no computed schema copy."""
    result = []
    for name in PREFLIGHT_RESOURCES:
        try:
            with (ROOT / name).open("rb") as source:
                raw = source.read(65537)
        except OSError as error:
            raise ValueError("frontend-preflight-contract-required") from error
        require(0 < len(raw) <= 65536, "frontend-preflight-contract-bound")
        result.append((name, raw))
    return tuple(result)


def preflight_input() -> dict:
    """Synthetic structural selection; contains no real publication or authority."""
    identity = "sha256:" + "1" * 64
    return {"schemaVersion": "latent.composition.v1", "tenant": "packaging-test",
        "nodeProfile": {"id": "static-site-v1", "javaGuest": False,
            "maximumWirePayloadBytes": "2097152", "maximumRequestBodyBytes": "65536",
            "maximumResponseBodyBytes": "65536"},
        "components": [{"id": "site", "packageDigest": identity, "assetsDigest": identity,
            "webManifestDigest": identity, "language": "static", "witShape": "static-assets-v1",
            "publicationKind": "static-site", "target": {"publicationId": "publication:" + identity,
                "webGeneration": "1"}, "imports": [], "exports": []}],
        "triggers": [{"kind": "static", "component": "site"}], "serviceEdges": [], "providers": [], "policies": []}


def preflight_smoke_cases() -> tuple:
    """Finite positive/context/header declarations used by the native smoke."""
    import copy
    selected = preflight_input()
    context = copy.deepcopy(selected)
    capsule = context["components"][0]
    identity = capsule["packageDigest"]
    capsule.pop("assetsDigest")
    capsule.pop("webManifestDigest")
    capsule.update(language="java", witShape="nested-values-v1", publicationKind="capsule",
        componentDigest=identity, releaseDigest=identity, contractMetadataDigest=identity,
        imports=["latent:context/context@0.1.0"],
        exports=[{"contract": "example:packaging/app@1.0.0", "functions": ["run"]}],
        target={"service": "packaging-test", "route": "packaging-test", "revision": "revision-v1:" + identity,
            "publicationId": "publication:" + identity, "deploymentId": "packaging-test", "deploymentGeneration": "1",
            "contract": "example:packaging/app@1.0.0", "function": "run"},
        budget={name: None if name == "wallTimeLimitMillis" else "1" for name in (
            "cpuFuel", "memoryBytes", "wallTimeLimitMillis", "childCalls", "outboundRequests",
            "stateReadBytes", "stateWriteBytes", "blobReadBytes", "blobWriteBytes", "logBytes", "effectCount")})
    context["nodeProfile"].update(id="standalone-java-v1", javaGuest=True)
    context["triggers"] = [{"kind": "typed", "component": "site", "contract": "example:packaging/app@1.0.0", "function": "run"}]
    header = copy.deepcopy(selected)
    header["components"][0].update(headerNames=["referrer-policy"], dynamicHeaders=True)
    return (("closed-static", selected, 0, None),
        ("ordinary-context-unavailable", context, 3, "ordinary-context-provider-not-installed"),
        ("reserved-header", header, 3, "declared-response-header-ownership"))


def preflight_smoke(command: list[str]) -> dict:
    """Run real packaged command paths outside the checkout with no Python PATH."""
    import os
    import tempfile
    cases = preflight_smoke_cases()
    with tempfile.TemporaryDirectory(prefix="lsf-native-preflight-smoke-") as temporary:
        directory = Path(temporary)
        state_root = directory / "uncreated-controller"
        source = directory / "composition.json"
        environment = {"TEMP": temporary, "TMP": temporary, "TMPDIR": temporary, "HOME": temporary,
            "LOCALAPPDATA": str(directory / "uncreated-local-appdata"), "PATH": temporary, "LANG": "C.UTF-8"}
        if sys.platform == "win32":
            environment.update(SystemRoot=os.environ["SystemRoot"], WINDIR=os.environ["WINDIR"],
                               PATH=str(Path(os.environ["SystemRoot"]) / "System32"))
        for _name, value, expected, reason in cases:
            source.write_bytes(encode(value))
            completed = subprocess.run([*command, "--state-root", str(state_root), "dev", "preflight", "--input", str(source)],
                cwd=directory, env=environment, capture_output=True, timeout=30)
            require(completed.returncode == expected and len(completed.stdout) <= 262144
                and not completed.stderr, "packaged-frontend-preflight-command-failed")
            result = json.loads(completed.stdout)
            require(result.get("schemaVersion") == "latent.dev.result.v1"
                and result.get("code") == ("success" if expected == 0 else "composition-checks-failed"),
                "packaged-frontend-preflight-result-failed")
            result = result["result"]
            require(result.get("schemaVersion") == "latent.composition.preflight.v1"
                and result.get("passed") is (expected == 0) and all(result.get(name) is False for name in (
                    "fullyChecked", "executionAuthorized", "grantCreated", "reservationCreated", "trafficEnabled")),
                "packaged-frontend-preflight-authority-failed")
            if reason:
                require(any(row["code"] == reason and row["state"] in {"failed", "unsupported"}
                    for row in result["checks"]), "packaged-frontend-preflight-rejection-missing")
            require(set(directory.iterdir()) == {source}, "packaged-frontend-preflight-created-state")
    return {"passed": True, "cases": [name for name, *_ in cases], "outsideCheckout": True,
        "controllerStateCreated": False, "qualification": "packaged-structural-preflight-only"}



def stream_operator_smoke(command: list[str]) -> dict:
    """Execute actual packaged preparation with an explicit Python node double.

    This checks packaging, protected files and process ownership. It supplies no
    real latentd installation, stream transport or provider readiness evidence.
    """
    import tempfile
    import os
    with tempfile.TemporaryDirectory(prefix="lsf-stream-operator-smoke-") as temporary:
        root = Path(temporary).absolute()
        root.chmod(0o700)
        base, selected, accepted, refused = (root / name for name in
                                            ("base.json", "installation.json", "accepted.json", "refused.json"))
        settings = {"budgetProfile": {"mode": "phase3"}, "audit": {"mode": "durable"},
            "capabilityPolicies": {"formatVersion": 1},
            "credentials": [{"token": "PUBLIC-PACKAGING-CONTROL-ONLY"}],
            "providers": {"formatVersion": 1, "bindings": []}}
        installation = {"identity": {"id": "streams", "tenant": "examples", "service": "stream-host", "epoch": 1},
            "configuration": {"formatVersion": 1, "profile": "lsf-outbound-streams-v1",
                "destinations": [{"endpoint": {"host": "127.0.0.1", "port": 32123, "transport": "tcp"},
                    "addresses": {"networks": ["127.0.0.1/32"], "specialAddresses": ["127.0.0.1"]},
                    "resolution": {"kind": "static", "addresses": ["127.0.0.1"]}}],
                "limits": {"maximumTransferBytes": 65536, "idleTimeoutMillis": 1000, "absoluteTimeoutMillis": 5000}}}
        bindings = [{"name": "mail-stream", "tenant": "examples", "consumerService": "examples/mail",
            "providerService": "stream-host", "contract": "latent:network/streams@0.1.0", "providerBinding": "stream-installed"}]
        for path, value in ((base, settings), (selected, {"installation": installation, "bindings": bindings})):
            path.write_bytes(encode(value))
            path.chmod(0o600)
        # Python opens this fixed private script when invoked with check-config.
        # Its known response is a process double, never a latentd profile claim.
        check = root / "check-config"
        check.write_bytes(b"import json,sys; assert sys.argv[1]=='--config'; json.load(open(sys.argv[2])); print('PRIVATE-PROCESS-OUTPUT')\n")
        environment = {"TEMP": temporary, "TMP": temporary, "TMPDIR": temporary, "HOME": temporary,
                       "PATH": temporary, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        if sys.platform == "win32":
            environment.update(SystemRoot=os.environ["SystemRoot"], WINDIR=os.environ["WINDIR"],
                               PATH=str(Path(os.environ["SystemRoot"]) / "System32"))
        check_node = Path(sys.executable).resolve(strict=True)
        prefix = [*command, "stream-operator", "prepare", "--node", str(check_node),
                  "--base-config", str(base), "--installation-record", str(selected), "--development-profile"]
        result = subprocess.run([*prefix, "--output", str(accepted)], cwd=root, env=environment,
                                capture_output=True, timeout=45)
        require(result.returncode == 0 and not result.stderr and len(result.stdout) <= 65536,
                "packaged-stream-operator-preparation-failed")
        value = json.loads(result.stdout)
        require(value.get("schemaVersion") == "latent.outbound-stream.operator.result.v1"
                and value.get("status") == "completed", "packaged-stream-operator-result-failed")
        observed = value["result"]
        require(observed.get("executionPermission") is False and observed.get("providerReadiness") == "not-observed"
                and observed.get("nodeBinary") == dict(zip(("sha256", "size"), file_digest(check_node)))
                and b"PRIVATE" not in result.stdout and str(root).encode() not in result.stdout,
                "packaged-stream-operator-authority-or-disclosure-failed")
        prepared = json.loads(accepted.read_bytes())
        require(prepared["credentials"] == settings["credentials"]
                and prepared["providers"]["outboundStreams"] == installation,
                "packaged-stream-operator-input-not-preserved")
        check.write_bytes(b"import sys; print('PRIVATE-PROCESS-FAILURE',file=sys.stderr); raise SystemExit(2)\n")
        result = subprocess.run([*prefix, "--output", str(refused)], cwd=root, env=environment,
                                capture_output=True, timeout=45)
        require(result.returncode == 1 and not result.stdout and len(result.stderr) <= 65536
                and json.loads(result.stderr).get("code") == "stream-operator-node-check-rejected-prepared-file-retained"
                and refused.read_bytes() == accepted.read_bytes() and b"PRIVATE" not in result.stderr,
                "packaged-stream-operator-refusal-not-retained")
        require(set(root.iterdir()) == {base, selected, accepted, refused, check},
                "packaged-stream-operator-created-unexpected-state")
    return {"passed": True, "outsideCheckout": True, "cases": ["prepared", "refused-input-retained"],
            "node": "explicit-python-configuration-check-double", "realLatentd": False,
            "providerReadiness": "not-observed", "qualification": "packaged-operator-files-and-process-only"}


def python_inventory(output: Path, lock: Path) -> None:
    """Retain actual Python and bootloader license texts, including vendored terms."""
    import shutil
    import re
    licenses = output / "licenses"
    licenses.mkdir()
    python_license = next((p for p in (Path(sys.base_prefix) / "LICENSE.txt",
                          Path(sysconfig.get_path("stdlib")) / "LICENSE.txt") if p.is_file()), None)
    require(python_license is not None, "frontend-python-license-required")
    shutil.copyfile(python_license, licenses / "CPython-3.13.5.txt")
    project_notices(ROOT, licenses)
    packages = []
    for line in lock.read_text().splitlines():
        match = re.fullmatch(r"([a-z0-9-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})", line)
        require(match is not None, "frontend-wheel-lock-format")
        name, version, checksum = match.groups()
        distribution = importlib.metadata.distribution(name)
        require(distribution.version == version, "frontend-build-dependency-version")
        retained = []
        for entry in distribution.files or []:
            if (not entry.name.lower().startswith(("license", "licence", "copying", "notice"))
                    or entry.suffix.lower() in {".py", ".pyc", ".pyo"}):
                continue
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                directory = licenses / (name + "-" + version)
                directory.mkdir(exist_ok=True)
                destination = directory / (str(len(retained)) + "-" + source.name)
                shutil.copyfile(source, destination)
                retained.append(destination.relative_to(output).as_posix())
        require(retained, "frontend-dependency-license-missing-" + name)
        packages.append({"name": name, "version": version, "wheelSha256": checksum, "licenses": retained,
                         "licenseDeclared": distribution.metadata.get("License-Expression") or "NOASSERTION"})
    (output / "python-inventory.json").write_bytes(encode({"python": platform.python_version(), "packages": packages,
        "pythonLicense": "licenses/CPython-3.13.5.txt", "scope": "CPython distribution and exact frontend/runtime and bootloader dependencies"}))


def helper(output: Path, resource_snapshot=None) -> str:
    entries = {"__main__.py": b"from tools.dev_workflow.helper import main\nraise SystemExit(main())\n",
               "tools/__init__.py": b""}
    for directory in ("tools/dev_workflow", "tools/native_runtime"):
        for path in sorted((ROOT / directory).glob("*.py")):
            # Windows implementation is omitted from the Linux helper.
            if path.name == "windows.py":
                continue
            entries[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for name in ("build_process", "build_process_linux", "build_process_signals", "guest_runtime_profiles",
                 "browser_response_ownership", "guest_compatibility", "guest_compatibility_context", "guest_compatibility_outcomes", "guest_runtime_receipts",
                 "guest_compatibility_context_build", "guest_emitted_code",
                 "application_dependencies", "application_dependency_store", "application_dependency_tools",
                 "build_snapshot", "rust_capsule_project", "guest_resources", "outbound_stream_operator"):
        entries[f"tools/{name}.py"] = (ROOT / f"tools/{name}.py").read_bytes()
    entries["tools/typescript_guest/__init__.py"] = b""
    entries["tools/typescript_guest/buffer_profile.py"] = (ROOT / "tools/typescript_guest/buffer_profile.py").read_bytes()
    for name in ("net_profile", "runtime_profile"):
        entries[f"tools/typescript_guest/{name}.py"] = (ROOT / f"tools/typescript_guest/{name}.py").read_bytes()
    for name, raw in resource_snapshot if resource_snapshot is not None else preflight_resources():
        entries["tools/dev_workflow/data/" + name] = raw
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(entries.items()):
            entry = zipfile.ZipInfo(name, (2026, 9, 23, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, raw)
    return digest(output.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--helper-only", action="store_true")
    arguments = parser.parse_args()
    output = arguments.output.absolute()
    require(output.is_relative_to(ROOT / "target") and not output.exists(), "new-owned-build-directory-required")
    output.mkdir(parents=True)
    resource_snapshot = preflight_resources()
    helper_digest = helper(output / "helper.pyz", resource_snapshot)
    if arguments.helper_only:
        print(encode({"helperSha256": helper_digest}).decode(), end="")
        return 0
    require(sys.platform in {"win32", "linux"} and platform.machine().lower() in {"amd64", "x86_64"}
            and sys.version_info[:3] == (3, 13, 5), "native-x64-python-3-13-5-required")
    target = "windows-x86_64" if sys.platform == "win32" else "linux-x86_64"
    lock = ROOT / ("tools/dev-frontend-windows.lock" if sys.platform == "win32" else "tools/dev-frontend-linux.lock")
    require(importlib.metadata.version("pyinstaller") == "6.22.3", "pinned-pyinstaller-required")
    python_inventory(output, lock)
    data_arguments = []
    import os
    for name, raw in resource_snapshot:
        source = output / "preflight-data" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(raw)
        destination = "tools/dev_workflow/data/" + Path(name).parent.as_posix()
        data_arguments.extend(["--add-data", str(source) + os.pathsep + destination])
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--noupx", "--collect-data", "jsonschema_specifications", "--name", "latent-dev", "--distpath", str(output / "dist"),
        "--workpath", str(output / "work"), "--specpath", str(output), *data_arguments, str(ROOT / "tools/latent_dev.py")],
        cwd=ROOT, check=True, timeout=300)
    executable = output / "dist/latent-dev" / ("latent-dev.exe" if sys.platform == "win32" else "latent-dev")
    require(executable.is_file(), "native-frontend-output-missing")
    for name, raw in resource_snapshot:
        installed = executable.parent / "_internal/tools/dev_workflow/data" / name
        require(installed.read_bytes() == raw, "packaged-frontend-preflight-contract-changed")
    require(preflight_resources() == resource_snapshot, "frontend-preflight-contract-changed-during-build")
    preflight = preflight_smoke([str(executable)])
    stream_operator = stream_operator_smoke([str(executable)])
    native = None
    if sys.platform == "linux":
        from tools.dev_frontend_linux import collect
        native = collect(output)
    # Run the packaged binary from outside the checkout, with no Python in PATH.
    import tempfile
    import os
    with tempfile.TemporaryDirectory(prefix="lsf-native-smoke-") as temporary:
        environment = {"TEMP": temporary, "TMP": temporary, "TMPDIR": temporary, "HOME": temporary,
                       "PATH": temporary, "LANG": "C.UTF-8"}
        if sys.platform == "win32":
            environment.update(SystemRoot=os.environ["SystemRoot"], WINDIR=os.environ["WINDIR"],
                               PATH=str(Path(os.environ["SystemRoot"]) / "System32"))
        help_result = subprocess.run([str(executable), "--help"], cwd=temporary, env=environment,
                                     capture_output=True, timeout=30)
        require(help_result.returncode == 0 and b"latent-dev" in help_result.stdout, "packaged-frontend-start-failed")
        smoke = subprocess.run([str(executable), "dev", "doctor"], cwd=temporary, env=environment,
                               capture_output=True, timeout=30)
        operator_help = subprocess.run([str(executable), "stream-operator", "prepare", "--help"],
            cwd=temporary, env=environment, capture_output=True, timeout=30)
    require(operator_help.returncode == 0 and b"--installation-record" in operator_help.stdout
            and b"--development-profile" in operator_help.stdout and not operator_help.stderr,
            "packaged-frontend-stream-operator-help-failed")
    require(smoke.returncode in {0, 2} and json.loads(smoke.stdout).get("schemaVersion") == "latent.dev.result.v1",
            "packaged-frontend-doctor-failed")
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip())
    record = {"schemaVersion": "latent.dev.frontend-build.v1", "sourceCommit": source, "sourceDirty": dirty,
              "target": target, "hostAbi": HOST_ABI, "protocol": PROTOCOL,
              "frontendSha256": digest(executable.read_bytes()), "helperSha256": helper_digest,
              "python": platform.python_version(), "packager": "pyinstaller-6.22.3",
              "lockSha256": digest(lock.read_bytes()),
              "doctor": json.loads(smoke.stdout), "publisherAuthenticated": False,
              "preflight": preflight,
              "streamOperatorSmoke": stream_operator,
              "preflightResources": [{"path": name, "sha256": digest(raw), "size": len(raw)} for name, raw in resource_snapshot],
              "qualification": "native-frontend-smoke-only"}
    if native is not None:
        record["hostRequirements"] = native["hostRequirements"]
    record["files"] = frontend_files(output)
    (output / "build.json").write_bytes(encode(record))
    print(encode({**{key: value for key, value in record.items() if key != "files"},
                  "fileCount": len(record["files"])}).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
