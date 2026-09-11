from __future__ import annotations

import os
import shlex
import shutil
import stat
from collections.abc import Mapping
from fnmatch import fnmatchcase
from pathlib import Path

PHASE0_REJECTED_BUILD_OVERRIDE_PATTERNS = (
    "RUSTFLAGS",
    "RUSTDOCFLAGS",
    "RUSTC",
    "RUSTC_BOOTSTRAP",
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "RUSTUP_TOOLCHAIN",
    "CARGO_ENCODED_RUSTFLAGS",
    "CARGO_ENCODED_RUSTDOCFLAGS",
    "CARGO_INCREMENTAL",
    "CARGO_BUILD_*",
    "CARGO_PROFILE_*",
    "CARGO_TARGET_*_RUSTFLAGS",
    "CARGO_TARGET_*_LINKER",
    "CARGO_TARGET_*_RUNNER",
    "PHASE0_NATIVE_RELEASE_PATH_REMAP",
    "PHASE0_NATIVE_RELEASE_LINKER_BUILD_ID",
    "PHASE0_NATIVE_RELEASE_PROMOTED_LOCALS",
    "CC",
    "CXX",
    "AR",
    "CPPFLAGS",
    "CFLAGS",
    "CXXFLAGS",
    "ARFLAGS",
    "LDFLAGS",
    "CC_*",
    "CXX_*",
    "AR_*",
    "CPPFLAGS_*",
    "CFLAGS_*",
    "CXXFLAGS_*",
    "ARFLAGS_*",
    "LDFLAGS_*",
    "*_CC",
    "*_CXX",
    "*_AR",
    "*_CPPFLAGS",
    "*_CFLAGS",
    "*_CXXFLAGS",
    "*_ARFLAGS",
    "*_LDFLAGS",
)


def is_phase0_rejected_build_override(name: str) -> bool:
    return any(
        fnmatchcase(name, pattern)
        for pattern in PHASE0_REJECTED_BUILD_OVERRIDE_PATTERNS
    )


def sanitized_phase0_environment(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    return {
        name: value
        for name, value in environment.items()
        if not is_phase0_rejected_build_override(name)
    }


def write_native_linux_runner_stubs(bin_directory: Path) -> None:
    """Give isolated fail-fast runner tests one consistent, fake host identity.

    Only copied runners with fake workload tools may use these PATH stubs.
    Production collectors still inspect the real host. Grep retains its real
    matching behavior; only the two kernel identity file inputs are replaced.
    """
    real_grep = shutil.which("grep")
    if real_grep is None:
        raise RuntimeError("runner fixtures require grep")
    kernel_identity = bin_directory / "native-kernel.txt"
    kernel_identity.write_text("Linux version 6.8.0-native-test\n", encoding="utf-8")
    commands = {
        "uname": "#!/usr/bin/env bash\nprintf '%s\\n' Linux\n",
        "systemd-detect-virt": "#!/usr/bin/env bash\nprintf '%s\\n' none\n",
        "grep": (
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "arguments=()\n"
            'for argument in "$@"; do\n'
            '  case "$argument" in\n'
            "    /proc/sys/kernel/osrelease|/proc/version)\n"
            f"      arguments+=({shlex.quote(str(kernel_identity))}) ;;\n"
            '    *) arguments+=("$argument") ;;\n'
            "  esac\n"
            "done\n"
            f'exec {shlex.quote(real_grep)} "${{arguments[@]}}"\n'
        ),
    }
    for command, contents in commands.items():
        path = bin_directory / command
        path.write_text(contents, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
