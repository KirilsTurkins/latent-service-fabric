#!/usr/bin/env bash
# Build the unchanged historical implementation for the targeted #94 comparison.
# The caller supervises this entire process group with wall-time/output bounds.
# This does not run a calibration, broad contract gate, or activation workload.
set -euo pipefail

if [[ $# -ne 2 ]]; then
    printf '%s\n' 'usage: build_phase1_historical_control.sh HISTORICAL_SOURCE FRESH_BUILD_DIR' >&2
    exit 2
fi
if [[ "$(uname -s)" != Linux ]]; then
    printf '%s\n' 'The historical comparison build requires Linux; containers are supported.' >&2
    exit 2
fi
for command in git python3 cargo rustc wasm-tools realpath tee; do
    command -v "$command" >/dev/null 2>&1 || {
        printf 'required command unavailable: %s\n' "$command" >&2
        exit 2
    }
done

COMPARISON_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CONTROL_SOURCE="$(realpath -- "$1")"
CONTROL_BUILD="$(realpath -m -- "$2")"
CONTROL_COMMIT=52ac47542a05c0a1263f78a14c04a5c2e6b761f3
CONTROL_TREE=cac3ececdbd0b5734691c30c0283fccff169a5f5

python3 - "$CONTROL_SOURCE" "$CONTROL_BUILD" "$COMPARISON_ROOT" "$CONTROL_COMMIT" "$CONTROL_TREE" <<'PY'
import importlib.metadata
import platform
import re
import subprocess
import sys
import tomllib
from pathlib import Path

source, build, candidate = map(Path, sys.argv[1:4])
commit, tree = sys.argv[4:6]
def git(*args):
    return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()
if (Path(git('rev-parse', '--show-toplevel')).resolve() != source
        or git('rev-parse', 'HEAD') != commit
        or git('rev-parse', 'HEAD^{tree}') != tree
        or git('status', '--porcelain', '--untracked-files=normal')):
    raise SystemExit('historical source must be the exact clean 52ac4754 checkout')
if build.exists() or build.is_symlink():
    raise SystemExit('historical build directory must be fresh')
if any(build == root or build.is_relative_to(root) or root.is_relative_to(build)
       for root in (source, candidate)):
    raise SystemExit('historical build directory must be outside both source trees')
for name in ('component.rs', 'logic.rs'):
    relative = Path('tools/toolchain-smoke/examples/echo_capsule') / name
    if (source / relative).read_bytes() != (candidate / relative).read_bytes():
        raise SystemExit('historical and candidate maintained echo source differs')
toolchain = tomllib.loads((source / 'tools/toolchain.toml').read_text())
if (platform.python_version() != toolchain['contracts']['python']
        or importlib.metadata.version('jsonschema') != toolchain['contracts']['jsonschema']):
    raise SystemExit('historical Python/schema tools do not match their committed pins')
for command, expected in ((['rustc', '--version'], toolchain['rust']['toolchain']),
                          (['cargo', '--version'], toolchain['rust']['toolchain']),
                          (['wasm-tools', '--version'], toolchain['contracts']['wasm-tools'])):
    output = subprocess.check_output(command, cwd=source, text=True)
    version = re.search(r'\b\d+\.\d+\.\d+\b', output)
    if version is None or version[0] != expected:
        raise SystemExit('historical build tool does not match its committed pin')
PY

cd "$CONTROL_SOURCE"
# Source the historical recipe, not a current facade or a copied implementation.
# shellcheck disable=SC1091
source "$CONTROL_SOURCE/tools/phase0_build_environment.sh"
phase0_reject_inherited_build_overrides
phase0_reject_hidden_cargo_configuration
if [[ -n "${CARGO:-}" || -n "${WASM_TOOLS:-}" ]]; then
    printf '%s\n' 'Custom Cargo/wasm-tools commands are not accepted by this comparison build.' >&2
    exit 2
fi
export CARGO_TARGET_DIR="$CONTROL_BUILD"
export GITHUB_SHA="$CONTROL_COMMIT"
mkdir -- "$CONTROL_BUILD"

run_logged() {
    printf '+ ' | tee -a "$CONTROL_BUILD/build.log"
    printf '%q ' "$@" | tee -a "$CONTROL_BUILD/build.log"
    printf '\n' | tee -a "$CONTROL_BUILD/build.log"
    "$@" 2>&1 | tee -a "$CONTROL_BUILD/build.log"
}

# This historical maintained helper builds only the echo guest, validates its
# WIT/manifest and uses two clean guest builds to verify byte reproducibility.
run_logged python3 tools/build_echo_capsule.py --verify-reproducible
run_logged phase0_release_cargo build -p latentd --bin phase0-baseline --release --locked

python3 - "$CONTROL_SOURCE" "$CONTROL_BUILD" "$COMPARISON_ROOT" "$CONTROL_COMMIT" "$CONTROL_TREE" <<'PY'
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

source, build, candidate = map(Path, sys.argv[1:4])
commit, tree = sys.argv[4:6]
def git(*args):
    return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()
if (git('rev-parse', 'HEAD') != commit or git('rev-parse', 'HEAD^{tree}') != tree
        or git('status', '--porcelain', '--untracked-files=normal')):
    raise SystemExit('historical source changed during the control build')

def reference(path, maximum=1024 * 1024):
    if path.is_symlink() or not path.is_file():
        raise SystemExit('control artifact must be a regular file')
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        raise SystemExit('control artifact exceeds its declared size bound')
    digest = hashlib.sha256()
    observed = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b''):
            observed += len(chunk)
            if observed > maximum:
                raise SystemExit('control artifact grew beyond its size bound')
            digest.update(chunk)
    if observed != size:
        raise SystemExit('control artifact changed while hashing')
    return {'path': path.relative_to(build).as_posix(),
            'sha256': 'sha256:' + digest.hexdigest(), 'bytes': str(size)}

def copy_input(path, relative):
    destination = build / 'inputs' / relative
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise SystemExit('control source artifact is not bounded regular input')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(path.read_bytes())
    return reference(destination)

original = build / 'capsules/echo'
staged = build / 'phase0-baseline/staged-echo'
staged.mkdir(parents=True)
component = staged / 'echo-capsule.wasm'
guest = original / 'echo-capsule.wasm'
reference(guest, 16 * 1024 * 1024)
shutil.copyfile(guest, component)
manifest = json.loads((original / 'capsule.json').read_text())
# These are immutable staged measurement inputs, not changes to historical code.
# Effective per-call grants match the candidate. The relative/absolute deadline
# is supplied by the targeted runner (1000 ms), not fabricated in this manifest.
manifest['execution']['limits']['cpuFuel'] = 10_000_000_000
manifest['execution']['limits']['memoryBytes'] = 16 * 1024 * 1024
if manifest['execution']['limits']['logBytes'] != 16384:
    raise SystemExit('historical echo log grant differs from the comparison plan')
capsule = staged / 'capsule.json'
with capsule.open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(json.dumps(manifest, indent=2, sort_keys=True) + '\n')

artifacts = [reference(build / 'build.log', 4 * 1024 * 1024),
             reference(original / 'capsule.json'), reference(original / 'build.json')]
source_paths = ['Cargo.lock', 'rust-toolchain.toml', 'tools/toolchain.toml',
                'tools/phase0_build_environment.sh', 'tools/build_echo_capsule.py',
                'examples/echo-contract/capsule.json', 'tools/toolchain-smoke/Cargo.toml',
                'tools/toolchain-smoke/build.rs']
source_paths += git('ls-files', 'wit/platform/context', 'wit/platform/log',
                    'examples/echo-contract/wit').splitlines()
for relative in source_paths:
    artifacts.append(copy_input(source / relative, 'historical/' + relative))
shared_guest_sources = []
for name in ('component.rs', 'logic.rs'):
    relative = 'tools/toolchain-smoke/examples/echo_capsule/' + name
    old = copy_input(source / relative, 'historical/' + relative)
    new = copy_input(candidate / relative, 'candidate/' + relative)
    if old['sha256'] != new['sha256'] or old['bytes'] != new['bytes']:
        raise SystemExit('maintained echo source changed during the control build')
    artifacts.extend((old, new))
    shared_guest_sources.append({'source_path': relative, 'historical': old, 'candidate': new})
artifacts.append(copy_input(candidate / 'tools/build_phase1_historical_control.sh',
                            'build_phase1_historical_control.sh'))
recipe = next(row for row in artifacts if row['path'].endswith('/tools/phase0_build_environment.sh'))
lock = next(row for row in artifacts if row['path'].endswith('/Cargo.lock'))
rustc = subprocess.check_output(['rustc', '--version', '--verbose'], cwd=source, text=True).strip()
target = next(line.removeprefix('host: ') for line in rustc.splitlines() if line.startswith('host: '))
build_configuration = {
    'profile': 'release', 'rustc': rustc,
    'cargo': subprocess.check_output(['cargo', '--version'], cwd=source, text=True).strip(),
    'wasmtime': '47.0.3', 'target': target,
    'overrides': {
        'recipe': 'tools/phase0_build_environment.sh:phase0_release_cargo',
        'recipe_sha256': recipe['sha256'], 'opt_level': '3', 'debug': '1',
        'codegen_units': '16', 'lto': 'false', 'debug_assertions': 'false',
        'overflow_checks': 'false', 'incremental': 'false', 'panic': 'unwind',
        'strip': 'none', 'path_remap': 'source-target-cargo-home-v1',
        'linker_build_id': 'sha1', 'promoted_locals': 'source-filename',
        'collector_surface': 'native-binary',
    },
}
receipt = {
    'schema': 'latent.phase1.control-build.v1',
    'source': {'commit': commit, 'tree': tree, 'dirty': False,
               'cargo_lock_sha256': lock['sha256']},
    'build': build_configuration,
    'binary': reference(build / 'release/phase0-baseline', 1024 * 1024 * 1024),
    'component': reference(component, 16 * 1024 * 1024), 'capsule': reference(capsule),
    'artifacts': artifacts, 'shared_guest_sources': shared_guest_sources,
    'commands': [
        ['python3', 'tools/build_echo_capsule.py', '--verify-reproducible'],
        ['phase0_release_cargo', 'build', '-p', 'latentd', '--bin', 'phase0-baseline', '--release', '--locked'],
    ],
    'staged_manifest_changes': {'cpuFuel': '10000000000', 'memoryBytes': '16777216'},
    'scope': 'targeted-historical-runtime-comparison-not-native-calibration',
    'full_invariant_proof': 'not-run-by-this-build-helper',
}
encoded = json.dumps(receipt, indent=2, sort_keys=True) + '\n'
if len(encoded.encode()) > 256 * 1024:
    raise SystemExit('control build receipt exceeds its bound')
with (build / 'build-receipt.json').open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(encoded)
print(json.dumps({'control_build_receipt': str(build / 'build-receipt.json'),
                  'scope': receipt['scope']}, sort_keys=True))
PY
