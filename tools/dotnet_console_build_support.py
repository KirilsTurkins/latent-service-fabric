"""Fixed generic build support extracted from reviewed Fetch observer 1c420914.

Only these three unchanged function bodies are used. No Fetch fixture, imports,
registration observer or source identity is substituted into this diagnostic.
"""
from pathlib import Path
import re
import tomllib
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import digest, read_file, fresh

ORIGIN = '1c420914b72bff605422a9077fa3eea34af321a3'
ORIGIN_DIGEST = 'sha256:b6873e35d7122fbf1a46371c9e064ca514b3ea40d85600eac99d3733b01c1a45'

def retain_private_cargo(built, output: Path, environment: dict, *, stage: str = 'build') -> dict:
    """Retain bounded compiler output only, redacting known credential values.

    This runs before signing, node startup or peer credentials exist. These
    files are private setup diagnostics and are never runtime qualification.
    """
    require(stage in {'build', 'fetch'}, 'fetch-frame-private-compiler-stage')
    secrets = []
    for key, value in environment.items():
        if re.search(r'(^|_)(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTHORIZATION|API_KEY|PRIVATE_KEY)(_|$)', key, re.I):
            require(type(value) is str and len(value) <= 32768, 'fetch-frame-redaction-value-limit')
            if value:
                secrets.append(value.encode())
    result = {}
    for label, raw in [('stdout', built.stdout), ('stderr', built.stderr)]:
        require(type(raw) is bytes and len(raw) <= 1048576, 'fetch-frame-private-compiler-output-bound')
        for value in sorted(set(secrets), key=len, reverse=True):
            raw = raw.replace(value, b'[REDACTED]')
        truncated = len(raw) > 1048576
        path = output/('private-'+stage+'.'+label+'.txt')
        path.write_bytes(raw[:1048576])
        result[label] = {**file_identity(path), 'redactedOutputTruncated': truncated}
    return {'scope': 'private-bounded-compiler-setup-only', 'knownCredentialValuesRedacted': True,
            'streams': result, 'qualification': False}

def locked_registry_inputs(root: Path) -> dict:
    """Authenticate data-only registry hydration; no git/unlocked dependency."""
    raw = read_file(root/'Cargo.lock', 1024*1024)
    require(digest(raw) == 'sha256:9ca94752fc918c521dd365eab93c8b92dfdde8c770df1377a10c8b44fe85b4d8',
            'fetch-frame-original-lock')
    packages = tomllib.loads(raw.decode())['package']
    require(0 < len(packages) <= 2048 and all(not item.get('source') or (
        item['source'] == 'registry+https://github.com/rust-lang/crates.io-index'
        and re.fullmatch(r'[a-f0-9]{64}', item.get('checksum', ''))) for item in packages),
        'fetch-frame-checksummed-registry-only')
    return {'lock': file_identity(root/'Cargo.lock'), 'packages': len(packages),
            'registryPackages': sum(bool(item.get('source')) for item in packages),
            'target': 'x86_64-unknown-linux-gnu', 'locked': True, 'buildScriptsExecuted': False}

def private_target(root: Path, output: Path, environment: dict) -> tuple[Path, str]:
    """Use cached outputs when present, otherwise build only in fresh private storage.

    Registry inputs must already be cached: the unchanged command remains
    offline/locked and the same 450-second build and 600-second overall limits
    apply. A cache miss grants neither network acquisition nor passing credit.
    """
    target = Path(environment.get('CARGO_TARGET_DIR', str(root/'target'))).resolve()
    if target.is_dir():
        return target, 'existing-target'
    return fresh(output/'private-target'), 'fresh-private-target'
