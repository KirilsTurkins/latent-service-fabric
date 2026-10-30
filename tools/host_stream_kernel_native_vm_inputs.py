"""One immutable qualified constructor image; never promote stream accounting.

Reuses the ordinary authenticated GitHub artifact and fixed-image readers. The
new programme changes userspace only. No kernel/compiler/sysroot build fallback.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import stat
import time
import zipfile

from tools.java_replay_materials import api
from tools.build_process import run_bounded_result
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json
from tools import host_stream_kernel_vm_image as image
from tools import qualify_host_stream_kernel_objects as objects

SOURCE = '0f1e453448bc10a7d2c60453ab69140283834182'
RUN, JOB, ARTIFACT = 40036590425, 120697476339, 12538540188
ZIP_BYTES = 17174886
ZIP_SHA = '8d5fe3c3fce9ea944f8e11a3bc2a59101e284ba8a9404ac134c51efc18a96875'
PUBLIC = 'docs/testing/evidence/kernel-no-begin-root-physical-return-2026-10-24.json'
PUBLIC_SHA = '70e3b6db242821b764af94c0dab62711eda962bc80e16752ec64ae2f565a0ffa'
QUALIFICATION_SHA = '423855dfc2527c2a4aa5c0a19e1c049eb5e280be0f12b189d789c5bbcb99fc0f'
SELECTION_SHA = '1a44e5695903040898289a42284120c1621738666b99922d2e7622e12cef0e0c'
MAX_ZIP, MAX_EXPANDED = 32 * 1024**2, 32 * 1024**2
MEMBERS = ('constructor-bzImage', 'constructor-init', 'constructor-initramfs.cpio',
           'selected.config', 'firmware/bios-256k.bin', 'firmware/linuxboot_dma.bin',
           'firmware/kvmvapic.bin')


def require(value, reason):
    if not value:
        raise ValueError('native-constructor-image-' + reason)


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def public_receipt():
    raw = read_file(ROOT/PUBLIC, 256*1024).replace(b'\r\n', b'\n')
    require(identity(raw)['sha256'] == PUBLIC_SHA, 'public-receipt-preimage')
    value = json.loads(raw)
    require(value['status'] == 'passed' and value['source']['commit'] == SOURCE
        and value['artifact']['id'] == ARTIFACT and value['artifact']['sha256'] == ZIP_SHA,
        'public-source-artifact-link')
    return value


def origin(run, job, artifact):
    require(type(run.get('run_attempt')) is int and run['run_attempt'] == 1
        and run['id'] == RUN and run['head_sha'] == SOURCE and run['event'] == 'push'
        and run['head_branch'] == 'feat/kernel-no-begin-root-final-free-20261024'
        and run['path'] == '.github/workflows/stream-kernel-constructor-vm.yml'
        and run['status'] == 'completed' and run['conclusion'] == 'success', 'successful-run')
    require(job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == SOURCE
        and job['status'] == 'completed' and job['conclusion'] == 'success'
        and all(row['conclusion'] in ('success', 'skipped') for row in job['steps']), 'successful-job')
    require(type(artifact.get('size_in_bytes')) is int and artifact['size_in_bytes'] == ZIP_BYTES
        and artifact['id'] == ARTIFACT and artifact['expired'] is False
        and artifact['digest'] == 'sha256:'+ZIP_SHA
        and artifact['name'] == 'stream-kernel-constructor-vm-'+SOURCE
        and artifact['workflow_run']['id'] == RUN
        and artifact['workflow_run']['head_sha'] == SOURCE, 'exact-artifact')


def validate_members(members):
    public = public_receipt()
    require('FAILED.json' not in members and all(name in members for name in MEMBERS),
        'success-and-selected-members')
    require(identity(members['qualification.json']) ==
        {'bytes': 210897, 'sha256': QUALIFICATION_SHA}
        and identity(members['selection.json']) == {'bytes': 204341, 'sha256': SELECTION_SHA},
        'immutable-raw-receipts')
    value = json.loads(members['qualification.json'])
    require(value['sourceCommit'] == SOURCE and value['status'] == 'passed'
        and all(value[name] is True for name in ('kernelLinked', 'kernelBooted',
            'actualLinuxExecution', 'rootFinalFree', 'actualLateFdCollection', 'actualNoBeginCollection'))
        and all(value[name] is False for name in ('actualNativeLedger', 'nativeNodeIntegration',
            'consumerSelected', 'completeAllocationClosure', 'productionInstallation')),
        'historical-qualified-scope')
    materials = {}
    for field in ('recipeInputs', 'localSourceFreeze', 'baselineSourceFreeze'):
        for name, bound in value[field].items():
            require(name not in materials or materials[name] == bound, 'conflicting-material')
            materials[name] = bound
    encoded = json.dumps(materials, sort_keys=True, separators=(',', ':')).encode()
    require(len(materials) == 294 and identity(encoded)['sha256'] ==
        public['sourceBinding']['canonicalInventorySha256'], 'all-original-materials')
    for name, bound in materials.items():
        # All old kernel-producing inputs remain source-identical. The added
        # native fixture/workflow is separate, not an old producer relabelling.
        require(identity(read_file(ROOT/name, 4*1024**2)) == bound, 'kernel-source-drift')
    for member, key in (('constructor-bzImage','kernelImage'), ('constructor-init','init'),
                        ('constructor-initramfs.cpio','initramfs')):
        require(identity(members[member]) == {k:value[key][k] for k in ('bytes','sha256')},
            'retained-image-binding')
    require(image.kernel_image(members['constructor-bzImage']) == public['images']['kernel'],
        'original-kernel-identity')
    require(image.check_boot_configuration(members['selected.config'], objects.configuration)
        == value['bootConfiguration'], 'original-config-identity')
    for name, bound in public['firmware'].items():
        require(identity(members['firmware/'+name]) == bound == value['firmware'][name],
            'original-firmware-identity')
    return {'source': SOURCE, 'run': RUN, 'job': JOB, 'artifact': ARTIFACT,
        'archive': {'bytes': ZIP_BYTES, 'sha256': ZIP_SHA}, 'producerStatus': 'passed',
        'kernelSourceMaterials': materials, 'kernelRebuilt': False,
        'originalImage': public['images']['kernel'], 'nativeQuotaReleased': False,
        'productionInstallation': False, 'completeAllocationClosure': False}


def prepare(output):
    run = api(f'actions/runs/{RUN}')
    job = api(f'actions/jobs/{JOB}')
    artifact = api(f'actions/artifacts/{ARTIFACT}')
    origin(run, job, artifact)
    output = fresh(output)
    require(bool(os.environ.get('GH_TOKEN')), 'read-only-artifact-token')
    # The maintained owner supervises gh plus descendants, its full wall clock
    # and output bound. Its115s capture plus5s maximum cleanup fit120s.
    # No hand-written redirect/transport or unbounded read.
    started = time.monotonic()
    downloaded = run_bounded_result(['gh', 'api',
        f'repos/KirilsTurkins/latent-service-fabric/actions/artifacts/{ARTIFACT}/zip'],
        cwd=ROOT, env=dict(os.environ), timeout_seconds=115, max_output_bytes=MAX_ZIP)
    elapsed = time.monotonic()-started
    require(elapsed <= 120, 'download-total-deadline')
    require(downloaded.returncode == 0, 'download-command')
    raw = downloaded.stdout
    require(identity(raw) == {'bytes': ZIP_BYTES, 'sha256': ZIP_SHA}, 'whole-archive-identity')
    archive_path = output/'original-image.zip'
    archive_path.write_bytes(raw)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) == 55
            and sum(row.file_size for row in archive.infolist()) <= MAX_EXPANDED, 'archive-bounds')
        members = {}
        for row in archive.infolist():
            name = row.filename
            require(PurePosixPath(name).as_posix() == name and not PurePosixPath(name).is_absolute()
                and '..' not in PurePosixPath(name).parts and '\\' not in name and ':' not in name
                and not row.is_dir() and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG),
                'archive-regular-member')
            members[name] = archive.read(row)  # All55 CRCs, whole authenticated ZIP.
    record = validate_members(members)
    record['download'] = {'exitCode': downloaded.returncode, 'elapsedMillis': elapsed*1000,
        'captureSeconds':115,'maximumCleanupSeconds':5,
        'supervisedWallSeconds': 120, 'wholeArchiveAuthenticated': True}
    for name in MEMBERS:
        target = output/name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(members[name])
    for name in ('qualification.json','selection.json','commands.json'):
        (output/name).write_bytes(members[name])
    write_json(output/'origin.json', record)
    return output, record
