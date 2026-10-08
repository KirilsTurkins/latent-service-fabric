"""Copy real retained compiler captures without altering reports or receipts."""
import hashlib
import json
from pathlib import Path
import shutil

base = Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data')
source_job = base / 'jobs/integration-v12-current-java-six-compiler-v1'
destination = base / 'jobs/integration-v12-current-java-six-captures-v2'
assert not destination.exists()
destination.mkdir(mode=0o700)
selections = []
for report_path in [*source_job.glob('results/*/report.json'), *source_job.glob('diagnostic/*/report.json')]:
    report = json.loads(report_path.read_text())
    assert report['sourceRevision'] == 'b133685145a66940358ec38eb6c90e61e6fa39b3'
    assert report['compiled'] is True and report['status'] == 'compiled'
    assert report['workingTreeChanged'] is False
    original = report_path.parent
    target = destination / report['variant']
    target.mkdir(mode=0o700)
    for name in ['report.json', 'source-inputs.json', 'source.tar.gz', 'recipe-inputs.json', 'compiler-inputs.json']:
        shutil.copyfile(original / name, target / name)
    shutil.copytree(original / 'project', target / 'project')
    component = original / 'compiled/component.wasm'
    raw = component.read_bytes()
    assert len(raw) == report['componentBytes']
    assert 'sha256:' + hashlib.sha256(raw).hexdigest() == report['componentDigest']
    shutil.copyfile(component, target / 'component.wasm')
    selections.append({'sourceCommit': report['sourceRevision'], 'variant': report['variant'],
        'reportDigest': 'sha256:' + hashlib.sha256(report_path.read_bytes()).hexdigest(),
        'componentDigest': report['componentDigest'],
        'compilerInputsDigest': 'sha256:' + hashlib.sha256((original / 'compiler-inputs.json').read_bytes()).hexdigest()})
assert len(selections) == 6
files = {p.relative_to(destination).as_posix(): {
    'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'size': p.stat().st_size}
    for p in destination.rglob('*') if p.is_file()}
manifest = {'compilerSource': selections[0]['sourceCommit'], 'selections': selections,
    'files': files, 'sourcePairedCompilerReceipt': 'integration-v12-current-java-six-compiler-v1/receipt.json',
    'signedNodeExecutionQualified': False}
(base / 'jobs/integration-v12-current-java-six-capture-manifest-v2.json').write_text(
    json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'variants': sorted(row['variant'] for row in selections), 'copiedFiles': len(files),
    'capturedSource': manifest['compilerSource'], 'reportsUnmodified': True,
    'signedNodeExecutionQualified': False}))
