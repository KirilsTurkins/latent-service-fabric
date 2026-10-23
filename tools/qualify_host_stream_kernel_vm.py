"""One linked isolated constructor VM; physical Root final-free stays unqualified."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import host_stream_kernel_cleanup_native_programme as programme
from tools import host_stream_kernel_vm_image as image

baseline = programme.baseline
objects = baseline.objects
paths = baseline.paths
require = baseline.require
ROOT = programme.ROOT
BRANCH = 'feat/stream-kernel-vm-qualification-20261023'
WORKFLOW = '.github/workflows/stream-kernel-constructor-vm.yml'
PROBE = 'research/standard-outbound/linux-6.12-lineage/constructor-vm-init.c'


def recipe_inputs():
    names = ('tools/qualify_host_stream_kernel_vm.py',
        'tools/host_stream_kernel_vm_image.py',
        'tools/host_stream_kernel_cleanup_native_programme.py',
        'tools/host_stream_kernel_cleanup_native.py',
        'tools/host_stream_kernel_constructor_failure.py',
        'tools/host_stream_kernel_stack_alignment.py',
        'tools/host_stream_kernel_vmap_extent.py',
        'tools/host_stream_kernel_vmap_fit.py',
        'tools/host_stream_kernel_task_identity_geometry.py',
        'tools/qualify_host_stream_kernel_objects.py',
        'tools/owned_test_process.py', 'tools/build_observation.py',
        'tools/dev_workflow/paths.py', WORKFLOW, PROBE)
    return {name: objects.identity(ROOT/name) for name in names}


def tool_identity(path, maximum=64 * 1024**2):
    checksum, size = paths.digest_file(path.parent,path.name,maximum)
    require(0 < size <= maximum, 'constructor-vm-tool-byte-bound')
    return dict(bytes=size,sha256=checksum.removeprefix('sha256:'))


def run(archive, output):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true' and
        os.environ.get('RUNNER_OS') == 'Linux', 'constructor-vm-hosted-linux-only')
    origin = {name:os.environ.get(name) for name in ('GITHUB_REPOSITORY','GITHUB_EVENT_NAME','GITHUB_REF_NAME')}
    require(origin['GITHUB_REPOSITORY']=='KirilsTurkins/latent-service-fabric' and
        origin['GITHUB_REF_NAME']==BRANCH and origin['GITHUB_EVENT_NAME'] in ('workflow_dispatch','push'),
        'constructor-vm-fixed-origin')
    value = baseline.maintained.manifest()
    output = paths.absolute(output)
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'constructor-vm-outside-checkout-output')
    paths.new_directory(output)
    recipe, local = recipe_inputs(), programme.local_freeze()
    archive = objects.snapshot_archive(archive, output/'source.tar.xz', value['archive'])
    extras = {'net/Kconfig','net/Makefile'} | set(objects.packet_source.fixture()['source'])
    originals = baseline.maintained.authenticate_archive(archive, value,
        tuple(sorted(extras - set(value['source']))))
    archive_identity = objects.identity(archive)
    tools = {name:shutil.which(name) for name in ('tar','make','gcc','qemu-system-x86_64')}
    require(all(tools.values()), 'constructor-vm-kbuild-tools')
    log, source_root = output/'commands', output/'source'
    log.mkdir(); source_root.mkdir()
    env = objects.build_environment(output)
    env.update(KBUILD_BUILD_USER='lsf-object-check',KBUILD_BUILD_HOST='isolated-ci',
        KBUILD_BUILD_TIMESTAMP='2026-10-23 00:00:00 UTC',KCONFIG_NOTIMESTAMP='1')
    commands = objects.Commands(source_root,log,env,deadline_seconds=2400,command_seconds=1800)
    tool_paths = {name: Path(path).resolve(strict=True) for name, path in tools.items()}
    tool_pins = {name: tool_identity(path) for name, path in tool_paths.items()}
    receipt = dict(schemaVersion='lsf.kernel-constructor-vm-observation.v1',
        status='in-progress', origin=origin, sourceCommit=subprocess.check_output(
            ['git','rev-parse','HEAD'],cwd=ROOT,timeout=15).decode().strip(),
        archive=archive_identity, upstreamCommit=baseline.maintained.COMMIT,
        recipeInputs=recipe, localSourceFreeze=local, observedTools=tool_pins,
        kernelLinked=False, kernelBooted=False, actualLinuxExecution=False,
        actualNativeLedger=False, nativeNodeIntegration=False, rootFinalFree=False,
        consumerSelected=False, completeAllocationClosure=False,
        wholeInfrastructureFitQualified=False, initialBirthBounded=False,
        compilerImplicitInputsAttested=False, productionInstallation=False)
    stage, failed = 'extract', False
    try:
        stage = 'captured-static-pid1'
        init, receipt['init'] = image.build_init(commands,tool_paths['gcc'],
            paths.read(ROOT,PROBE,64*1024),output)
        stage = 'extract'
        commands.run('extract-authenticated-source',tools['tar'],'--extract','--xz',
            '--file',str(archive),'--directory',str(source_root),'--no-same-owner','--no-same-permissions')
        tree = source_root/('linux-'+value['version'])
        commands.root = tree
        require(all((tree/name).read_bytes() == raw for name,raw in originals.items()),
            'constructor-vm-extracted-preimage')
        stage = 'baseline-source-and-config'
        base, frozen, old_originals = programme.baseline_source(tree,originals)
        receipt['baselineSourceFreeze'] = frozen
        original_inputs = {**old_originals,**originals}
        # Fixed stage names read from this same fully authenticated private
        # extraction. Old archive-extra limits and validators remain unchanged.
        for name in sorted(programme.source_names() - {'selected.config'}):
            if name not in original_inputs:
                original_inputs[name] = paths.read(tree,name,baseline.maintained.MAX_FILE)
        require(sum(map(len,original_inputs.values())) <= baseline.maintained.MAX_SELECTED,
            'constructor-vm-selected-byte-bound')
        for name,suffix in (('net/Kconfig',objects.KCONFIG),('net/Makefile',objects.MAKEFILE)):
            raw = original_inputs[name]
            require(objects.SELECTED.encode() not in raw,'constructor-vm-private-config-present')
            (tree/name).write_bytes(raw+suffix.encode())
        build = output/'objects'
        common = [tools['make'],'O='+str(build),'ARCH=x86_64','CC='+tools['gcc']]
        commands.run('compiler-identity',tools['gcc'],'--version')
        commands.run('original-defconfig',*common,'x86_64_defconfig')
        before_raw = (build/'.config').read_bytes()
        (output/'baseline.config').write_bytes(before_raw)
        before = objects.configuration(before_raw)
        require(before.get(objects.SELECTED) == 'n','constructor-vm-private-default-enabled')
        selected_raw = before_raw.replace(b'# CONFIG_LSF_STREAM_FACTORY is not set\n',b'CONFIG_LSF_STREAM_FACTORY=y\n')
        require(selected_raw != before_raw,'constructor-vm-missing-private-config')
        (build/'.config').write_bytes(selected_raw)
        commands.run('resolve-selected-config',*common,'olddefconfig')
        final = (build/'.config').read_bytes()
        baseline.configuration(before,objects.configuration(final))
        (output/'selected.config').write_bytes(final)
        receipt['bootConfiguration'] = image.check_boot_configuration(final, objects.configuration)
        # This generated exact selected config is also independently pinned in
        # the authenticated provider source fixture, never a copied local file.
        stage = 'complete-source-composition'
        fixture_config,receipt['sourceFixtureConfiguration'] = programme.source_fixture_configuration(final)
        # Retain both real selected bytes and the explicit data-only fixture
        # projection. The actual Kbuild configuration is NEVER rewritten.
        (output/'source-fixture.config').write_bytes(fixture_config)
        normal = programme.compose(base,original_inputs,fixture_config)
        derived, receipt['candidateProjection'] = programme.qualification_projection(normal, final)
        receipt['selectedOriginalInputs'] = {name:objects.identity(tree/name)
            for name in programme.source_names() if name != 'selected.config'}
        receipt['normalDerived'], receipt['derived'] = {}, {}
        for name,raw in derived.items():
            target = tree/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(raw)
            receipt['normalDerived'][name] = dict(bytes=len(normal[name]),
                sha256=hashlib.sha256(normal[name]).hexdigest())
            receipt['derived'][name] = objects.identity(target)
        paths.write_new(output/'selection.json',(json.dumps(receipt,indent=2)+'\n').encode())
        stage = 'complete-real-kernel-link'
        commands.run('link-complete-candidate-kernel', *common, '-j2', 'bzImage')
        receipt['kernelLinked'] = True
        baseline.generated_configuration((build/'include/generated/autoconf.h').read_bytes())
        require(b'#define CONFIG_RUST ' not in (build/'include/generated/autoconf.h').read_bytes(),
                'constructor-vm-rust-kernel-must-remain-unselected')
        require((build/'.config').read_bytes() == final, 'constructor-vm-build-config-drift')
        built_kernel = build/'arch/x86/boot/bzImage'
        kernel_raw = paths.read(built_kernel.parent,built_kernel.name,image.MAX_KERNEL)
        receipt['kernelImage'] = image.kernel_image(kernel_raw)
        receipt['linkedVmlinux'] = tool_identity(build/'vmlinux',512*1024**2)
        kernel = output/'constructor-bzImage'
        paths.write_new(kernel,kernel_raw)
        # Full bzImage already builds this exact upstream host tool.
        generator = build/'usr/gen_init_cpio'
        require(generator.is_file(), 'constructor-vm-upstream-initramfs-generator-missing')
        receipt['initramfsGenerator'] = tool_identity(generator)
        initramfs, receipt['initramfs'] = image.build_initramfs(commands,generator,init,output)
        firmware = output/'firmware'
        firmware.mkdir()
        receipt['firmware'] = {}
        firmware_sources = {
            'bios-256k.bin': Path('/usr/share/seabios/bios-256k.bin'),
            'linuxboot_dma.bin': Path('/usr/share/qemu/linuxboot_dma.bin'),
            'kvmvapic.bin': Path('/usr/share/qemu/kvmvapic.bin'),
        }
        for name, source in firmware_sources.items():
            payload = paths.read(source.parent,source.name,1024*1024)
            paths.write_new(firmware/name,payload)
            receipt['firmware'][name] = objects.identity(firmware/name)
        require(sum(row['bytes'] for row in receipt['firmware'].values())<=1024*1024,
                'constructor-vm-firmware-byte-bound')
        commands.run('qemu-version',tool_paths['qemu-system-x86_64'],'--version')
        stage = 'isolated-constructor-vm'
        old_limit = commands.command_seconds
        commands.command_seconds = image.VM_SECONDS
        try:
            serial = commands.run('boot-isolated-real-constructor',
                *image.boot_argv(tool_paths['qemu-system-x86_64'],kernel,initramfs,firmware))
        finally:
            commands.command_seconds = old_limit
        observation = image.serial_observation(serial)
        receipt.update(kernelBooted=True,actualLinuxExecution=True,
            actualTaskControlChildRetirement=True,rootStillHeldAtObservation=True,
            vm=dict(accelerator='tcg-multi',cpus=image.VM_CPUS,memoryMiB=image.VM_MEMORY_MIB,
                externalNetwork=False,hostDrives=False,hostInstallation=False,
                watchdogExpiryIsSuccess=False),
            serial=observation)
        stage = 'final-input-and-image-recheck'
        require(objects.identity(archive) == archive_identity,'constructor-vm-archive-drift')
        require(all(objects.identity(tree/name) == bound for name,bound in receipt['derived'].items()),
                'constructor-vm-derived-source-drift')
        require(all(objects.identity(ROOT/name) == bound for name,bound in frozen.items())
            and programme.local_freeze() == local and recipe_inputs() == recipe,
                'constructor-vm-local-source-drift')
        require({name:tool_identity(path) for name,path in tool_paths.items()}==tool_pins,
                'constructor-vm-tool-drift')
        require(image.kernel_image(paths.read(output,kernel.name,image.MAX_KERNEL))==receipt['kernelImage']
            and image.init_elf(paths.read(output,init.name,image.MAX_INIT))['sha256']==receipt['init']['sha256']
            and objects.identity(initramfs)=={key:receipt['initramfs'][key] for key in ('bytes','sha256')}
            and tool_identity(generator)==receipt['initramfsGenerator'],
                'constructor-vm-image-drift')
        require(all(objects.identity(firmware/name)==bound for name,bound in receipt['firmware'].items()),
                'constructor-vm-firmware-drift')
        receipt['status'] = 'passed'
        paths.write_new(output/'qualification.json',(json.dumps(receipt,indent=2)+'\n').encode())
        return receipt
    except BaseException:
        failed = True
        paths.write_new(output/'FAILED.json',
            (json.dumps({**receipt,'status':'failed','stage':stage},indent=2)+'\n').encode())
        raise
    finally:
        try:
            paths.write_new(output/'commands.json',(json.dumps(commands.records,indent=2)+'\n').encode())
        except BaseException:
            if not failed:
                raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    run(args.archive.resolve(strict=True),args.output)
