"""Explicitly reviewed source generator for actual signed C qualification only."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path

from tools import c_capsule
from tools.build_snapshot import digest
from tools.rust_capsule_project import snapshot, write_json


def install(project: Path, outside: Path) -> dict:
    """Exercise the public approval CLI; normal builds never approve a tool."""
    outside.mkdir(mode=0o700)
    inputs = outside / "inputs"
    inputs.mkdir(mode=0o700)
    (inputs / "value.txt").write_bytes(b"17")
    executable = outside / "generate-value"
    executable.write_bytes(b'#!/bin/sh\nset -eu\nvalue=$(cat /inputs/value.txt)\n'
        b'printf "int generated_library_value(void);\\n" > /outputs/value.h\n'
        b'printf "#include \\\"value.h\\\"\\nint generated_library_value(void) { return %s; }\\n" "$value" > /outputs/value.c\n')
    executable.chmod(0o700)
    main = project / "src/main.c"
    original = main.read_bytes()
    if original.count(b'#include "qualified.h"') != 1 or original.count(b'    size_t first =') != 1:
        raise ValueError("C generated-library qualification source hook changed")
    main.write_bytes(original.replace(b'#include "qualified.h"',
        b'#include "qualified.h"\n#include "generated/value.h"').replace(b'    size_t first =',
        b'    lsf_require(generated_library_value() == 17);\n    size_t first ='))
    candidate = project / "target/generator-request.json"
    candidate.parent.mkdir(mode=0o700, exist_ok=True)
    commands = []
    def cli(name, arguments, expected):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = c_capsule.main(list(map(str, arguments)))
        (outside / (name + ".stdout")).write_bytes(stdout.getvalue().encode())
        (outside / (name + ".stderr")).write_bytes(stderr.getvalue().encode())
        commands.append({"stage": name, "exitCode": code})
        if code != expected:
            raise ValueError("C generator qualification CLI failed; inspect retained diagnostics")
        return json.loads(stdout.getvalue() if expected == 0 else stderr.getvalue())
    before = snapshot(project)
    request = cli("request", ["generator-request", project, "--candidate", candidate,
        "--tool", executable, "--tool-version", "external-c-value-v1", "--inputs", inputs], 0)
    if (not request["approvalRequired"] or request["generatorExecution"]
            or request["requestDigest"] != digest(candidate.read_bytes())):
        raise ValueError("C generator qualification request identity changed")
    denial = cli("wrong-approval", ["generate", project, "--candidate", candidate,
        "--expect", "sha256:" + "0" * 64], 1)
    if denial["reason"] != "c-generator-request-approval-mismatch" or snapshot(project) != before:
        raise ValueError("C generator qualification changed source before approval")
    # This maintained fixture explicitly reviews its own exact request; the
    # application CLI and ordinary compiler retain independent approval.
    generated = cli("approved", ["generate", project, "--candidate", candidate,
        "--expect", request["requestDigest"]], 0)
    if (generated["status"], generated["cleanup"], generated["generatedFiles"]) != ("succeeded", "reaped", 2):
        raise ValueError("C generator qualification execution or reaping changed")
    executable.unlink()
    (inputs / "value.txt").unlink()
    cli("offline-status", ["dependencies", project], 0)
    result = {"requestDigest": request["requestDigest"], "executionReceiptDigest": generated["executionReceiptDigest"],
        "generatedInputsDigest": digest((project / "c-generated-inputs.json").read_bytes()),
        "originalGeneratorAndInputs": "unavailable-after-explicit-execution", "commands": commands,
        "network": "denied", "cleanup": "reaped", "compilerExecution": False,
        "runtimeExecution": "not-yet-observed"}
    write_json(outside / "GENERATOR-COMPLETE.json", result)
    return result
