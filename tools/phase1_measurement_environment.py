"""Observed host/build identity for the separate Phase 1 measurement runner."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import subprocess

from tools.run_phase1_conformance import ROOT, digest, git, identity


def command(*arguments: str) -> str:
    return subprocess.run(arguments, cwd=ROOT, check=True, capture_output=True,
                          text=True, timeout=15).stdout.strip()


def optional_text(path: Path, limit: int = 64 * 1024) -> str | None:
    try:
        with path.open("rb") as source:
            data = source.read(limit + 1)
        if len(data) > limit:
            return None
        return data.decode("utf-8").strip()
    except (OSError, UnicodeError):
        return None


def virtualization() -> dict:
    observations = {}
    for name, argument in (("systemd_detect_virt", ""),
                           ("systemd_detect_virt_container", "--container"),
                           ("systemd_detect_virt_vm", "--vm")):
        try:
            result = subprocess.run(["systemd-detect-virt", *([argument] if argument else [])],
                                    capture_output=True, text=True, timeout=5)
            observations[name] = result.stdout.strip() or "unavailable"
        except (OSError, subprocess.SubprocessError):
            observations[name] = "unavailable"
    observations.update({
        "wsl_detected": "microsoft" in platform.release().lower(),
        "docker_marker": Path("/.dockerenv").exists(),
        "container_marker": Path("/run/.containerenv").exists(),
        "cpu_max": optional_text(Path("/sys/fs/cgroup/cpu.max")),
        "memory_max": optional_text(Path("/sys/fs/cgroup/memory.max")),
        "cpuset_effective": optional_text(Path("/sys/fs/cgroup/cpuset.cpus.effective")),
    })
    return observations


def host() -> dict:
    # Keep missing observations explicit. They never become measured zeroes.
    cpu = optional_text(Path("/proc/cpuinfo"), 1024 * 1024) or ""
    model = next((line.split(":", 1)[1].strip() for line in cpu.splitlines()
                  if line.startswith("model name") and ":" in line), "unavailable")
    memory = optional_text(Path("/proc/meminfo")) or ""
    total = re.search(r"^MemTotal:\s+(\d+) kB$", memory, re.MULTILINE)
    policies = {}
    for path in sorted(Path("/sys/devices/system/cpu/cpufreq").glob("policy*"))[:1024]:
        policies[path.name] = {name: optional_text(path / name) for name in
                               ("scaling_governor", "scaling_driver", "scaling_min_freq",
                                "scaling_max_freq", "energy_performance_preference")}
    return {
        "os": platform.system(), "arch": platform.machine(), "kernel": command("uname", "-a"),
        "cpu_model": model, "logical_cpus": str(os.cpu_count()) if os.cpu_count() else None,
        "memory_total_bytes": str(int(total[1]) * 1024) if total else None,
        "virtualization": virtualization(),
        "allocator": {name: os.environ.get(name, "unset") for name in ("LD_PRELOAD", "MALLOC_CONF")},
        "cpu_policy": policies, "load_before": list(os.getloadavg()),
    }


def build_configuration(profile: str) -> dict:
    rustc = command("rustc", "--version", "--verbose")
    target = next((line.removeprefix("host: ") for line in rustc.splitlines()
                   if line.startswith("host: ")), "unavailable")
    if profile == "full":
        overrides = {
            "recipe": "tools/phase0_build_environment.sh:phase0_release_cargo",
            "recipe_sha256": digest(ROOT / "tools/phase0_build_environment.sh")[0],
            "opt_level": "3", "debug": "1", "codegen_units": "16", "lto": "false",
            "debug_assertions": "false", "overflow_checks": "false", "incremental": "false",
            "panic": "unwind", "strip": "none", "path_remap": "source-target-cargo-home-v1",
            "linker_build_id": "sha1", "promoted_locals": "source-filename",
            "collector_surface": "libtest",
        }
    else:
        overrides = {"collector_surface": "libtest", "recipe": "cargo-test-debug"}
    return {"profile": "release" if profile == "full" else "debug", "rustc": rustc,
            "cargo": command("cargo", "--version"), "wasmtime": "47.0.3", "target": target,
            "overrides": overrides}


def capture(profile: str, binary: Path, fixtures: dict[str, Path]) -> dict:
    return {
        "schema": "latent.phase1.measurement-identity.v1",
        "source": {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
                   "dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
                   "cargo_lock_sha256": digest(ROOT / "Cargo.lock")[0]},
        "build": build_configuration(profile), "environment": host(),
        "binary": {key: value for key, value in identity("collector", binary).items() if key != "name"},
        "fixtures": [identity(name, path, 16 * 1024 * 1024) for name, path in fixtures.items()],
    }
