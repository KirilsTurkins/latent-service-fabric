"""Copy only bounded public two-case diagnostic evidence to a separate upload root."""
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
PATTERNS = (
    'native/native-products.json', 'native/source-inputs.json', 'native/retrieval.json',
    'tools/INSTALL-COMPLETE.json', 'tools/runtime-inputs.json', 'tools/wasi-sdk.json',
    'tools/logs/*.stdout.txt', 'tools/logs/*.stderr.txt',
    'witness/qualified.json', 'witness/FAILED.json', 'witness/capture.json',
    'witness/build/*.json', 'witness/build/component.wasm', 'witness/build/derived-*.dll',
    'witness/build/logs/*.stdout.txt', 'witness/build/logs/*.stderr.txt',
    'witness/node/*.json', 'witness/node/commands/logs/*.stdout.txt',
    'witness/node/commands/logs/*.stderr.txt', 'witness/node/controls/*.json',
    'witness/node/signed/my-greeting/build-observation.json',
    'witness/node/signed/release-set.json',
)


def admit(root):
    root = Path(root).absolute(); record_path = root / 'evidence-admission.json'
    value = {'schemaVersion': 'latent.dotnet.monitor-cancel.evidence-admission.v1', 'status': 'failed'}
    try:
        require(root.is_dir() and not root.is_symlink(), 'monitor-cancel-evidence-root')
        files = sorted({path for pattern in PATTERNS for path in root.glob(pattern)})
        require(1 <= len(files) <= MAX_FILES, 'monitor-cancel-evidence-count')
        selected = {}; total = 0
        for path in files:
            relative = path.relative_to(root)
            require(path.is_file() and not path.is_symlink()
                and all(not root.joinpath(*relative.parts[:i]).is_symlink()
                    for i in range(1, len(relative.parts))), 'monitor-cancel-evidence-path')
            identity = file_identity(path, MAX_FILE); total += identity['bytes']
            require(total <= MAX_TOTAL - MAX_RECORD, 'monitor-cancel-evidence-total')
            selected[relative.as_posix()] = identity
        public = root / 'public'; require(not public.exists(), 'monitor-cancel-public-not-fresh'); public.mkdir(mode=0o700)
        for name, identity in selected.items():
            source = root / name; destination = public / name; destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            require(file_identity(destination, MAX_FILE) == identity == file_identity(source, MAX_FILE),
                'monitor-cancel-evidence-preimage-changed')
        value.update(status='passed', files=selected, payloadBytes=total, uploadUnionMaximumBytes=MAX_TOTAL)
    finally:
        data = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
        require(len(data) <= MAX_RECORD, 'monitor-cancel-evidence-record-bound')
        record_path.write_bytes(data)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    print(admit(parser.parse_args().output)['status'])
