"""One fixed-bank consumer; reuse only the qualified observation-ABI kernel."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import qualify_host_stream_kernel_native_vm as original
from tools import qualify_host_stream_kernel_return_vm as previous
from tools import host_stream_kernel_bank_inputs as inputs
from tools import host_stream_kernel_bank_vm as observer
from tools import host_stream_kernel_native_vm as native
from tools import host_stream_kernel_vm_image as image
from tools import ci_rust_artifacts as artifacts
from tools import ci_suite_inventory as registry
from tools.build_observation import build_environment
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT,fresh,read_file,write_json

BRANCH = 'feat/kernel-bank-reclamation-20261025'
WORKFLOW = '.github/workflows/stream-kernel-bank-vm.yml'
BANK_CASE = 'broker::pools::tests::protocol::kernel_backing_uses_existing_fixed_metadata_ceiling'
RECIPE = (WORKFLOW,observer.EXAMPLE,inputs.PUBLIC,'tools/host_stream_kernel_bank_inputs.py',
    'tools/host_stream_kernel_bank_vm.py','tools/qualify_host_stream_kernel_bank_vm.py',
    'tools/tests/test_kernel_bank_reclamation_vm.py','tools/ci/suites.d/kernel-bank-reclamation-vm.json')


def source_inputs():
    result = original.source_inputs(ROOT)
    for name in RECIPE:
        raw = read_file(ROOT/name,4*1024**2)
        result[name] = {'digest':'sha256:'+native.identity(raw)['sha256'],'size':len(raw)}
    return dict(sorted(result.items()))


def partition_control(commands,output):
    """Use the ALREADY built current core test product; no third Cargo build."""
    index, = [i for i,row in enumerate(commands.records) if row['stage'] == 'close-result-cargo']
    inventory = commands.output/'logs'/f'{index:02}-close-result-cargo.stdout.txt'
    contract, = [row for row in registry.load()['suites']
        if row['package'] == 'latent-capabilities' and row['kind'] == 'lib']
    native.require(BANK_CASE in contract['expectedCases'] and BANK_CASE not in contract['expectedIgnored'],
        'bank-registered-original-protocol-control')
    suite = artifacts.Suite('crates/latent-capabilities/Cargo.toml','latent_capabilities',
        'src/lib.rs',BANK_CASE,frozenset({BANK_CASE}),False)
    target = output/'host-control-target'
    executable = artifacts.read_inventory(inventory,ROOT,suite,target=target)
    env,seconds = commands.environment,commands.command_seconds
    commands.environment = artifacts.cargo_environment(ROOT,executable,env,target=target)
    try:
        commands.command_seconds = min(seconds,30)
        listed = commands.run('bank-partition-list',executable.executable,BANK_CASE,'--exact','--list')
        ignored = commands.run('bank-partition-ignored',executable.executable,BANK_CASE,'--exact','--ignored','--list')
        native.require(re.findall(rb'^([A-Za-z0-9_:]+): test$',listed,re.M) == [BANK_CASE.encode()]
            and not re.search(rb': test$',ignored,re.M),'bank-exact-unignored-control')
        commands.command_seconds = min(seconds,120)
        raw = commands.run('bank-partition-test',executable.executable,BANK_CASE,
            '--exact','--show-output','--test-threads=1')
        expected = tuple(str(n).encode() for n in (1,0,0,0,contract['minimumCases']-1))
        native.require(re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$',raw,re.M) == [BANK_CASE.encode()]
            and re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; '
                rb'(\d+) measured; (\d+) filtered out;',raw,re.M) == [expected],
            'bank-original-quota-partition-executed')
        return {'executed':[BANK_CASE],'ignored':[],'stdout':native.identity(raw),
            'sameCoreExecutableReused':True,'actualKernelOrProofConstructed':False}
    finally:
        commands.environment,commands.command_seconds = env,seconds


def cargo_product(raw,root,target):
    native.require(type(raw) is bytes and 0 < len(raw) <= 4*1024**2,'bank-cargo-bound')
    found,finished = [],False
    for line in raw.splitlines():
        native.require(len(line) <= 1024**2 and not finished,'bank-cargo-record-order')
        row = json.loads(line)
        if row.get('reason') == 'build-finished':
            native.require(row.get('success') is True,'bank-cargo-success');finished = True
        elif row.get('reason') == 'compiler-artifact' and row['target']['name'] == observer.TARGET_NAME:
            expected = target/original.TARGET/'release/examples'/observer.TARGET_NAME
            native.require(Path(row['manifest_path']).resolve() == root/'crates/latent-streams/Cargo.toml'
                and row['target']['kind'] == ['example']
                and Path(row['target']['src_path']).resolve() == root/observer.EXAMPLE
                and row['profile']['test'] is False and row['profile']['opt_level'] == 'z'
                and row['profile']['debug_assertions'] is False
                and 'development-outbound' in row['features']
                and set(row['features']) <= {'default','development-outbound'}
                and row.get('executable') is not None and Path(row['executable']).resolve() == expected,
                'bank-owned-static-product')
            found.append(expected)
    native.require(finished and len(found) == 1,'bank-single-normal-product')
    return found[0]


def qualify(output,revision):
    native.require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push','bank-one-hosted-push')
    environment = build_environment(output)
    artifacts.require_source(ROOT,revision,environment)
    native.require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'bank-output-outside-checkout')
    output = fresh(output);before = source_inputs();write_json(output/'source-inputs.json',before)
    tools = {name:Path(shutil.which(name) or '').absolute() for name in ('rustc','cargo','qemu-system-x86_64')}
    native.require(all(path.is_file() for path in tools.values()),'bank-normal-host-tools')
    targets = {name:path.resolve() for name,path in tools.items()}
    pins = {name:native.identity(read_file(path,256*1024**2)) for name,path in targets.items()}
    environment.update(CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',CARGO_TARGET_DIR=str(output/'host-control-target'))
    log = output/'commands';log.mkdir()
    commands = Commands(ROOT,log,environment,deadline_seconds=1320,command_seconds=1200)
    receipt = {'schemaVersion':'lsf.kernel-bank-reclamation.v1','status':'in-progress','sourceRevision':revision,
        'sourceBefore':before,'kernelRebuilt':False,'fullNativeQuotaReleased':False,
        'connectionQuotaReleased':False,'productionInstallation':False,'completeAllocationClosure':False,
        'fullVfsLsmCostsQualified':False,'hostTlsQualified':False,'wholeNodeExecuted':False,
        'freshVmAttempts':0,'validatedVmBoots':0,'bankReservationReturnedBytes':0,
        'hermetic':False,'compilerImplicitInputsAttested':False,'reproducibility':'not-checked',
        'limits':{'overallSeconds':1320,'cargoCommandSeconds':1200,'vmSeconds':180,
            'vmCpus':2,'vmMemoryMiB':512,'pid1FileBytes':image.MAX_INIT,
            'nativeFileBytes':native.MAX_NATIVE_INIT,'aggregateLoadSpanBytes':image.MAX_INIT_LOAD,
            'cpioBytes':image.MAX_INITRAMFS},'observedTools':pins}
    try:
        receipt['stage'] = 'source-matched-native-controls'
        compiler = commands.run('rust-compiler-version',tools['rustc'],'--version')
        native.require(compiler.startswith(b'rustc 1.97.1 '),'bank-normal-rust-compiler')
        receipt['nativeCompiler'] = compiler.decode().strip()
        commands.run('emulator-version',tools['qemu-system-x86_64'],'--version')
        receipt['ownerControls'] = original.owner_controls(commands,tools['cargo'],output)
        receipt['partitionControl'] = partition_control(commands,output)
        receipt['leafControl'] = previous.leaf_control(commands,tools['cargo'],output)
        receipt['stage'] = 'immutable-qualified-observation-image'
        kernel,receipt['kernelOrigin'] = inputs.prepare(output/'kernel',commands.deadline)
        receipt['stage'] = 'one-new-normal-static-native-child'
        environment.update(CARGO_TARGET_DIR=str(output/'native-target'),
            CARGO_ENCODED_RUSTFLAGS='\x1f'.join(original.FLAGS),CARGO_PROFILE_RELEASE_OPT_LEVEL='z',
            CARGO_PROFILE_RELEASE_LTO='fat',CARGO_PROFILE_RELEASE_CODEGEN_UNITS='1',
            CARGO_PROFILE_RELEASE_PANIC='abort',CARGO_PROFILE_RELEASE_STRIP='symbols')
        inventory = commands.run('build-bank-consumer-example',tools['cargo'],'build','--locked',
            '-p','latent-streams','--example',observer.TARGET_NAME,'--features','development-outbound',
            '--release','--target',original.TARGET,'--message-format=json')
        product = cargo_product(inventory,ROOT,output/'native-target')
        candidate = product.lstat()
        native.require(stat.S_ISREG(candidate.st_mode),'bank-regular-native-product')
        child = read_file(product,native.MAX_NATIVE_INIT);receipt['nativeInit'] = native.native_elf(child)
        (output/'native-init').write_bytes(child)
        pid1 = read_file(kernel/'constructor-init',image.MAX_INIT)
        receipt['supervisor'] = receipt['kernelOrigin']['originalSupervisor']
        receipt['executablePartition'] = native.executable_partition(pid1,child)
        base = read_file(kernel/'constructor-initramfs.cpio',image.MAX_INITRAMFS)
        cpio_raw = native.native_initramfs(base,pid1,pid1,child)
        cpio = output/'bank-consumer-initramfs.cpio';cpio.write_bytes(cpio_raw)
        receipt['initramfs'] = native.identity(cpio_raw)
        receipt['stage'] = 'one-bank-consumption-vm'
        commands.command_seconds = min(commands.command_seconds,image.VM_SECONDS)
        receipt['freshVmAttempts'] = 1
        serial = commands.run('one-bank-consumption-vm',*image.boot_argv(
            tools['qemu-system-x86_64'],kernel/'kernel/constructor-bzImage',cpio,kernel/'firmware'))
        receipt['observations'] = observer.serial_observation(serial)
        receipt['validatedVmBoots'] = 1
        receipt['stage'] = 'final-immutable-inputs'
        native.require(time.monotonic() < commands.deadline and source_inputs() == before,'bank-source-or-deadline')
        native.require({name:path.resolve() for name,path in tools.items()} == targets
            and {name:native.identity(read_file(path,256*1024**2)) for name,path in targets.items()} == pins,
            'bank-tools-changed')
        native.require(native.identity(read_file(kernel/'qualified-observation-image.zip',inputs.MAX_ZIP))
            == {'bytes':inputs.ZIP_BYTES,'sha256':inputs.ZIP_SHA},'bank-original-archive-changed')
        for name,bound in receipt['kernelOrigin']['selectedBootMaterials'].items():
            native.require(native.identity(read_file(kernel/name,inputs.MAX_ZIP)) == bound,
                'bank-selected-boot-material-changed')
        for name,bound in receipt['kernelOrigin']['kernelSourceMaterials'].items():
            native.require(native.identity(read_file(ROOT/name,4*1024**2)) == bound,'bank-kernel-source-changed')
        native.require(read_file(output/'native-init',native.MAX_NATIVE_INIT) == child
            and read_file(cpio,image.MAX_INITRAMFS) == cpio_raw
            and read_file(kernel/'constructor-init',image.MAX_INIT) == pid1,'bank-executables-changed')
        artifacts.require_source(ROOT,revision,environment)
        receipt.update(status='passed',sourceAfter=before,sourceUnchanged=True,
            bankReservationReturnedBytes=observer.BANK_BYTES,
            bootstrapOverheadReservationRetainedBytes=observer.BANK_BYTES,
            originalObserverReservationRetained=True,originalConnectionQuarantined=True)
        write_json(output/'receipt.json',receipt)
    except BaseException:
        receipt['status'] = 'failed';write_json(output/'FAILED.json',receipt);raise
    finally:
        write_json(output/'commands.json',commands.records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-commit',required=True)
    args = parser.parse_args()
    qualify(args.output.resolve(),args.source_commit)
