"""Read-only diagnosis of the retained reopen selected-frame coverage gap."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('/workspace/project/target/optimization-catalog-mutations/full-01')
OUTPUT = Path('/workspace/project/target/issue108-reopen-coverage.json')


def read(path):
    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= 32 * 1024**2
    body = path.read_bytes()
    assert len(body) <= 32 * 1024**2
    return body, {'path': str(path.relative_to(ROOT)), 'bytes': str(len(body)),
                  'sha256': 'sha256:' + hashlib.sha256(body).hexdigest()}


body, aggregate_ref = read(ROOT / 'aggregate.json')
aggregate = json.loads(body)
assert aggregate['status'] == 'complete' and aggregate['validated_collectors'] == '32'
rows = []
for ordinal in (25, 27, 29, 31):
    row = aggregate['runs'][ordinal]
    assert row['sequence_ordinal'] == ordinal and row['mode'] == 'allocation-reopen'
    proof = row['allocation_attribution']['verified_symbols']['reopen']
    path = ROOT / ('runs/owner-' + str(ordinal) + '-allocation-00004-' + row['shape']
                   + '-' + row['variant'] + '-r01-allocation-reopen/probe/interpreted.heaptrack')
    data, source = read(path)
    observed = []
    for number, line in enumerate(data.splitlines(), 1):
        if b'measured_catalog_reopen' in line:
            assert len(line) <= 65536 and len(observed) < 4
            name = line.split(b' ', 2)[2].decode('ascii')
            observed.append({'line_number': number, 'line': line.decode('ascii'),
                             'name': name, 'matches_current_group': name in (proof['raw'], proof['demangled']),
                             'matches_raw_before_llvm_suffix': name == proof['raw'].split('.llvm.', 1)[0]})
    assert observed and all(not item['matches_current_group']
                            and item['matches_raw_before_llvm_suffix'] for item in observed)
    binary = ROOT / 'builds' / row['variant'] / 'latentd-backend-collector'
    address = int(proof['address'], 16)
    command = ['objdump', '-d', '--start-address=' + hex(address),
               '--stop-address=' + hex(address + 32), str(binary)]
    result = subprocess.run(command, capture_output=True, check=True, timeout=30)
    assert len(result.stdout) <= 16384 and len(result.stderr) <= 4096
    rows.append({'sequence_ordinal': ordinal, 'variant': row['variant'], 'shape': row['shape'],
                 'source': row['source'], 'binary': row['binary'], 'verified_symbol': proof,
                 'interpreted': source, 'observed_names': observed,
                 'original_attribution_status': row['allocation_attribution']['status'],
                 'original_counts': row['allocation_attribution']['frames']['reopen']['counts'],
                 'original_frame': row['allocation_frames'][0],
                 'disassembly': {'command': command, 'exit_code': result.returncode,
                                 'stdout': result.stdout.decode('ascii'),
                                 'stderr': result.stderr.decode('ascii')}})
value = {'schema': 'latent.catalog-mutation.reopen-coverage-diagnostic.v1',
         'scope': 'read-only retained evidence and 32-byte symbol disassembly; no workload or semantic replay',
         'aggregate': aggregate_ref, 'rows': rows,
         'conclusion': 'Exact selected-name groups omit the Heaptrack raw alias without the LLVM suffix. '
                       'The original available status establishes symbol proofs and zero unresolved frames, '
                       'but the zero selected counts do not measure recovery allocations. '
                       'Treat the selected reopen allocation comparison as unavailable; whole-process '
                       'and normal timing/memory evidence retain their original scopes.'}
with OUTPUT.open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(value, stream, indent=2)
    stream.write('\n')
print('Recorded coverage limitation for all four reopen profiles; no evidence modified.')
