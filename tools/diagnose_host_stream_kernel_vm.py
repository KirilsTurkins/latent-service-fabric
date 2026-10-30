"""Boot one authenticated retained failed-run image with a numeric PID1 probe.

No kernel rebuild, installation, external network or constructor qualification.
The original failed observation remains failed. Only /init changes in its fixed
five-entry initramfs; all kernel-producing source inputs remain byte identical.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import host_stream_kernel_vm_image as image
from tools import qualify_host_stream_kernel_objects as objects
from tools.build_observation import build_environment
from tools.java_replay_materials import NoRedirect
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json

SOURCE = '556c065ccc49205709da1f18ce0d871feaf9d0a4'
RUN, JOB, ARTIFACT = 39928143452, 120329504000, 12491371397
ZIP_BYTES = 15002593
ZIP_SHA = '8217fcf127edfca863378a6f87a183bf44c02bade656849667607730277a5e75'
REPOSITORY = 'KirilsTurkins/latent-service-fabric'
PROBE = 'research/standard-outbound/linux-6.12-lineage/constructor-vm-init.c'
CHANGED_RECIPE = {PROBE}  # A separate workflow does not alter the old recipe.
MAX_ZIP, MAX_EXPANDED = 32 * 1024**2, 32 * 1024**2


def require(value, reason):
    if not value:
        raise ValueError('kernel-vm-numeric-' + reason)


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def api(path):
    raw = subprocess.check_output(['gh', 'api', 'repos/' + REPOSITORY + '/' + path], timeout=30)
    require(len(raw) <= 1024**2, 'api-bound')
    return json.loads(raw)


def origin(metadata, job):
    require(metadata['id'] == ARTIFACT and metadata['size_in_bytes'] == ZIP_BYTES
        and metadata['digest'] == 'sha256:' + ZIP_SHA and not metadata['expired']
        and metadata['workflow_run']['id'] == RUN
        and metadata['workflow_run']['head_sha'] == SOURCE, 'artifact-origin')
    require(job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == SOURCE
        and job['status'] == 'completed' and job['conclusion'] == 'failure', 'failed-job-origin')


def acquire(output):
    metadata, job = api(f'actions/artifacts/{ARTIFACT}'), api(f'actions/jobs/{JOB}')
    origin(metadata, job)
    token = os.environ.get('GH_TOKEN')
    require(bool(token), 'read-only-artifact-token')
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT}/zip',
        headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'artifact-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('kernel-vm-numeric-artifact-redirect-required')
    require(url.startswith('https://'), 'artifact-https')
    with urllib.request.urlopen(url, timeout=60) as response:
        require(response.status == 200, 'artifact-download-status')
        raw = response.read(MAX_ZIP + 1)
    require(identity(raw) == dict(bytes=ZIP_BYTES, sha256=ZIP_SHA), 'whole-archive-identity')
    archive_path = output / 'retained-image.zip'
    archive_path.write_bytes(raw)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) == 33
            and sum(row.file_size for row in archive.infolist()) <= MAX_EXPANDED,
            'fixed-archive-bounds')
        members = {}
        for row in archive.infolist():
            name = row.filename
            require(not Path(name).is_absolute() and '..' not in Path(name).parts
                and '\\' not in name and ':' not in name and not row.is_dir()
                and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG), 'archive-member')
            members[name] = archive.read(row)  # CRC checked, whole ZIP authenticated.
    observation = json.loads(members['FAILED.json'])
    require(observation['sourceCommit'] == SOURCE and observation['status'] == 'failed'
        and observation['stage'] == 'isolated-constructor-vm'
        and observation['kernelLinked'] is True and observation['consumerSelected'] is False
        and observation['rootFinalFree'] is False
        and observation['completeAllocationClosure'] is False, 'original-link-only-observation')
    for member, key in (('constructor-bzImage', 'kernelImage'), ('constructor-init', 'init'),
                        ('constructor-initramfs.cpio', 'initramfs')):
        require(identity(members[member]) == {k: observation[key][k] for k in ('bytes', 'sha256')},
                'retained-image-link')
    materials = {}
    for key in ('recipeInputs', 'localSourceFreeze', 'baselineSourceFreeze'):
        for name, bound in observation[key].items():
            require(name not in materials or materials[name] == bound, 'conflicting-source-link')
            materials[name] = bound
    for name, bound in materials.items():
        if name not in CHANGED_RECIPE:
            require(objects.identity(ROOT / name) == bound, 'kernel-producing-source-drift')
    require(identity(members['constructor-init.c']) == materials[PROBE], 'original-probe-source')
    write_json(output / 'retained-image-origin.json', dict(source=SOURCE, run=RUN, job=JOB,
        artifact=ARTIFACT, wholeArchive=identity(raw), producerStatus='failed',
        sourceMaterials=materials, changedRecipe=sorted(CHANGED_RECIPE)))
    return members, observation


def replace_init(original, old_init, new_init):
    """Replace only /init in the authenticated upstream gen_init_cpio output."""
    require(len(original) <= image.MAX_INITRAMFS and len(new_init) <= image.MAX_INIT,
            'cpio-size')
    position, result = 0, bytearray()
    expected = ('dev', 'dev/console', 'proc', 'sys', 'init', 'TRAILER!!!')
    modes = (0o40755, 0o20600, 0o40555, 0o40555, 0o100755, 0)
    for ordinal, name in enumerate(expected):
        begin = position
        header = original[position:position+110]
        require(len(header) == 110 and header[:6] == b'070701'
            and re.fullmatch(b'[0-9a-fA-F]{104}', header[6:]) is not None, 'cpio-header')
        fields = [int(header[6+i*8:14+i*8], 16) for i in range(13)]
        size, length = fields[6], fields[11]
        require(fields[1] == modes[ordinal] and fields[2:4] == [0, 0]
            and fields[5] == fields[12] == 0 and length == len(name)+1,
            'cpio-fixed-entry')
        position += 110
        require(original[position:position+length] == name.encode()+b'\0', 'cpio-fixed-name')
        position = (position+length+3)&~3
        require(position+size <= len(original), 'cpio-payload-range')
        payload = original[position:position+size]
        position = (position+size+3)&~3
        if name == 'init':
            require(payload == old_init, 'cpio-original-init')
            # gen_init_cpio emits uppercase hexadecimal. Preserve every other
            # authenticated header byte instead of canonicalizing its spelling.
            changed_header = bytearray(header)
            changed_header[54:62] = f'{len(new_init):08X}'.encode()
            result.extend(changed_header)
            result.extend(name.encode()+b'\0')
            result.extend(bytes((-len(result))%4))
            result.extend(new_init)
            result.extend(bytes((-len(result))%4))
        else:
            require(size == 0, 'cpio-unexpected-payload')
            result.extend(original[begin:position])
    require(not any(original[position:]) and len(original)%512 == 0, 'cpio-tail')
    result.extend(bytes((-len(result))%512))
    require(len(result) <= image.MAX_INITRAMFS, 'cpio-result-size')
    return bytes(result)


def run(output):
    require(sys.platform == 'linux', 'isolated-linux-host')
    output = fresh(output)
    record = dict(schemaVersion='lsf.kernel-constructor-numeric-diagnostic.v1', status='incomplete',
        kernelRebuilt=False, constructorQualification=False, productionInstallation=False,
        actualNativeLedger=False, rootFinalFree=False, completeAllocationClosure=False)
    try:
        members, old = acquire(output)
        commands = Commands(ROOT, output, build_environment(output),
                            deadline_seconds=300, command_seconds=image.VM_SECONDS)
        init, record['init'] = image.build_init(commands, Path('/usr/bin/gcc'),
                                               (ROOT/PROBE).read_bytes(), output)
        original = members['constructor-initramfs.cpio']
        require(replace_init(original, members['constructor-init'], members['constructor-init'])
                == original, 'unchanged-init-reproduces-original-cpio')
        cpio = output/'constructor-initramfs.cpio'
        cpio.write_bytes(replace_init(original, members['constructor-init'], init.read_bytes()))
        kernel = output/'constructor-bzImage';kernel.write_bytes(members['constructor-bzImage'])
        image.kernel_image(kernel.read_bytes())
        firmware = output/'firmware';firmware.mkdir()
        for name, bound in old['firmware'].items():
            require(name in {'bios-256k.bin','linuxboot_dma.bin','kvmvapic.bin'}
                and identity(members['firmware/'+name]) == bound, 'original-firmware')
            (firmware/name).write_bytes(members['firmware/'+name])
        serial = commands.run('boot-same-linked-image-numeric-probe',
            *image.boot_argv(Path('/usr/bin/qemu-system-x86_64'), kernel, cpio, firmware))
        rows = [line.decode('ascii') for line in serial.splitlines() if line.startswith(b'LSFVM1 ')]
        require(len(serial) <= image.MAX_SERIAL and 3 <= len(rows) <= 6, 'numeric-serial-bound')
        require(sum(bool(re.fullmatch(r'LSFVM1 begin-refusal result=-?[0-9]{1,3} errno=[0-9]{1,4} diagnostic-bytes=-?[0-9]{1,3}', row))
                    for row in rows) == 1, 'actual-numeric-begin-refusal-required')
        record.update(status='observed-refusal', serialRows=rows, commands=commands.records,
            originalImage=old['kernelImage'], derivedInitramfs=identity(cpio.read_bytes()),
            currentProbe=objects.identity(ROOT/PROBE), retainedProducerRemainsFailed=True)
        return record
    finally:
        write_json(output/'numeric-diagnostic.json', record)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
