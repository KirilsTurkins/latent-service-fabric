#!/usr/bin/env python3
"""Probe pinned upstream Go bindings against LSF's real WIT; never claim delivery."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.build_process import run_bounded
from tools.stage_runtime_wit import stage


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def probe(output: Path, go: Path, componentize: Path, wasm_tools: Path) -> None:
    output = output.resolve()
    if output.exists():
        raise ValueError("probe output must be a fresh directory; preserve previous attempts")
    if output == ROOT or (ROOT in output.parents and not output.is_relative_to(ROOT / "target")):
        raise ValueError("probe output must be outside source directories")
    output.mkdir(parents=True)
    lock = json.loads((ROOT / "sdk/go-guest/toolchain.lock.json").read_text())
    abi = json.loads((ROOT / lock["hostAbiSource"]).read_text())
    report = {"formatVersion": 1, "status": "failed", "deployable": False,
              "profile": lock["profile"], "steps": [], "startedAt": int(time.time()),
              "sourceInputs": {}, "limitations": [
                  "Upstream WASI adapter is not an LSF runtime-authority adapter.",
                  "Binding generation and compilation are not real-node conformance."]}
    environment = os.environ.copy()
    environment.update(GOTOOLCHAIN="local", GOWORK="off", GOFLAGS="-mod=readonly",
                       GOCACHE=str(output / "go-cache"), TMPDIR=str(output / "tmp"))
    (output / "tmp").mkdir()
    environment["PATH"] = str(go.parent) + os.pathsep + environment.get("PATH", "")

    def run(label: str, command: list[str], cwd: Path = ROOT) -> str:
        started = time.monotonic()
        entry = {"name": label, "command": command, "status": "failed"}
        report["steps"].append(entry)
        try:
            result = run_bounded(command, cwd, environment, timeout_seconds=600,
                                 max_output_bytes=4 * 1024 * 1024)
            (output / f"{label}.stdout").write_bytes(result.stdout)
            (output / f"{label}.stderr").write_bytes(result.stderr)
            entry["status"] = "passed"
            return result.stdout.decode("utf-8")
        except Exception as error:
            entry["error"] = str(error)
            raise
        finally:
            entry["elapsedSeconds"] = time.monotonic() - started
            write_json(output / "probe-report.json", report)

    try:
        actual = run("go-version", [str(go), "version"]).split()
        if len(actual) < 3 or actual[2] != lock["go"]["version"]:
            raise ValueError("Go compiler version differs from the pinned profile")
        goroot = Path(run("go-root", [str(go), "env", "GOROOT"]).strip())
        runtime = goroot / "src/runtime/lock_wasip1.go"
        if "wasiOnIdle" not in runtime.read_text():
            raise ValueError("async Go patch is absent; implicit compiler downloads are forbidden")
        version = run("componentize-version", [str(componentize), "--version"]).split()
        if version != ["componentize-go", lock["componentizeGo"]["version"]]:
            raise ValueError("componentize-go differs from the pinned profile")
        run("wasm-tools-version", [str(wasm_tools), "--version"])
        source = output / "source-wit"
        source.mkdir()
        imports = "\n".join("    import " + item["interface"] + ";" for item in abi["interfaces"])
        (source / "world.wit").write_text(
            "package lsf:go-probe@1.0.0;\n\n"
            "interface probe {\n"
            "    record payload { value: u64, text: string, bytes: list<u8> }\n"
            "    check: async func(input: payload) -> result<payload, string>;\n"
            "}\n\nworld capsule {\n" + imports + "\n    export probe;\n}\n")
        wit = output / "wit"
        stage(wit, source)
        for path in sorted(wit.rglob("*.wit")):
            report["sourceInputs"][str(path.relative_to(output))] = digest(path)
        report["sourceInputs"]["sdk/go-guest/toolchain.lock.json"] = digest(ROOT / "sdk/go-guest/toolchain.lock.json")
        report["sourceInputs"][lock["hostAbiSource"]] = digest(ROOT / lock["hostAbiSource"])
        module = output / "module"
        module.mkdir()
        args = [str(componentize), "--ignore-toml-files", "-d", str(wit), "-w", "capsule"]
        run("bindings", args + ["bindings", "--generate-stubs", "--format", "-o", str(module)])
        report["generatedBindings"] = {str(path.relative_to(module)): digest(path)
                                       for path in sorted(module.rglob("*")) if path.is_file()}
        run("module-download", [str(go), "mod", "download"], module)
        component = output / "upstream-candidate.wasm"
        run("component-build", args + ["build", "--go", str(go), "-o", str(component)], module)
        run("component-validate", [str(wasm_tools), "validate", "--features", "all", str(component)])
        surface = run("component-wit", [str(wasm_tools), "component", "wit", str(component)])
        (output / "upstream-candidate.wit").write_text(surface)
        report["component"] = {"digest": digest(component), "size": component.stat().st_size}
        report["status"] = "upstream-build-observed"
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        report["finishedAt"] = int(time.time())
        write_json(output / "probe-report.json", report)
        shutil.rmtree(output / "go-cache", ignore_errors=True)
        shutil.rmtree(output / "tmp", ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--go", required=True, type=Path)
    parser.add_argument("--componentize-go", type=Path, default=shutil.which("componentize-go"))
    parser.add_argument("--wasm-tools", type=Path, default=shutil.which("wasm-tools"))
    args = parser.parse_args()
    if args.componentize_go is None or args.wasm_tools is None:
        parser.error("install the pinned componentize-go and wasm-tools first")
    probe(args.output, args.go.resolve(), args.componentize_go.resolve(), args.wasm_tools.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
