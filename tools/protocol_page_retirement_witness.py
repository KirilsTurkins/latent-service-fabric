"""Build and run the real protocol-page allocator observer with the pinned graph."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/protocol_page_retirement_witness.rs'
CAPACITY_SOURCE = ROOT / 'tools/native_capacity_retirement_witness.rs'
PACKAGES = ('latent-http', 'latent-capabilities', 'latent-artifacts', 'latent-policy', 'latent-core')
TARGETS = {name.replace('-', '_') for name in PACKAGES} | {'tokio'}

def main():
    command = ['cargo', 'build', '--locked', '--lib', '--message-format=json']
    for package in PACKAGES:
        command += ['-p', package]
    found = {}
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
            if name not in TARGETS or 'lib' not in target['kind']:
                continue
            paths = [Path(p) for p in record['filenames'] if p.endswith('.rlib')]
            if len(paths) != 1 or (name in found and found[name] != paths[0]):
                raise RuntimeError(f'ambiguous artifact: {name}, previous={found.get(name)}, paths={paths}, features={record["features"]}')
            found[name] = paths[0]
    if set(found) != TARGETS:
        raise RuntimeError(f'missing artifacts: {TARGETS - set(found)}')
    with tempfile.TemporaryDirectory() as out:
        binary = Path(out) / 'protocol-page-owner-witness'
        fixture = Path(out) / 'fixture'
        fixture.mkdir()
        command = ['rustc', '--edition=2021', str(SOURCE), '-o', str(binary)]
        directories = {p.parent for p in found.values()}
        directories.update(p / 'deps' for p in tuple(directories) if p.name == 'debug')
        for path in sorted(map(str, directories)):
            command += ['-L', 'dependency=' + path]
        for path in sorted(linked):
            command += ['-L', path]
        for name in sorted(TARGETS):
            command += ['--extern', f'{name}={found[name]}']
        subprocess.run(command, cwd=ROOT, check=True, timeout=120)
        env = os.environ.copy()
        env['LSF_PROTOCOL_WITNESS_ROOT'] = str(fixture)
        subprocess.run([str(binary)], cwd=ROOT, check=True, timeout=30, env=env)
        # Reuse the same source-matched latent-core artifact to pause the actual
        # native-capacity Arc deallocator and observe its original node charge.
        capacity = Path(out) / 'native-capacity-owner-witness'
        command = ['rustc', '--edition=2021', str(CAPACITY_SOURCE), '-o', str(capacity)]
        for path in sorted(map(str, directories)):
            command += ['-L', 'dependency=' + path]
        command += ['--extern', f'latent_core={found["latent_core"]}']
        subprocess.run(command, cwd=ROOT, check=True, timeout=120)
        subprocess.run([str(capacity)], cwd=ROOT, check=True, timeout=30)

if __name__ == '__main__':
    main()
