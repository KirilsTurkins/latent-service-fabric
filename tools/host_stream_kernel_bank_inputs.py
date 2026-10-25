"""One successful observation-ABI image; new bank consumption is separate.

Fixed selection using the existing supervised artifact and image readers.
There is no historical pre-ioctl fallback, kernel build or generic replay API.
"""
from pathlib import Path, PurePosixPath
import json
import os
import stat
import time
import zipfile

from tools.java_replay_materials import api
from tools.build_process import run_bounded_result
from tools.rust_capsule_project import ROOT, canonical, fresh, read_file, write_json
from tools import host_stream_kernel_native_vm as native
from tools import host_stream_kernel_return_vm as observed
from tools import qualify_host_stream_kernel_objects as objects

SOURCE = '15167d63a3aef6d211ffc83c9591890d4d2486b2'
RUN, JOB, ARTIFACT = 40144839812, 121023860613, 12580134816
ZIP_BYTES = 19602627
ZIP_SHA = 'deb69e68dbb73a072429a087382ea54f796214abe91d444a857dfd88a538f895'
PUBLIC = 'docs/testing/evidence/kernel-native-root-return-observation-2026-10-25.json'
PUBLIC_SHA = 'f38065b09321d4628118b31689a96ff55c3029df50da30032e1e7a1a56c683c8'
RAW_RECEIPT = {'bytes':2740684,'sha256':'b52f6f31f1cb8967c9a0601f1fd8be9fc33b5ab6fb8c2c2c9a441575951b6b41'}
RAW_SELECTION = {'bytes':1609636,'sha256':'53c905dbe4ca95b3ff1127e9bc5b0ccbf951db1ce2d189fc4cfdd0221982ebf1'}
MAX_ZIP = MAX_EXPANDED = 32 * 1024**2
MEMBERS = ('kernel/constructor-bzImage','kernel/selected.config','constructor-init',
           'constructor-initramfs.cpio','constructor-init.c','firmware/bios-256k.bin',
           'firmware/linuxboot_dma.bin','firmware/kvmvapic.bin')
identity, require = native.identity, native.require


def public_receipt():
    raw = read_file(ROOT/PUBLIC,256*1024).replace(b'\r\n',b'\n')
    require(identity(raw)['sha256'] == PUBLIC_SHA,'bank-original-public-receipt')
    public = json.loads(raw)
    require(public['status'] == 'passed' and public['sourceRevision'] == SOURCE
        and public['qualification']['artifactId'] == ARTIFACT
        and public['qualification']['artifactSha256'] == ZIP_SHA,'bank-public-origin')
    return public


def origin(run,job,artifact):
    require(type(run.get('run_attempt')) is int and run['run_attempt'] == 1
        and run['id'] == RUN and run['head_sha'] == SOURCE and run['event'] == 'push'
        and run['head_branch'] == 'feat/kernel-native-return-vm-20261024'
        and run['path'] == '.github/workflows/stream-kernel-return-vm.yml'
        and run['status'] == 'completed' and run['conclusion'] == 'success','bank-successful-producer')
    require(job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == SOURCE
        and job['status'] == 'completed' and job['conclusion'] == 'success'
        and type(job.get('steps')) is list and bool(job['steps'])
        and all(s['conclusion'] == 'success' for s in job['steps']),'bank-successful-job')
    require(type(artifact.get('size_in_bytes')) is int and artifact['size_in_bytes'] == ZIP_BYTES
        and artifact['id'] == ARTIFACT and artifact['expired'] is False
        and artifact['digest'] == 'sha256:'+ZIP_SHA
        and artifact['name'] == 'stream-kernel-return-vm-'+SOURCE
        and artifact['workflow_run']['id'] == RUN
        and artifact['workflow_run']['head_sha'] == SOURCE,'bank-exact-artifact')


