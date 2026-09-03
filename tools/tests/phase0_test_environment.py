from __future__ import annotations

import os
from collections.abc import Mapping
from fnmatch import fnmatchcase

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
