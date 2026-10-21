"""Reuse the exact successful backend step from the failed5265 outer job.

The original failure is never promoted to qualification. Normal Prepared still
checks current producer sources and exact compiler/composer/component bytes.
"""
from pathlib import Path

from tools import replay_rust_wasi_http_async_runtime as retained
from tools import rust_wasi_http_inputs as runtime
from tools.java_replay_materials import api
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, read_json

MATERIALS = ('tools/rust_wasi_http_current_backend.py',
    'tools/replay_rust_wasi_http_async_runtime.py', retained.PINS,
    '.github/workflows/rust-wasi-http-streamed-post.yml')


def backend_step(job):
    steps = [row for row in job['steps']
        if row['name'] == 'Compile exactly one current source-bound standard backend']
    require(len(steps) == 1 and type(steps[0]['number']) is int and steps[0]['number'] == 12
        and steps[0]['status'] == 'completed' and steps[0]['conclusion'] == 'success',
        'rust-http-current-backend-actual-successful-step-in-failed-outer')
    return steps[0]['name']


def verify(restored, directory):
    restored = Path(restored).resolve(strict=True)
    directory = Path(directory).resolve(strict=True)
    require(directory == restored / 'rust-http-current-backend',
        'rust-http-current-backend-exact-retained-directory')
    pins = read_json(ROOT / retained.PINS, 1024**2)
    require(pins['source'] == retained.SOURCE and pins['run'] == retained.RUN
        and pins['job'] == retained.JOB and len(pins['members']) == 341,
        'rust-http-current-backend-fixed-original-inventory')
    require(retained.artifact_inventory(restored) == pins['members'],
        'rust-http-current-backend-all-original341-member-identities')
    run = api(f'actions/runs/{retained.RUN}')
    job = api(f'actions/jobs/{retained.JOB}')
    artifact = api(f'actions/artifacts/{pins["artifact"]["id"]}')
    retained.validate_origin(run, job, artifact, pins)
    step = backend_step(job)
    require(len(pins['backendMaterials']) == 7 and all(
        file_identity(directory / name, 64*1024**2) == row
        for name, row in pins['backendMaterials'].items()),
        'rust-http-current-backend-seven-original-materials')
    receipt = read_json(directory / runtime.RECEIPT)
    runtime._bounded_record(receipt)
    source = read_file(directory / 'source-inputs.json', runtime.MAX_SOURCE)
    rows = read_json(directory / 'source-inputs.json', runtime.MAX_SOURCE)
    require(receipt['sourceRows'] == len(rows) == 110 and digest(source) == receipt['sourceDigest']
        and inventory(runtime.source_files()) == source,
        'rust-http-current-backend-original-producer-sources-still-byte-exact')
    originals = retained.git_files(rows)
    require(all(row == {'digest': digest(originals[name]), 'size': len(originals[name])}
        for name, row in rows.items()), 'rust-http-current-backend-all110-original-git-preimages')
    return {'buildKind': 'retained-successful-current-source-backend-step',
        'originalCompilerSource': retained.SOURCE, 'run': retained.RUN, 'job': retained.JOB,
        'originalOuterConclusion': 'failure', 'backendStep': step,
        'backendStepConclusion': 'success', 'artifact': pins['artifact'],
        'originalArtifactMembers': 341, 'selectedOriginalMaterials': pins['backendMaterials'],
        'producerReceipt': file_identity(directory / runtime.RECEIPT),
        'sourceInventory': file_identity(directory / 'source-inputs.json'),
        'currentProducerSourceByteExact': True, 'receiptRewritten': False,
        'historicalAdapterReceiptRebound': False, 'backendCompilationPerformed': False,
        'originalOuterPromotedToPass': False, 'signedQualification': False}
