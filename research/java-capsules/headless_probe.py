"""Run the checked C candidate separately from the preserved upstream attempts."""
from __future__ import annotations

from pathlib import Path

import headless


def run(attempt, tools: dict[str, str], project: Path) -> dict:
    output = attempt.output / "build/C-headless"
    result = {"qualification": "not-qualified", "lsfExecution": "not-attempted",
              "status": "not-started", "coreExecution": "not-attempted"}
    headless.prepare(attempt.output / "build/C", output)
    # The checksum-pinned Zig distribution keeps its library beside the binary.
    # Zig 0.16 emits ZON from `env`; do not misparse it as JSON.
    zig_lib = Path(tools["zig"]).resolve().parent / "lib"
    commands = headless.compile_commands(tools["zig"], zig_lib, output)
    for name, command in commands:
        if attempt.run(name, command)["status"] != "passed":
            return dict(result, status="failed", failedPhase=name)
    core = output / "probe.wasm"
    result.update(coreSha256=headless.sha256(core), coreBytes=core.stat().st_size)
    for name, command in [
        ("c-headless-validate", [tools["wasm-tools"], "validate", str(core)]),
        ("c-headless-embed", [tools["wasm-tools"], "component", "embed", str(project / "headless.wit"),
                               str(core), "--world", "capsule", "-o", str(output / "embedded.wasm")]),
        ("c-headless-component", [tools["wasm-tools"], "component", "new", str(output / "embedded.wasm"),
                                   "-o", str(output / "component.wasm")]),
        ("c-headless-component-validate", [tools["wasm-tools"], "validate", str(output / "component.wasm")]),
        ("c-headless-component-wit", [tools["wasm-tools"], "component", "wit", str(output / "component.wasm")]),
        ("c-headless-core-execution", [tools["node"], str(project / "check_core.mjs"),
                                       str(core), str(output / "core-execution.json")]),
    ]:
        if attempt.run(name, command)["status"] != "passed":
            return dict(result, status="failed", failedPhase=name)
        if name == "c-headless-core-execution":
            result["coreExecution"] = "passed-not-lsf-qualification"
    component = output / "component.wasm"
    result.update(status="compiled-component", componentSha256=headless.sha256(component),
                  componentBytes=component.stat().st_size)
    return result
