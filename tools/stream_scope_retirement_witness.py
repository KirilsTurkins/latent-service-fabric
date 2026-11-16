"""Compile and run the actual shared-stream-scope allocator observer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/stream_scope_retirement_witness.rs'
PACKAGES = {
    'latent_capabilities', 'latent_activation', 'latent_artifacts', 'latent_audit',
    'latent_core', 'latent_executor', 'latent_manifest', 'latent_policy',
    'latent_routing', 'serde_json',
}


def cargo_artifacts(command):
    artifacts = {}
    linked = set()
    with tempfile.TemporaryFile() as receipt:
        subprocess.run(command, cwd=ROOT, stdout=receipt, check=True, timeout=600)
        if receipt.tell() > 64 * 1024 * 1024:
            raise RuntimeError('cargo artifact receipt too large')
        receipt.seek(0)
        for line in receipt:
            record = json.loads(line)
            if record.get('reason') == 'build-script-executed':
                linked.update(record.get('linked_paths', []))
            if record.get('reason') != 'compiler-artifact':
                continue
            target = record['target']
            name = target['name']
            if name not in PACKAGES or 'lib' not in target['kind']:
                continue
            if name == 'latent_capabilities' and (record['profile']['test'] or record['features']):
                raise RuntimeError('scope witness requires the default production capability library')
            paths = [Path(path) for path in record['filenames'] if path.endswith('.rlib')]
            if not paths:  # The lib-test target is an executable, not the production rlib.
                continue
            if len(paths) != 1 or (name in artifacts and artifacts[name] != paths[0]):
                raise RuntimeError(f'ambiguous artifact: {name}, paths={paths}')
            artifacts[name] = paths[0]
    return artifacts, linked


def main():
    # Match the test fixture's direct audit feature while compiling the normal
    # production capability library. No stopped diagnostic or test is run.
    production, native = cargo_artifacts([
        'cargo', 'build', '--locked', '--lib', '-p', 'latent-capabilities',
        '-p', 'latent-manifest', '--features', 'latent-audit/test-support',
        '--message-format=json',
    ])
    if not PACKAGES <= production.keys():
        raise RuntimeError(f'missing production artifacts: {PACKAGES - production.keys()}')
    artifacts = {name: production[name] for name in PACKAGES}
    with tempfile.TemporaryDirectory() as out:
        binary = Path(out) / 'stream-scope-owner-witness'
        command = ['rustc', '--edition=2021', str(SOURCE), '-o', str(binary)]
        for path in sorted({str(path.parent) for path in artifacts.values()}):
            command += ['-L', 'dependency=' + path]
        for path in sorted(native):
            command += ['-L', path]
        for name, path in sorted(artifacts.items()):
            command += ['--extern', f'{name}={path}']
        env = os.environ.copy()
        # The checked-in fixture's include_str! resolves against its own crate.
        env['CARGO_MANIFEST_DIR'] = str(ROOT / 'crates/latent-capabilities')
        env['LSF_SCOPE_WITNESS_ROOT'] = out
        subprocess.run(command, cwd=ROOT, check=True, timeout=120, env=env)
        subprocess.run([str(binary)], cwd=ROOT, check=True, timeout=30, env=env)


if __name__ == '__main__':
    main()