def validate_members(members):
    public = public_receipt()
    require(set(members) == set(public['retainedMembers']) and len(members) == 70
        and 'FAILED.json' not in members,'bank-complete-retained-union')
    require(all(identity(raw) == public['retainedMembers'][name] for name,raw in members.items()),
        'bank-retained-member-identity')
    require(identity(members['receipt.json']) == RAW_RECEIPT
        and identity(members['kernel/selection.json']) == RAW_SELECTION,'bank-original-raw-receipts')
    value = json.loads(members['receipt.json'])
    require(value['sourceRevision'] == SOURCE and value['status'] == 'passed'
        and value['sourceBefore'] == value['sourceAfter'] and value['sourceUnchanged'] is True
        and value['kernelLinked'] is True and value['freshVmAttempts'] == value['validatedVmBoots'] == 1
        and value['actualNativeKernelRootReturned'] is True
        and value['actualKernelPhysicalReturn'] is True
        and value['originalNodeCapacityQuarantined'] is True
        and all(value[name] is False for name in ('nativeQuotaReleased','productionInstallation',
            'completeAllocationClosure','fullVfsLsmCostsQualified','wholeNodeExecuted','hostTlsQualified')),
        'bank-original-qualified-scope')
    require(len(value['sourceBefore']) == 6471 and identity(canonical(value['sourceBefore']))['sha256']
        == public['sourceBinding']['qualifiedSourceBefore']['canonicalInventorySha256'],
        'bank-original-source-invariance')
    materials = value['compiledKernelProducerMaterials']
    require(len(materials) == 296 and identity(canonical(materials))['sha256']
        == public['sourceBinding']['kernelProducerMaterials']['canonicalInventorySha256'],
        'bank-original-kernel-materials')
    require(set(value['historicalKernelProducerMaterials']) | set(value['additionalKernelProducerMaterials'])
        == set(materials) and len(value['historicalKernelProducerMaterials']) == 294
        and len(value['additionalKernelProducerMaterials']) == 2,'bank-original-294-plus-2')
    for name,bound in materials.items():
        require(identity(read_file(ROOT/name,4*1024**2)) == bound,'bank-current-kernel-source-drift')
    # Current Rust consumers are intentionally new. The complete old native
    # source capture remains at SOURCE; only kernel-producing inputs must equal
    # this immutable image. New consumer inputs are separately captured.
    require(native.image.kernel_image(members['kernel/constructor-bzImage']) == value['kernelImage']
        and native.image.check_boot_configuration(members['kernel/selected.config'],objects.configuration)
            == value['bootConfiguration'],'bank-qualified-image-config')
    pid1 = members['constructor-init']
    require(native.image.init_elf(pid1) == {k:value['supervisor'][k]
        for k in ('bytes','sha256','loadSegments','staticX86_64')},'bank-qualified-pid1')
    require(members['constructor-init.c'] == native.supervisor_source()
        and identity(members['constructor-init.c'])['sha256'] == value['supervisor']['sourceSha256'],
        'bank-qualified-pid1-source')
    require(native.native_initramfs(members['constructor-initramfs.cpio'],pid1,pid1,members['native-init'])
        == members['native-return-initramfs.cpio'],'bank-qualified-base-cpio')
    for name,bound in value['firmware'].items():
        require(identity(members['firmware/'+name]) == bound,'bank-qualified-firmware')
    commands = json.loads(members['commands.json'])
    require(commands == public['commands'] and len(commands) == 26
        and all(type(row['exitCode']) is int and row['exitCode'] == 0 for row in commands),
        'bank-successful-producer-commands')
    serial = members['commands/logs/25-one-real-native-return-vm.stdout.txt']
    require(observed.serial_observation(serial) == value['observations']
        == public['vm']['observations'],'bank-real-producer-observation')
    return {'source':SOURCE,'run':RUN,'job':JOB,'artifact':ARTIFACT,
        'archive':{'bytes':ZIP_BYTES,'sha256':ZIP_SHA},'producerStatus':'passed',
        'kernelSourceMaterials':materials,'kernelRebuilt':False,
        'originalImage':value['kernelImage'],'originalSupervisor':value['supervisor'],
        'selectedBootMaterials':{name:identity(members[name]) for name in MEMBERS},
        'originalCompiledCControls':value['compiledParserControls'],
        'producerNativeQuotaReleased':False,'newBankConsumerExecuted':False,
        'productionInstallation':False,'completeAllocationClosure':False}


def prepare(output,deadline):
    # Three existing fixed metadata reads each have a 30-second cap. Refuse
    # before starting them when the original consumer budget cannot cover that.
    require(type(deadline) is float and 95 <= deadline-time.monotonic() <= 1320,
        'bank-original-input-deadline')
    origin(api(f'actions/runs/{RUN}'),api(f'actions/jobs/{JOB}'),api(f'actions/artifacts/{ARTIFACT}'))
    output = fresh(output)
    require(bool(os.environ.get('GH_TOKEN')),'bank-read-only-artifact-token')
    started = time.monotonic()
    capture = min(115,deadline-time.monotonic()-5)
    require(capture > 0,'bank-original-input-deadline')
    downloaded = run_bounded_result(['gh','api',
        f'repos/KirilsTurkins/latent-service-fabric/actions/artifacts/{ARTIFACT}/zip'],
        cwd=ROOT,env=dict(os.environ),timeout_seconds=capture,max_output_bytes=MAX_ZIP)
    elapsed = time.monotonic()-started
    require(elapsed <= 120 and downloaded.returncode == 0,'bank-supervised-download')
    raw = downloaded.stdout
    require(identity(raw) == {'bytes':ZIP_BYTES,'sha256':ZIP_SHA},'bank-whole-archive')
    archive_path = output/'qualified-observation-image.zip';archive_path.write_bytes(raw)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) == 70
            and sum(row.file_size for row in archive.infolist()) <= MAX_EXPANDED,'bank-archive-bounds')
        members = {}
        for row in archive.infolist():
            name = row.filename
            require(PurePosixPath(name).as_posix() == name and not PurePosixPath(name).is_absolute()
                and '..' not in PurePosixPath(name).parts and '\\' not in name and ':' not in name
                and not row.is_dir() and stat.S_IFMT(row.external_attr >> 16) in (0,stat.S_IFREG),
                'bank-regular-archive-member')
            members[name] = archive.read(row)
    record = validate_members(members)
    require(time.monotonic() < deadline,'bank-original-input-deadline')
    record['download'] = {'elapsedMillis':elapsed*1000,'captureSeconds':capture,'maximumCaptureSeconds':115,
        'maximumCleanupSeconds':5,'supervisedWallSeconds':120,'wholeArchiveAuthenticated':True}
    for name in MEMBERS:
        target = output/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(members[name])
    for name in ('receipt.json','commands.json','source-inputs.json','kernel/selection.json'):
        (output/name).write_bytes(members[name])
    write_json(output/'origin.json',record)
    return output,record
