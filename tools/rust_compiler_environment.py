"""Validate the captured Rust compiler environment used in consent requests."""
import re


RUST_ENVIRONMENT_SCALARS = ('LC_ALL', 'LANG', 'TZ', 'CARGO_NET_OFFLINE', 'CARGO_INCREMENTAL',
                            'CARGO_BUILD_JOBS', 'RUSTUP_AUTO_INSTALL', 'RUSTUP_TOOLCHAIN')
RUST_ENVIRONMENT_PATHS = {'ZIG_GLOBAL_CACHE_DIR': None, 'ZIG_LOCAL_CACHE_DIR': None,
    'CARGO_HOME': None, 'CARGO_TARGET_DIR': None, 'RUSTC': 'rustc', 'RUSTDOC': 'rustdoc',
    'CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER': 'linker', 'LSF_CAPTURED_ZIG': 'zig'}


def validate_environment_material(value: dict) -> dict:
    """Bounded digest-only shape accepted by explicit private request inspection."""
    from tools.application_dependency_store import DependencyError
    def require(condition):
        if not condition:
            raise DependencyError('cargo-execution-environment-invalid')
    def sha(identity):
        return isinstance(identity, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', identity) is not None
    require(isinstance(value, dict) and set(value) == {'formatVersion', 'profile', 'scalars', 'paths'})
    require(type(value['formatVersion']) is int and value['formatVersion'] == 1
            and value['profile'] == 'rust-captured-environment-v1')
    require(isinstance(value['scalars'], dict) and set(value['scalars']) == set(RUST_ENVIRONMENT_SCALARS))
    require(isinstance(value['paths'], dict) and value['paths'].keys() == RUST_ENVIRONMENT_PATHS.keys())
    for key, row in value['scalars'].items():
        if row is None:
            require(key == 'LANG')
        else:
            require(isinstance(row, dict) and set(row) == {'digest', 'size'})
            require(sha(row['digest']) and type(row['size']) is int and 0 <= row['size'] <= 4096)
    for key, row in value['paths'].items():
        if row is None:
            require(key == 'RUSTDOC')
        elif owner := RUST_ENVIRONMENT_PATHS[key]:
            require(isinstance(row, dict) and row == {'tool': owner})
        else:
            require(isinstance(row, dict) and set(row) == {'owner', 'relativeDigest'}
                    and row['owner'] == 'owned-workspace' and sha(row['relativeDigest']))
    return value
