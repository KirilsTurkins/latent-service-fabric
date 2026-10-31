"""Run the unchanged signed GC programme on the authenticated a5c component."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import java_checkpoint_gc_retained as retained, rust_thread_native_products as products
from tools.java_checkpoint_gc_node import execute
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_java_checkpoint_gc import MATERIALS, build_evidence
from tools.rust_capsule_project import ROOT, fresh, write_json

EXTRA = ('tools/java_checkpoint_gc_retained.py', 'tools/qualify_java_checkpoint_gc_retained.py',
    'tools/tests/test_java_checkpoint_gc_retained.py', retained.PINS)


def qualify(native_directory, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'java-gc-retained-linux-python313')
    native_directory = Path(native_directory).resolve(strict=True);output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and output != native_directory and output not in native_directory.parents
        and native_directory not in output.parents, 'java-gc-retained-separated-inputs')
    deadline = time.monotonic()+900
    origin = products.verify_prepared(native_directory);native = products.native_products(native_directory)
    for path in native.values():path.chmod(0o700)
    consumer = source_identity(ROOT)
    before = {n: file_identity(ROOT/n) for n in (*MATERIALS, *EXTRA)}
    output = fresh(output)
    record = {'schemaVersion': 'lsf.java.gc.retained-runtime-qualification.v1', 'status': 'incomplete',
        'consumerSource': consumer, 'materials': before, 'nativeOrigin': origin,
        'guestComponentsCompiled': 0, 'nativeProductsBuilt': 0, 'compilerInvocations': 0,
        'originalProducerSource': retained.SOURCE, 'originalProducerRun': retained.RUN,
        'originalProducerJob': retained.JOB, 'originalProducerConclusion': 'failure',
        'historicalGuestQualificationRelabelled': False, 'fullTicketQualification': False,
        'garbageCollectionObserved': False}
    stage = 'authenticate-original-failed-producer-and-package-recovery'
    try:
        artifact, proof = retained.prepare(output/'retained')
        record['retained'] = proof
        stage = 'unchanged-signed-four-case-and-two-grant-denial-programme'
        record['node'] = execute(artifact, native, output/'node', deadline, proof['build']['component']['sha256'])
        require(build_evidence(artifact) == proof['build']
            and retained.source_proof(artifact.parent) == proof['sourceBridge']
            and origin == products.verify_prepared(native_directory) and consumer == source_identity(ROOT)
            and before == {n: file_identity(ROOT/n) for n in before} and time.monotonic() < deadline,
            'java-gc-retained-final-source-and-native-and-component-fences')
        for name, row in proof['packageRecovery']['originalPackageInputs'].items():
            require(file_identity(artifact/name) == {'sha256': row['digest'], 'bytes': row['size']},
                'java-gc-retained-final-original-package-inputs')
        record.update(status='passed', garbageCollectionObserved=True)
        write_json(output/'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'output'):parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(qualify(args.native, args.output)['status'])
