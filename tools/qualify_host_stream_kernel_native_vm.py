"""First actual Rust native constructor / qualified kernel join; no quota refund."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts
from tools import host_stream_kernel_native_vm as native
from tools import host_stream_kernel_native_vm_inputs as inputs
from tools import host_stream_kernel_vm_image as image
from tools.build_observation import build_environment
from tools.qualify_go_network_runtime import source_inputs as original_inputs
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

BRANCH = 'feat/kernel-native-constructor-vm-20261024'
WORKFLOW = '.github/workflows/stream-native-factory-owner.yml'
TARGET = 'x86_64-unknown-linux-gnu'
MAX_REJECTED_NATIVE = 8 * 1024**2  # Forensic retention only, never an image allowance.
FLAGS = ('-Ctarget-feature=+crt-static','-Crelocation-model=static','-Clink-arg=-no-pie')
RECIPE = (WORKFLOW, native.SUPERVISOR, native.ORIGINAL, inputs.PUBLIC,
    'tools/qualify_host_stream_kernel_native_vm.py','tools/host_stream_kernel_native_vm.py',
    'tools/host_stream_kernel_native_vm_inputs.py','tools/host_stream_kernel_vm_image.py',
    'tools/diagnose_host_stream_kernel_vm.py')


def source_inputs(root):
    result = original_inputs(root)
    for name in RECIPE:
        raw = read_file(root/name,4*1024**2)
        result[name] = {'digest':'sha256:'+native.identity(raw)['sha256'],'size':len(raw)}
    return dict(sorted(result.items()))


def cargo_product(raw, root, target):
    native.require(type(raw) is bytes and 0 < len(raw) <= 4*1024**2, 'cargo-inventory-bound')
    found, finished = [], False
    for line in raw.splitlines():
        native.require(len(line) <= 1024**2 and not finished, 'cargo-record-after-finish')
        record = json.loads(line)
        if record.get('reason') == 'build-finished':
            native.require(record.get('success') is True, 'cargo-finish-success')
            finished = True
        elif record.get('reason') == 'compiler-artifact' and record['target']['name'] == 'kernel_constructor_vm':
            native.require(Path(record['manifest_path']).resolve() == root/'crates/latent-streams/Cargo.toml'
                and record['target']['kind'] == ['example']
                and Path(record['target']['src_path']).resolve() == root/native.EXAMPLE
                and record['profile']['test'] is False and record['profile']['opt_level'] == 'z'
                and record['profile']['debug_assertions'] is False
                and 'development-outbound' in record['features']
                and set(record['features']) <= {'default','development-outbound'}, 'cargo-exact-owner')
            expected = target/TARGET/'release/examples/kernel_constructor_vm'
            native.require(record.get('executable') is not None
                and Path(record['executable']).resolve() == expected, 'cargo-owned-product')
            found.append(expected)
    native.require(finished and len(found) == 1, 'one-successful-native-example')
    return found[0]


def qualify(output, revision):
    native.require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME') == BRANCH
        and os.environ.get('GITHUB_EVENT_NAME') == 'push', 'one-hosted-owned-push')
    environment = build_environment(output)
    artifacts.require_source(ROOT,revision,environment)
    native.require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'outside-checkout-output')
    output = fresh(output)
    before = source_inputs(ROOT)
    write_json(output/'native-source-inputs.json',before)
    # Preserve argv[0] for rustup's rustc/cargo launchers; resolving the link
    # before execution would invoke the toolchain manager instead. Hash the
    # regular targets separately and recheck both links and bytes after use.
    tools = {name:Path(shutil.which(name) or '').absolute() for name in ('gcc','rustc','cargo','qemu-system-x86_64')}
    native.require(all(path.is_file() for path in tools.values()), 'normal-host-tools-required')
    tool_targets = {name:path.resolve() for name,path in tools.items()}
    tool_pins = {name:native.identity(read_file(path,256*1024**2)) for name,path in tool_targets.items()}
    command_root = output/'commands'; command_root.mkdir()
    environment.update(CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',
        CARGO_TARGET_DIR=str(output/'native-target'),CARGO_ENCODED_RUSTFLAGS='\x1f'.join(FLAGS),
        CARGO_PROFILE_RELEASE_OPT_LEVEL='z',CARGO_PROFILE_RELEASE_LTO='fat',
        CARGO_PROFILE_RELEASE_CODEGEN_UNITS='1',CARGO_PROFILE_RELEASE_PANIC='abort',
        CARGO_PROFILE_RELEASE_STRIP='symbols')
    commands = Commands(ROOT,command_root,environment,deadline_seconds=1320,command_seconds=1200)
    receipt = {'schemaVersion':'lsf.native-constructor-kernel-join.v1','status':'in-progress',
        'sourceRevision':revision,'kernelRebuilt':False,'wholeNodeExecuted':False,
        'nativeQuotaReleased':False,'productionInstallation':False,'completeAllocationClosure':False,
        'hostTlsQualified':False,'wholeCostQualification':False,'freshVmBoots':0,
        'staticCompilerFlags':list(FLAGS),'sourceBefore':before,'observedTools':tool_pins,
        'observedToolPaths':{name:{'launcher':str(tools[name]),'regularTarget':str(path)}
            for name,path in tool_targets.items()},
        'hermetic':False,'compilerImplicitInputsAttested':False,
        'reproducibility':'not-checked'}
    stage = 'immutable-kernel-input'
    try:
        kernel,receipt['kernelOrigin'] = inputs.prepare(output/'kernel')
        stage = 'normal-static-native-example'
        compiler = commands.run('rust-compiler-version',tools['rustc'],'--version')
        native.require(compiler.startswith(b'rustc 1.97.1 '), 'pinned-normal-rust-compiler')
        receipt['nativeCompiler'] = compiler.decode().strip()
        commands.run('c-compiler-version',tools['gcc'],'--version')
        commands.run('emulator-version',tools['qemu-system-x86_64'],'--version')
        inventory = commands.run('build-native-constructor-example',tools['cargo'],'build','--locked',
            '-p','latent-streams','--example','kernel_constructor_vm','--features','development-outbound',
            '--release','--target',TARGET,'--message-format=json')
        executable = cargo_product(inventory,ROOT,output/'native-target')
        candidate = executable.lstat()
        regular = stat.S_ISREG(candidate.st_mode)
        receipt['nativeCandidate'] = {'bytes':candidate.st_size,'mode':candidate.st_mode,
            'fileType':stat.S_IFMT(candidate.st_mode),'regularFile':regular,
            'symlink':stat.S_ISLNK(candidate.st_mode),'maximumAdmittedBytes':native.MAX_NATIVE_INIT}
        if regular and native.MAX_NATIVE_INIT < candidate.st_size <= MAX_REJECTED_NATIVE:
            rejected = read_file(executable,MAX_REJECTED_NATIVE)
            forensic = output/'native-init.rejected.elf'
            forensic.write_bytes(rejected)
            forensic.chmod(0o600)
            receipt['rejectedNativeProduct'] = {**native.identity(rejected),
                'path':forensic.name,'maximumForensicBytes':MAX_REJECTED_NATIVE,
                'admitted':False,'executable':False,'executed':False,'includedInVm':False}
        child_raw = read_file(executable,native.MAX_NATIVE_INIT)
        receipt['nativeInit'] = native.native_elf(child_raw)
        native_init = output/'native-init';native_init.write_bytes(child_raw)
        stage = 'actual-supervisor-and-leaf-controls'
        supervisor_source = native.supervisor_source()
        supervisor,receipt['supervisor'] = image.build_init(commands,tools['gcc'],supervisor_source,output)
        controls = commands.run('actual-native-kmsg-controls',supervisor,'--native-kmsg-control')
        native.require(controls == native.COMPILED_CONTROLS, 'actual-compiled-parser-cases')
        receipt['compiledParserControls'] = {'passed':12,'failed':0,**native.identity(controls)}
        supervisor_raw = read_file(supervisor,image.MAX_INIT)
        receipt['executablePartition'] = native.executable_partition(supervisor_raw,child_raw)
        stage = 'fixed-userspace-image'
        cpio_raw = native.native_initramfs(read_file(kernel/'constructor-initramfs.cpio',image.MAX_INITRAMFS),
            read_file(kernel/'constructor-init',image.MAX_INIT),supervisor_raw,child_raw)
        cpio = output/'native-constructor-initramfs.cpio';cpio.write_bytes(cpio_raw)
        receipt['initramfs'] = native.identity(cpio_raw)
        stage = 'one-isolated-native-kernel-join'
        previous_seconds,previous_deadline = commands.command_seconds,commands.deadline
        commands.command_seconds = min(previous_seconds,image.VM_SECONDS)
        commands.deadline = min(previous_deadline,time.monotonic()+image.VM_SECONDS)
        try:
            serial = commands.run('one-real-native-constructor-vm',
                *image.boot_argv(tools['qemu-system-x86_64'],kernel/'constructor-bzImage',cpio,kernel/'firmware'))
            native.require(time.monotonic() < commands.deadline, 'vm-expiry-never-success')
        finally:
            commands.command_seconds,commands.deadline = previous_seconds,previous_deadline
        receipt['observations'] = native.serial_observation(serial)
        receipt['freshVmBoots'] = 1
        stage = 'final-exact-material-recheck'
        native.require(source_inputs(ROOT) == before, 'native-source-mutated')
        native.require(read_file(native_init,native.MAX_NATIVE_INIT) == child_raw
            and read_file(cpio,image.MAX_INITRAMFS) == cpio_raw
            and read_file(output/'constructor-init.c',64*1024) == supervisor_source,
            'executed-userspace-image-mutated')
        # Recheck the selected immutable bytes after all compiler/VM children.
        original = inputs.public_receipt()
        native.require(image.kernel_image(read_file(kernel/'constructor-bzImage',image.MAX_KERNEL)) ==
            original['images']['kernel'], 'executed-kernel-mutated')
        for name,bound in original['firmware'].items():
            native.require(native.identity(read_file(kernel/'firmware'/name,1024**2)) == bound,
                'executed-firmware-mutated')
        native.require({name:path.resolve() for name,path in tools.items()} == tool_targets
            and {name:native.identity(read_file(path,256*1024**2)) for name,path in tool_targets.items()}
            == tool_pins, 'observed-tools-mutated')
        native.require(time.monotonic() < commands.deadline,'programme-expiry-never-success')
        artifacts.require_source(ROOT,revision,environment)
        receipt.update(status='passed',sourceAfter=before,sourceUnchanged=True,
            actualNativeConstructorReady=True,actualKernelRootReturn=True,
            originalNodeCapacityQuarantined=True,vm={'cpus':image.VM_CPUS,
                'memoryMiB':image.VM_MEMORY_MIB,'seconds':image.VM_SECONDS,
                'externalNetwork':False,'hostDrives':False,'hostInstallation':False,
                'watchdogExpiryIsSuccess':False})
        write_json(output/'receipt.json',receipt)
        return receipt
    except BaseException:
        write_json(output/'FAILED.json',{**receipt,'status':'failed','stage':stage})
        raise
    finally:
        write_json(output/'commands.json',commands.records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-commit',required=True)
    arguments = parser.parse_args()
    qualify(arguments.output.resolve(),arguments.source_commit)
