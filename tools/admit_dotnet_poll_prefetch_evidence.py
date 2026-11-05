"""Copy only bounded public paired diagnostic evidence to a separate upload root."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity

MAX_FILES, MAX_FILE, MAX_TOTAL, MAX_RECORD = 1024, 64 * 1024**2, 256 * 1024**2, 1024**2
SHARED = ('native/native-products.json', 'native/source-inputs.json', 'native/retrieval.json',
    'pair/qualified.json', 'pair/FAILED.json', 'pair/attempt-*.json', 'pair/result-*.json',
    'pair/pair-commands/logs/*.stdout.txt', 'pair/pair-commands/logs/*.stderr.txt')
VARIANT = ('qualified.json', 'FAILED.json', 'capture.json', 'build/*.json',
    'build/component.wasm', 'build/native-aot-original.wasm', 'build/derived-*.dll',
    'build/logs/*.stdout.txt', 'build/logs/*.stderr.txt', 'build/package/*.json', 'build/package/*.wasm',
    'node/*.json', 'node/commands/logs/*.stdout.txt',
    'node/commands/logs/*.stderr.txt', 'node/controls/*.json',
    'node/signed/my-greeting/build-observation.json', 'node/signed/release-set.json')
INSTALLATION = ('INSTALL-COMPLETE.json', 'runtime-inputs.json', 'wasi-sdk.json',
    'logs/*.stdout.txt', 'logs/*.stderr.txt')
PATTERNS = SHARED + tuple('tools-' + variant + '/' + path
    for variant in ('baseline', 'fixed') for path in INSTALLATION) + tuple('pair/' + variant + '/' + path
    for variant in ('baseline', 'fixed') for path in VARIANT)


def admit(root):
    root = Path(root).absolute(); record_path = root / 'evidence-admission.json'
    value = {'schemaVersion': 'latent.dotnet.poll-prefetch.evidence-admission.v1', 'status': 'failed'}
    try:
        require(root.is_dir() and not root.is_symlink(), 'poll-prefetch-evidence-root')
        files = sorted({path for pattern in PATTERNS for path in root.glob(pattern)})
        require(1 <= len(files) <= MAX_FILES, 'poll-prefetch-evidence-count')
        selected = {}; total = 0
        for path in files:
            relative = path.relative_to(root)
            require(path.is_file() and not path.is_symlink()
                and all(not root.joinpath(*relative.parts[:i]).is_symlink()
                    for i in range(1, len(relative.parts))), 'poll-prefetch-evidence-path')
            identity = file_identity(path, MAX_FILE); total += identity['bytes']
            require(total <= MAX_TOTAL - MAX_RECORD, 'poll-prefetch-evidence-total')
            selected[relative.as_posix()] = identity
        public = root / 'public'; require(not public.exists(), 'poll-prefetch-public-not-fresh'); public.mkdir(mode=0o700)
        for name, identity in selected.items():
            source = root / name; destination = public / name; destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            require(file_identity(destination, MAX_FILE) == identity == file_identity(source, MAX_FILE),
                'poll-prefetch-evidence-preimage-changed')
        value.update(status='passed', files=selected, payloadBytes=total, uploadUnionMaximumBytes=MAX_TOTAL)
    finally:
        data = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
        require(len(data) <= MAX_RECORD, 'poll-prefetch-evidence-record-bound')
        record_path.write_bytes(data)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    print(admit(parser.parse_args().output)['status'])
