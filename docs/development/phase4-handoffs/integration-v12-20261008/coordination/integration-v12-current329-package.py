"""Execute maintained current packaging on separately captured compiler bytes."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
from tools.java_transaction_qualification.current_inputs import CurrentSelection
from tools.java_transaction_qualification.packaging import package_current

base = Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data')
input_root, manifest_path, output = map(Path, sys.argv[1:])
manifest = json.loads(manifest_path.read_text())
expected = manifest['files']

def verify():
    observed = {}
    for path in input_root.rglob('*'):
        if path.is_file():
            assert not path.is_symlink()
            raw = path.read_bytes()
            observed[path.relative_to(input_root).as_posix()] = {
                'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    assert observed == expected, 'original compiler material closure changed'

verify()
selections = tuple((input_root / row['variant'], CurrentSelection(
    row['sourceCommit'], row['variant'], row['reportDigest'], row['componentDigest'],
    row['compilerInputsDigest'])) for row in manifest['selections'])
signed = package_current(selections, output, base / 'target/debug/examples/capsule_contracts',
                         base / 'target/debug/examples/capsule_authoring', timeout=600)
verify()
release = json.loads((signed / 'release-set.json').read_text())
assert release['schemaVersion'] == 'latent.component.signing-fixture.v1'
assert release['trust'] == 'ephemeral-native-package-test-only'
accepted = {row['componentDigest'] for row in manifest['selections'] if row['variant'] != 'forbidden-http'}
assert {row['componentDigest'] for row in release['releases']} == accepted
print(json.dumps({'passed': True, 'compilerSource': manifest['compilerSource'],
    'originalMaterialFiles': len(expected), 'packageCount': len(accepted),
    'negativeProfileRefusal': True, 'nativeSignerExecuted': True,
    'compilerExecutedBySigner': False, 'signedNodeExecutionQualified': False,
    'packagedDistributionQualified': False}))
