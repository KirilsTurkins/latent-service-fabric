"""One fresh kernel and authenticated native observation; all native quota held."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import qualify_host_stream_kernel_native_vm as original
from tools import host_stream_kernel_return_vm as observer
from tools import host_stream_kernel_return_build as kernel_build
from tools import host_stream_kernel_return_source as source
from tools import host_stream_kernel_native_vm as native
from tools import host_stream_kernel_vm_image as image
from tools import ci_rust_artifacts as artifacts
from tools import ci_suite_inventory as registry
from tools.build_observation import build_environment
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

BRANCH = 'feat/kernel-native-return-vm-20261024'
WORKFLOW = '.github/workflows/stream-kernel-return-vm.yml'
LEAF_CASE = 'ffi::tests::fixed_descriptor_boundary_refuses_foreign_and_preserves_actual_ownership'
RECIPE = (WORKFLOW, observer.EXAMPLE, 'tools/host_stream_kernel_return_vm.py',
    'tools/host_stream_kernel_return_build.py','tools/host_stream_kernel_return_source.py',
    'tools/qualify_host_stream_kernel_return_vm.py','tools/host_stream_kernel_retirement_observation.py',
    'tools/tests/fixtures/host_stream_kernel_retirement_observation.json',
    'tools/tests/fixtures/host_stream_kernel_return_vfs.json',
    'tools/tests/test_kernel_return_observation_vm.py',
    'research/standard-outbound/linux-6.12-lineage/factory-retirement-observation.c',
    'crates/latent-stream-factory-native/Cargo.toml','crates/latent-stream-factory-native/src/lib.rs',
    'tools/ci/suites.d/kernel-return-observation-vm.json')


def source_inputs():
    result = original.source_inputs(ROOT)
    for name in RECIPE:
        raw = read_file(ROOT/name,4*1024**2)
        result[name] = {'digest':'sha256:'+native.identity(raw)['sha256'],'size':len(raw)}
    return dict(sorted(result.items()))


def leaf_control(commands, cargo, output):
    contract, = [row for row in registry.load()['suites']
        if row['package'] == 'latent-stream-factory-native' and row['kind'] == 'lib']
    native.require(contract['expectedCases'] == [LEAF_CASE] and not contract['expectedIgnored']
        and contract['minimumCases'] == 1,'registered-owned-descriptor-leaf')
    commands.run('leaf-cargo',cargo,'test','--locked','--all-features',
        '-p','latent-stream-factory-native','--lib','--no-run','--message-format=json')
    inventory = commands.output/'logs'/f'{len(commands.records)-1:02d}-leaf-cargo.stdout.txt'
    suite = artifacts.Suite('crates/latent-stream-factory-native/Cargo.toml',
        'latent_stream_factory_native','src/lib.rs','ffi::tests::',frozenset({LEAF_CASE}),False)
    target = output/'host-control-target'
    executable = artifacts.read_inventory(inventory,ROOT,suite,target=target)
    env,seconds = commands.environment,commands.command_seconds
    commands.environment = artifacts.cargo_environment(ROOT,executable,env,target=target)
    try:
        commands.command_seconds = min(seconds,30)
        listed = commands.run('leaf-list',executable.executable,'--list')
        ignored = commands.run('leaf-ignored',executable.executable,'--ignored','--list')
        native.require(re.findall(rb'^([a-zA-Z0-9_:]+): test$',listed,re.M) == [LEAF_CASE.encode()]
            and not re.search(rb': test$',ignored,re.M),'exact-unignored-owned-descriptor-leaf')
        commands.command_seconds = min(seconds,120)
        raw = commands.run('leaf-tests',executable.executable,'--show-output','--test-threads=1')
        native.require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$',raw,re.M) == [LEAF_CASE.encode()]
            and re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; '
                rb'(\d+) measured; (\d+) filtered out;',raw,re.M) == [(b'1',b'0',b'0',b'0',b'0')],
            'owned-descriptor-leaf-actually-executed')
        return {'executed':[LEAF_CASE],'ignored':[],'stdout':native.identity(raw),
            'executableBytes':executable.executable.stat().st_size,
            'executableSha256':original.native_controls.provider.digest_file(executable.executable,1024**3),
            'actualKernelMint':False}
    finally:
        commands.environment,commands.command_seconds = env,seconds


def cargo_product(raw, root, target):
    # Preserve the original strict Cargo parser's complete contract; only this
    # distinct source target/product is admitted, without rewriting raw records.
    native.require(type(raw) is bytes and 0 < len(raw) <= 4*1024**2,'return-cargo-inventory-bound')
    found,finished = [],False
    for line in raw.splitlines():
        native.require(len(line) <= 1024**2 and not finished,'return-cargo-after-finish')
        row = json.loads(line)
        if row.get('reason') == 'build-finished':
            native.require(row.get('success') is True,'return-cargo-success')
            finished = True
        elif row.get('reason') == 'compiler-artifact' and row['target']['name'] == observer.TARGET_NAME:
            native.require(Path(row['manifest_path']).resolve() == root/'crates/latent-streams/Cargo.toml'
                and row['target']['kind'] == ['example']
                and Path(row['target']['src_path']).resolve() == root/observer.EXAMPLE
                and row['profile']['test'] is False and row['profile']['opt_level'] == 'z'
                and row['profile']['debug_assertions'] is False
                and 'development-outbound' in row['features']
                and set(row['features']) <= {'default','development-outbound'},'return-cargo-exact-owner')
            expected = target/original.TARGET/'release/examples'/observer.TARGET_NAME
            native.require(row.get('executable') is not None and Path(row['executable']).resolve() == expected,
                'return-cargo-owned-product')
            found.append(expected)
    native.require(finished and len(found) == 1,'one-return-example')
    return found[0]


def qualify(output, revision):
    native.require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == BRANCH and os.environ.get('GITHUB_EVENT_NAME') == 'push',
        'one-fresh-return-hosted-push')
    environment = build_environment(output)
    artifacts.require_source(ROOT,revision,environment)
    native.require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'return-output-outside-checkout')
    output = fresh(output)
    before = source_inputs()
    write_json(output/'source-inputs.json',before)
    names = ('gcc','rustc','cargo','qemu-system-x86_64','make','tar','curl')
    tools = {name:Path(shutil.which(name) or '').absolute() for name in names}
    native.require(all(path.is_file() for path in tools.values()),'return-host-tools')
    targets = {name:path.resolve() for name,path in tools.items()}
    pins = {name:native.identity(read_file(path,256*1024**2)) for name,path in targets.items()}
    environment.update(CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',
        CARGO_TARGET_DIR=str(output/'host-control-target'),KBUILD_BUILD_USER='lsf-object-check',
        KBUILD_BUILD_HOST='isolated-ci',KBUILD_BUILD_TIMESTAMP='2026-10-23 00:00:00 UTC',KCONFIG_NOTIMESTAMP='1')
    log = output/'commands';log.mkdir()
    commands = Commands(ROOT,log,environment,deadline_seconds=2400,command_seconds=1200)
    receipt = {'schemaVersion':'lsf.kernel-native-return-observation.v1','status':'in-progress',
        'sourceRevision':revision,'sourceBefore':before,'observedTools':pins,
        'observedToolPaths':{name:{'launcher':str(tools[name]),'regularTarget':str(path)}
            for name,path in targets.items()},'nativeQuotaReleased':False,'productionInstallation':False,
        'completeAllocationClosure':False,'fullVfsLsmCostsQualified':False,'wholeNodeExecuted':False,
        'hostTlsQualified':False,'freshVmAttempts':0,'validatedVmBoots':0,'kernelLinked':False,
        'compilerImplicitInputsAttested':False,'hermetic':False,'reproducibility':'not-checked',
        'limits':{'overallSeconds':2400,'nativePhaseSeconds':1320,'kernelCommandSeconds':1800,
            'cargoCommandSeconds':1200,'vmSeconds':180,'vmCpus':2,'vmMemoryMiB':512,
            'pid1FileBytes':image.MAX_INIT,'nativeFileBytes':native.MAX_NATIVE_INIT,
            'aggregateLoadSpanBytes':image.MAX_INIT_LOAD,'cpioBytes':image.MAX_INITRAMFS}}
    try:
        receipt['stage'] = 'fail-fast-native-and-c'
        global_deadline = commands.deadline
        commands.deadline = min(global_deadline,time.monotonic()+1320)
        version = commands.run('rust-compiler-version',tools['rustc'],'--version')
        native.require(version.startswith(b'rustc 1.97.1 '),'return-normal-rust-compiler')
        receipt['nativeCompiler'] = version.decode().strip()
        commands.run('c-compiler-version',tools['gcc'],'--version')
        receipt['ownerControls'] = original.owner_controls(commands,tools['cargo'],output)
        receipt['leafControl'] = leaf_control(commands,tools['cargo'],output)
        # No Linux source download/link can precede all nineteen actual cases.
        environment.update(CARGO_TARGET_DIR=str(output/'native-target'),
            CARGO_ENCODED_RUSTFLAGS='\x1f'.join(original.FLAGS),CARGO_PROFILE_RELEASE_OPT_LEVEL='z',
            CARGO_PROFILE_RELEASE_LTO='fat',CARGO_PROFILE_RELEASE_CODEGEN_UNITS='1',
            CARGO_PROFILE_RELEASE_PANIC='abort',CARGO_PROFILE_RELEASE_STRIP='symbols')
        inventory = commands.run('build-return-observation-example',tools['cargo'],'build','--locked',
            '-p','latent-streams','--example',observer.TARGET_NAME,'--features','development-outbound',
            '--release','--target',original.TARGET,'--message-format=json')
        product = cargo_product(inventory,ROOT,output/'native-target')
        candidate = product.lstat()
        receipt['nativeCandidate'] = {'bytes':candidate.st_size,'mode':candidate.st_mode,
            'regularFile':stat.S_ISREG(candidate.st_mode),'maximumAdmittedBytes':native.MAX_NATIVE_INIT}
        if stat.S_ISREG(candidate.st_mode) and native.MAX_NATIVE_INIT < candidate.st_size <= original.MAX_REJECTED_NATIVE:
            rejected = read_file(product,original.MAX_REJECTED_NATIVE)
            forensic = output/'native-init.rejected.elf';forensic.write_bytes(rejected);forensic.chmod(0o600)
            receipt['rejectedNativeProduct'] = {**native.identity(rejected),'path':forensic.name,
                'admitted':False,'executable':False,'executed':False,'includedInVm':False}
        child = read_file(product,native.MAX_NATIVE_INIT)
        receipt['nativeInit'] = native.native_elf(child)
        native_init = output/'native-init';native_init.write_bytes(child)
        supervisor_source = native.supervisor_source()
        supervisor,receipt['supervisor'] = image.build_init(commands,tools['gcc'],supervisor_source,output)
        controls = commands.run('actual-native-kmsg-controls',supervisor,'--native-kmsg-control')
        native.require(controls == native.COMPILED_CONTROLS,'return-actual-twelve-c-controls')
        receipt['compiledParserControls'] = {'passed':12,'failed':0,**native.identity(controls)}
        pid1 = read_file(supervisor,image.MAX_INIT)
        receipt['executablePartition'] = native.executable_partition(pid1,child)
        native.require(time.monotonic() < commands.deadline,'return-native-phase-expired')
        commands.deadline = global_deadline  # Original absolute overall bound, never a new deadline.
        commands.command_seconds = 180
        receipt['stage'] = 'fresh-exact-linux-source'
        value = kernel_build.baseline.maintained.manifest()
        archive = output/'download-linux.tar.xz'
        commands.run('acquire-exact-linux-source',tools['curl'],'--fail','--location','--proto','=https',
            '--tlsv1.2','--max-time','180','--max-filesize',str(value['archive']['bytes']),
            value['archive']['url'],'--output',archive)
        kernel_output = output/'kernel';kernel_output.mkdir()
        kernel,generator,tree,derived,config = kernel_build.build(commands,tools,archive,kernel_output,receipt)
        commands.command_seconds = 1200
        base_cpio,_ = image.build_initramfs(commands,generator,supervisor,output)
        raw_cpio = native.native_initramfs(read_file(base_cpio,image.MAX_INITRAMFS),pid1,pid1,child)
        cpio = output/'native-return-initramfs.cpio';cpio.write_bytes(raw_cpio)
        receipt['initramfs'] = native.identity(raw_cpio)
        firmware = output/'firmware';firmware.mkdir()
        receipt['firmware'] = {}
        for name,path in {'bios-256k.bin':'/usr/share/seabios/bios-256k.bin',
                'linuxboot_dma.bin':'/usr/share/qemu/linuxboot_dma.bin',
                'kvmvapic.bin':'/usr/share/qemu/kvmvapic.bin'}.items():
            raw = read_file(Path(path),1024**2);(firmware/name).write_bytes(raw)
            receipt['firmware'][name] = native.identity(raw)
        native.require(sum(row['bytes'] for row in receipt['firmware'].values()) <= 1024**2,
            'return-original-firmware-bound')
        commands.run('emulator-version',tools['qemu-system-x86_64'],'--version')
        receipt['stage'] = 'one-fresh-authenticated-return-vm'
        commands.command_seconds = min(commands.command_seconds,image.VM_SECONDS)
        receipt['freshVmAttempts'] = 1
        serial = commands.run('one-real-native-return-vm',
            *image.boot_argv(tools['qemu-system-x86_64'],kernel,cpio,firmware))
        native.require(time.monotonic() < commands.deadline,'return-vm-expired')
        receipt['observations'] = observer.serial_observation(serial)
        receipt['validatedVmBoots'] = 1
        receipt['stage'] = 'final-source-image-and-tools-recheck'
        native.require(source_inputs() == before,'return-source-mutated')
        native.require({name:path.resolve() for name,path in tools.items()} == targets
            and {name:native.identity(read_file(path,256*1024**2)) for name,path in targets.items()} == pins,
            'return-tools-mutated')
        native.require(read_file(native_init,native.MAX_NATIVE_INIT) == child
            and read_file(cpio,image.MAX_INITRAMFS) == raw_cpio
            and read_file(output/'constructor-init.c',64*1024) == supervisor_source,
            'return-userspace-mutated')
        native.require(image.kernel_image(read_file(kernel,image.MAX_KERNEL)) == receipt['kernelImage']
            and read_file(kernel_output/'objects/.config',256*1024) == config
            and kernel_build.objects.identity(generator) == receipt['initramfsGenerator']
            and all(read_file(tree/name,4*1024**2) == raw for name,raw in derived.items()),
            'return-compiled-kernel-mutated')
        audited = {name:read_file(tree/name,4*1024**2) for name in source.fixture()['originals']}
        native.require(source.ordinary_bodies(audited) == receipt['outsideBankLifetimeSource']['compiledOrdinaryBodies'],
            'return-vfs-compiled-body-mutated')
        native.require(all(name in derived or native.identity(raw) == source.fixture()['originals'][name]
            for name,raw in audited.items()),'return-vfs-unmodified-whole-file-mutated')
        native.require(kernel_build.programme.local_freeze() == receipt['localSourceFreeze']
            and kernel_build.historical.recipe_inputs() == receipt['recipeInputs']
            and all(kernel_build.objects.identity(ROOT/name) == bound
                for name,bound in receipt['compiledKernelProducerMaterials'].items()),
            'return-complete-kernel-materials-mutated')
        native.require(kernel_build.tool_identity(kernel_output/'objects/vmlinux',512*1024**2)
            == receipt['linkedVmlinux']
            and kernel_build.objects.identity(kernel_output/'objects/include/generated/autoconf.h')
                == receipt['generatedAutoconf']
            and kernel_build.objects.identity(kernel_output/'source.tar.xz') == receipt['archive'],
            'return-original-compiler-products-mutated')
        native.require(all(native.identity(read_file(firmware/name,1024**2)) == bound
            for name,bound in receipt['firmware'].items()),'return-firmware-mutated')
        native.require(time.monotonic() < commands.deadline,'return-overall-expired')
        artifacts.require_source(ROOT,revision,environment)
        receipt.update(status='passed',sourceAfter=before,sourceUnchanged=True,
            actualNativeKernelRootReturned=True,actualKernelPhysicalReturn=True,
            originalNodeCapacityQuarantined=True)
        write_json(output/'receipt.json',receipt)
        return receipt
    except BaseException:
        write_json(output/'FAILED.json',{**receipt,'status':'failed'})
        raise
    finally:
        write_json(output/'commands.json',commands.records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-commit',required=True)
    args = parser.parse_args()
    qualify(args.output.resolve(),args.source_commit)
