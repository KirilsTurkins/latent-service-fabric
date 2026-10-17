#!/usr/bin/env python3
"""Execute the exact captured BCL error-port controls; no guest-client claim."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.dotnet_guest import http_errors
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, snapshot, write_json


def probe(tools: Path, output: Path) -> dict:
    tools = tools.resolve(strict=True)
    output = fresh(output)
    sdk = ROOT / "sdk/dotnet-guest"
    source = output / "source"
    source.mkdir()
    for name in ("HttpErrorsProbe.csproj", "HttpErrorsProbe.cs"):
        (source / name).write_bytes(read_file(sdk / "probes/http-errors" / name))
    (source / "global.json").write_bytes(read_file(sdk / "global.json"))
    (source / "nuget.config").write_text(
        '<configuration><packageSources><clear /></packageSources></configuration>\n', encoding="utf-8")
    environment = build_environment(output)
    environment.update(DOTNET_CLI_HOME=str(output / "cli"), DOTNET_ROLL_FORWARD="Disable",
        DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
        DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE="true", NUGET_PACKAGES=str(output / "packages"),
        MSBUILDDISABLENODEREUSE="1", DOTNET_CLI_USE_MSBUILD_SERVER="0")
    commands = Commands(source, output, environment, deadline_seconds=300, command_seconds=120)
    dotnet = shutil.which("dotnet", path=environment["PATH"])
    if not dotnet or commands.run("dotnet-version", dotnet, "--version").strip() != b"10.0.100":
        raise ValueError("http-error-probe-requires-pinned-dotnet")
    tool_identity = http_errors.verify_installed(sdk, tools)
    before = snapshot(source)
    original = http_errors.source_paths(tools)[0]
    http_errors.require_digest(original, http_errors.SOURCE_DIGEST, "http-error-framework")
    derived, receipt = output / "System.Net.Http.dll", output / "rewrite.json"
    executable = tools / "http-errors/HttpErrors.dll"
    commands.run("rewrite", dotnet, executable, original, derived, receipt)
    repeated = output / "System.Net.Http.repeated.dll"
    commands.run("repeat-rewrite", dotnet, executable, original, repeated, output / "repeat.json")
    if read_file(derived, http_errors.MAX_ASSEMBLY) != read_file(repeated, http_errors.MAX_ASSEMBLY):
        raise ValueError("http-error-probe-nondeterministic-output")
    commands.run("probe-build", dotnet, "build", source / "HttpErrorsProbe.csproj", "-c", "Release",
        "--output", output / "probe", "--artifacts-path", output / "artifacts",
        "-p:RestoreConfigFile=" + str(source / "nuget.config"), "-p:NuGetAudit=false", "-nodeReuse:false")
    result = json.loads(commands.run("actual-bcl-errors", dotnet, output / "probe/HttpErrorsProbe.dll",
        original, derived, output / "actual-bcl-errors.json"))
    if result["assertions"] != 79 or result["defaultClientComponentQualified"] is not False:
        raise ValueError("http-error-probe-assertions")

    # The error-only derivation and all 79 controls above remain independent.
    # Exercise both transformations together without claiming guest progress.
    sync_derived = output / "System.Net.Http.sync-read.dll"
    sync_receipt = output / "sync-read-rewrite.json"
    commands.run("sync-read-rewrite", dotnet, executable, "--sync-read", original, sync_derived, sync_receipt)
    rewrite = json.loads(read_file(sync_receipt, http_errors.MAX_RECEIPT))
    http_errors.validate_sync_read(rewrite["synchronousRead"])
    sync_repeated = output / "System.Net.Http.sync-read.repeated.dll"
    commands.run("sync-read-repeat", dotnet, executable, "--sync-read", original, sync_repeated,
                 output / "sync-read-repeat.json")
    if read_file(sync_derived, http_errors.MAX_ASSEMBLY) != read_file(sync_repeated, http_errors.MAX_ASSEMBLY):
        raise ValueError("http-sync-read-probe-nondeterministic-output")
    combined = json.loads(commands.run("sync-read-bounded-errors", dotnet, output / "probe/HttpErrorsProbe.dll",
        original, sync_derived, output / "sync-read-bounded-errors.json"))
    sync_result = json.loads(commands.run("actual-bcl-sync-read", dotnet, output / "probe/HttpErrorsProbe.dll",
        "--sync-read", original, sync_derived, output / "actual-bcl-sync-read.json"))
    if (combined["assertions"] != 79 or combined["defaultClientComponentQualified"] is not False
            or sync_result["assertions"] != 24 or sync_result["defaultClientComponentQualified"] is not False
            or sync_result["pendingGuestIoQualified"] is not False):
        raise ValueError("http-sync-read-probe-assertions")
    response_errors = json.loads(commands.run("actual-bcl-response-read-errors", dotnet, output / "probe/HttpErrorsProbe.dll",
        "--response-read-errors", original, sync_derived, output / "actual-bcl-response-read-errors.json"))
    if (response_errors["assertions"] != 16 or response_errors["nativeErrorDropQualified"] is not False
            or response_errors["pendingGuestIoQualified"] is not False
            or response_errors["defaultClientComponentQualified"] is not False):
        raise ValueError("http-response-read-errors-probe-assertions")

    def rejected(stage, input_path, output_path, receipt_path, *mode):
        count = len(commands.records)
        try:
            commands.run(stage, dotnet, executable, *mode, input_path, output_path, receipt_path)
        except ValueError:
            if len(commands.records) != count + 1 or commands.records[-1]["exitCode"] != 1:
                raise
        else:
            raise ValueError("http-error-probe-negative-control-accepted")

    corrupt = output / "corrupt-original.dll"
    data = bytearray(read_file(original, http_errors.MAX_ASSEMBLY))
    data[-1] ^= 1
    corrupt.write_bytes(data)
    rejected("changed-preimage", corrupt, output / "changed.dll", output / "changed.json")
    rejected("derived-is-not-an-original", derived, output / "repatched.dll", output / "repatched.json")
    sentinel = output / "existing.dll"
    sentinel.write_bytes(b"preserve-existing-output")
    rejected("existing-output", original, sentinel, output / "existing.json")
    rejected("in-place-output", original, original, output / "in-place.json")
    occupied = output / "occupied.json"
    occupied.write_bytes(b"preserve-existing-receipt")
    rejected("existing-receipt", original, output / "occupied.dll", occupied)
    rejected("sync-read-changed-preimage", corrupt, output / "sync-changed.dll", output / "sync-changed.json", "--sync-read")
    rejected("sync-read-derived-preimage", sync_derived, output / "sync-repatched.dll", output / "sync-repatched.json", "--sync-read")
    rejected("sync-read-existing-output", original, sentinel, output / "sync-existing.json", "--sync-read")
    rejected("sync-read-in-place-output", original, original, output / "sync-in-place.json", "--sync-read")
    rejected("sync-read-existing-receipt", original, output / "sync-occupied.dll", occupied, "--sync-read")
    if sentinel.read_bytes() != b"preserve-existing-output" or occupied.read_bytes() != b"preserve-existing-receipt":
        raise ValueError("http-error-probe-existing-material-changed")
    if any((output / name).exists() for name in ("changed.dll", "changed.json", "repatched.dll", "repatched.json",
                                               "existing.json", "in-place.json", "occupied.dll", "sync-changed.dll", "sync-changed.json",
                                               "sync-repatched.dll", "sync-repatched.json", "sync-existing.json",
                                               "sync-in-place.json", "sync-occupied.dll")):
        raise ValueError("http-error-probe-denied-output-created")
    http_errors.require_digest(original, http_errors.SOURCE_DIGEST, "http-error-framework")
    if http_errors.verify_installed(sdk, tools) != tool_identity or snapshot(source) != before:
        raise ValueError("http-error-probe-inputs-changed")
    result = {**result, "rewriteDeterministic": True, "fivePreimageAndOwnershipDenials": True,
              "originalAndExistingOutputsUnchanged": True, "commands": commands.records,
              "responseReadErrors": response_errors,
              "synchronousRead": {**sync_result, "rewriteDeterministic": True,
                  "fivePreimageAndOwnershipDenials": True, "boundedErrorAssertions": combined["assertions"]}}
    write_json(output / "result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(probe(args.tools, args.output)))
        return 0
    except (ValueError, OSError, RuntimeError):
        print("http-error-probe-failed; inspect retained bounded diagnostics", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
