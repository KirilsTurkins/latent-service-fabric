"""First actual Rust native constructor / qualified kernel join; no quota refund."""
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
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts
from tools import ci_suite_inventory as registry
from tools import host_stream_kernel_native_vm as native
from tools import host_stream_kernel_native_vm_inputs as inputs
from tools import host_stream_kernel_vm_image as image
from tools import qualify_host_stream_native as native_controls
from tools.build_observation import build_environment
from tools.qualify_go_network_runtime import source_inputs as original_inputs
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

BRANCHES = ('feat/kernel-native-constructor-vm-20261024','feat/kernel-native-close-20261024')
WORKFLOW = '.github/workflows/stream-native-factory-owner.yml'
TARGET = 'x86_64-unknown-linux-gnu'
MAX_REJECTED_NATIVE = 8 * 1024**2  # Forensic retention only, never an image allowance.
FLAGS = ('-Ctarget-feature=+crt-static','-Crelocation-model=static','-Clink-arg=-no-pie')
RECIPE = (WORKFLOW, native.SUPERVISOR, native.ORIGINAL, inputs.PUBLIC,
    'tools/qualify_host_stream_kernel_native_vm.py','tools/host_stream_kernel_native_vm.py',
    'tools/host_stream_kernel_native_vm_inputs.py','tools/host_stream_kernel_vm_image.py',
    'tools/diagnose_host_stream_kernel_vm.py','tools/ci/suites.json',
    'tools/ci/suites.d/outbound-streams.json')

CORE_CLOSE_PREFIX = 'broker::pools::tests::close_observation::'
CORE_CLOSE_CASES = frozenset(CORE_CLOSE_PREFIX+name for name in (
    'buffered_and_delivered_close_receipt_keeps_original_cleanup_charge',
    'abandoned_close_waiter_does_not_release_running_or_quarantined_owner',
    'close_worker_panic_never_publishes_accepted_receipt_or_refunds_connection',
    'held_close_receipt_bounds_new_admission_and_returns_unchanged_owner',
    'published_receipt_drop_cannot_release_live_sender_worker_tail',
))


def owner_controls(commands, cargo, output):
    """Normal source-matched host controls; never execute native-init on host."""
    result = {}
    contracts = registry.load()['suites']
    target = output/'host-control-target'
    for label,package,target_name,prefix,cases in (
            ('native-owner','latent-streams','latent_streams',native_controls.PREFIX,native_controls.CASES),
            ('close-result','latent-capabilities','latent_capabilities',CORE_CLOSE_PREFIX,CORE_CLOSE_CASES)):
        contract, = [row for row in contracts if row['package'] == package and row['kind'] == 'lib']
        native.require({name for name in contract['expectedCases'] if name.startswith(prefix)} == cases
            and not set(contract['expectedIgnored']) & cases, 'registered-owner-controls')
        stage = label+'-cargo'
        commands.run(stage,cargo,'test','--locked','--all-features','-p',package,'--lib',
            '--no-run','--message-format=json')
        inventory = commands.output/'logs'/f'{len(commands.records)-1:02d}-{stage}.stdout.txt'
        suite = artifacts.Suite(f'crates/{package}/Cargo.toml',target_name,'src/lib.rs',prefix,cases,False)
        executable = artifacts.read_inventory(inventory,ROOT,suite,target=target)
        previous_environment, previous_seconds = commands.environment,commands.command_seconds
        commands.environment = artifacts.cargo_environment(ROOT,executable,previous_environment,target=target)
        try:
            commands.command_seconds = min(previous_seconds,30)
            listed = commands.run(label+'-list',executable.executable,prefix,'--list')
            registered = [name.decode() for name in re.findall(rb'^([a-zA-Z0-9_:]+): test$',listed,re.M)]
            ignored = commands.run(label+'-ignored',executable.executable,prefix,'--ignored','--list')
            native.require(len(registered) == len(cases) and set(registered) == cases
                and not re.search(rb': test$',ignored,re.M), 'exact-unignored-owner-controls')
            commands.command_seconds = min(previous_seconds,120)
            raw = commands.run(label+'-tests',executable.executable,prefix,'--show-output','--test-threads=1')
            actual = [name.decode() for name in re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$',raw,re.M)]
            totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; '
                rb'(\d+) measured; (\d+) filtered out;',raw,re.M)
            expected = tuple(str(number).encode() for number in
                (len(cases),0,0,0,contract['minimumCases']-len(cases)))
            native.require(len(actual) == len(cases) and set(actual) == cases and totals == [expected],
                'all-fixed-owner-controls-executed')
            if label == 'native-owner':native_controls.outcomes(raw)
            result[label] = {'registered':sorted(registered),'executed':sorted(actual),'ignored':[],
                'stdout':native.identity(raw),'executableSha256':native_controls.provider.digest_file(
                    executable.executable,1024*1024**2),
                'executableBytes':executable.executable.stat().st_size,
                'customKernelOrNativeInitExecuted':False}
        finally:
            commands.environment,commands.command_seconds = previous_environment,previous_seconds
    return result


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
        and os.environ.get('GITHUB_REF_NAME') in BRANCHES
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
        CARGO_TARGET_DIR=str(output/'host-control-target'))
    commands = Commands(ROOT,command_root,environment,deadline_seconds=1320,command_seconds=1200)
    receipt = {'schemaVersion':'lsf.native-constructor-close-request.v1','status':'in-progress',
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
        stage = 'normal-host-owner-controls'
        receipt['ownerControls'] = owner_controls(commands,tools['cargo'],output)
        stage = 'normal-static-native-example'
        environment.update(CARGO_TARGET_DIR=str(output/'native-target'),
            CARGO_ENCODED_RUSTFLAGS='\x1f'.join(FLAGS),
            CARGO_PROFILE_RELEASE_OPT_LEVEL='z',CARGO_PROFILE_RELEASE_LTO='fat',
            CARGO_PROFILE_RELEASE_CODEGEN_UNITS='1',CARGO_PROFILE_RELEASE_PANIC='abort',
            CARGO_PROFILE_RELEASE_STRIP='symbols')
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
            actualNativeConstructorReady=True,actualNativeCloseRequestAccepted=True,
            originalReceiptChargeObserved=True,actualKernelRootReturn=True,
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


NODE_RECIPE = (*RECIPE,'tools/qualify_host_stream_kernel_stream_objects.py',
    'tools/qualify_host_stream_kernel_objects.py','tools/requirements.lock')


def node_source_inputs(root,listed):
    # Same original native-owner selection, with an owned inventory command
    # instead of the legacy helper's unrecorded subprocess.
    from tools import qualify_go_network_runtime as source_owner
    native.require(type(listed) is bytes and len(listed) <= 4*1024**2,'node-path-inventory-bound')
    names = set(source_owner.BUILD_RECIPE) | {'Cargo.toml','Cargo.lock','rust-toolchain.toml',
        'tools/qualify_go_network_runtime.py','tools/ci/suites.d/go-network-runtime.json',*NODE_RECIPE}
    for name in listed.decode('utf8','strict').split('\0'):
        if name.startswith(('apps/','crates/','wit/','schemas/','examples/','sdk/go-guest/')) or (
                name.startswith('tools/') and name.endswith('.py')):
            names.add(name)
    native.require(100 <= len(names) <= 32768,'node-original-native-source-count')
    result,total = {},0
    for name in sorted(names):
        raw = read_file(root/name,16*1024**2); total += len(raw)
        native.require(total <= 128*1024**2,'node-original-native-source-bytes')
        result[name] = {'digest':'sha256:'+native.identity(raw)['sha256'],'size':len(raw)}
    return result


def node_kvm_access(run, receipt, tool_pins):
    """Ephemeral owning runner: inspect first, then grant only its UID if needed."""
    kvm = Path('/dev/kvm')
    def facts():
        value = {'uid':os.getuid(),'euid':os.geteuid(),'gid':os.getgid(),
            'egid':os.getegid(),'groups':sorted(os.getgroups())}
        try:
            entry = kvm.lstat()
        except OSError as error:
            return {**value,'exists':False,'errno':error.errno}
        return {**value,'exists':True,'symlink':stat.S_ISLNK(entry.st_mode),
            'characterDevice':stat.S_ISCHR(entry.st_mode),'mode':entry.st_mode,
            'device':entry.st_dev,'inode':entry.st_ino,'rdev':entry.st_rdev,
            'major':os.major(entry.st_rdev),'minor':os.minor(entry.st_rdev),
            'ownerUid':entry.st_uid,'ownerGid':entry.st_gid,
            'readWrite':os.access(kvm,os.R_OK|os.W_OK,effective_ids=True)}
    access = receipt['kvmAccess'] = {'before':facts(),'grantAttempted':False,
        'lifetime':'ephemeral-hosted-runner-only; ACL discarded with runner'}
    before = access['before']
    native.require(before['exists'],'node-KVM-device-missing-no-fallback')
    native.require(before['characterDevice'] and not before['symlink'],
        'node-KVM-device-type-no-fallback')
    for name in ('getfacl','setfacl'):
        tool = Path('/usr/bin')/name
        native.require(tool.is_file(),'node-KVM-ACL-tools-required')
        tool_pins[name] = {'path':str(tool),'target':str(tool.resolve()),
            **native.identity(read_file(tool.resolve(),256*1024**2))}
    def acl(label):
        raw = run(label,'/usr/bin/getfacl','--omit-header','--numeric',
            '--no-effective','--',kvm,seconds=15)
        native.require(len(raw) <= 4096,'node-KVM-ACL-document-bound')
        return [line for line in raw.decode('ascii').splitlines() if line]
    original = access['aclBefore'] = acl('node-KVM-ACL-before')
    if not before['readWrite']:
        # Only the simple native device ACL is eligible. An unknown extended
        # ACL is refused, never replaced or normalized. Its original group has
        # no execute bit, so adding mask rw cannot widen its effective rights.
        base = {}
        for line in original:
            match = re.fullmatch(r'(user|group|other)::([r-][w-][x-])',line)
            native.require(match is not None and match[1] not in base,
                'node-KVM-original-simple-ACL-required')
            base[match[1]] = match[2]
        native.require(set(base) == {'user','group','other'} and
            base['group'][2] == '-' and before['uid'] == before['euid'] and
            before['uid'] > 0 and before['uid'] != before['ownerUid'],
            'node-KVM-scoped-ACL-precondition')
        uid = str(before['uid'])
        access['grantAttempted'] = True
        run('node-KVM-runner-UID-ACL','sudo','-n','/usr/bin/setfacl','--no-mask',
            '--modify','user:'+uid+':rw-,mask::rw-','--',kvm,seconds=15)
        changed = access['aclAfter'] = acl('node-KVM-ACL-after')
        native.require(len(changed) == 5 and set(changed) ==
            set(original)|{'user:'+uid+':rw-','mask::rw-'},
            'node-KVM-only-runner-UID-ACL-changed')
    else:
        access['aclAfter'] = original
    after = access['after'] = facts()
    stable = ('uid','euid','gid','egid','groups','exists','symlink','characterDevice',
        'device','inode','rdev','major','minor','ownerUid','ownerGid')
    native.require(all(after.get(key) == before[key] for key in stable) and
        after['readWrite'],'node-real-KVM-required-no-fallback')


def qualify_node(output,revision):
    """One fresh development image; no ordinary constructor/TCG receipt reuse."""
    import math
    from tools import qualify_host_stream_kernel_stream_objects as c
    from tools import qualify_host_stream_kernel_objects as objects
    native.require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true' and
        os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric' and
        os.environ.get('GITHUB_REF_NAME') == native.NODE_BRANCH and
        os.environ.get('GITHUB_EVENT_NAME') == 'push','node-one-hosted-push')
    started = float(os.environ.get('LSF_Q35_STARTED_MONOTONIC','nan'))
    now = time.monotonic()
    native.require(math.isfinite(started) and 0 < started <= now and now-started < 1315,
        'node-original-setup-clock')
    end = started+1320
    native.require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'node-outside-checkout')
    output = fresh(output)
    private = output/'private'; private.mkdir(mode=0o700)
    (private/'tmp').mkdir(mode=0o700)
    (output/'commands').mkdir()
    environment = build_environment(output)
    environment.update(PYTHONDONTWRITEBYTECODE='1',LC_ALL='C',LANG='C',TMPDIR=str(private/'tmp'),
        GIT_NO_LAZY_FETCH='1',GIT_TERMINAL_PROMPT='0',CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',
        RUSTUP_AUTO_INSTALL='0',RUSTUP_TOOLCHAIN='1.97.1',
        KBUILD_BUILD_USER='lsf-node-boot',KBUILD_BUILD_HOST='isolated-ci',
        KBUILD_BUILD_TIMESTAMP='2026-10-23 00:00:00 UTC',KCONFIG_NOTIMESTAMP='1')
    commands = objects.Commands(ROOT,output/'commands',environment,
        deadline_seconds=max(1,int(end-now)),command_seconds=1200)
    commands.deadline = end-5 # Original single cleanup reserve, never renewed.
    receipt = {'schemaVersion':'lsf.q35-node-boot.v1','status':'in-progress',
        'sourceRevision':revision,'startedMonotonic':started,'deadlineMonotonic':end,
        'maximumSeconds':1320,'cleanupReserveSeconds':5,'maximumCommands':128,
        'maximumCommandSeconds':1200,'maximumCommandChannelBytes':4*1024**2,
        'maximumTotalLogBytes':16*1024**2,'maximumPublicBytes':128*1024**2,
        'maximumCSourceBytes':c.MAX_SOURCE,'maximumCSourceEntries':c.MAX_ENTRIES,
        'nodeFunding':False,'nodeRetired':False,'irqEnabled':False,'tcpEnabled':False,
        'whole738Complete':False,'wholeNodeFitQualified':False,'productionInstallation':False,
        'earlyPlatformObjectsRetroactivelyFunded':False,'freshVmBoots':0,
        'hermetic':False,'compilerImplicitInputsAttested':False,'reproducibility':'not-checked',
        'profile':{'qemu':'11.1.2','machine':'pc-q35-11.1','accel':'kvm',
            'cpus':1,'maxcpus':1,'virtualIommu':False,'interruptRemapping':False,
            'virtioNetPciVectors':3,'hostNetwork':False,'hostDrives':False}}
    stage = 'source-capture'; products = {}; tool_pins = {}
    def run(label,*argv,root=None,seconds=1200):
        nonlocal stage
        native.require(len(commands.records) < 128 and time.monotonic() < commands.deadline,
            'node-command-parent-bounds')
        stage = label; commands.root = ROOT if root is None else root
        commands.command_seconds = min(seconds,1200)
        return commands.run(label,*argv)
    def keep(name,path,maximum):
        raw = read_file(path,maximum)
        target = output/name
        native.require(target.parent == output and not target.exists(),'node-public-fresh-name')
        target.write_bytes(raw); products[name] = native.identity(raw)
        return raw
    try:
        # Capture every selected repo source plus ALL114 C inputs and the new
        # five research files BEFORE loading either maintained projector.
        native.require(run('source-head','git','-c','core.fsmonitor=false','rev-parse','HEAD',seconds=15).decode().strip() == revision,'node-source-head')
        listed = run('source-path-inventory','git','-c','core.fsmonitor=false','ls-files','-z',seconds=30)
        before = node_source_inputs(ROOT,listed)
        physical,capacity_raw = c.capacity_capture(ROOT)
        boot_raw = native.node_capture(ROOT)
        native.require(set(physical).isdisjoint(boot_raw) and len(physical)+len(boot_raw) <= c.MAX_ENTRIES and
            sum(r['bytes'] for r in physical.values())+sum(map(len,boot_raw.values())) <= c.MAX_SOURCE,
            'node-complete-research-envelope')
        receipt.update(sourceBefore=dict(sorted(before.items())),
            cPhysicalBefore={**physical,**{n:native.identity(b) for n,b in boot_raw.items()}},
            cPhysicalCount=len(physical)+len(boot_raw))
        write_json(output/'native-source-inputs.json',receipt['sourceBefore'])
        node_kvm_access(run,receipt,tool_pins)
        run('source-clean','git','-c','core.fsmonitor=false','diff','--no-ext-diff','--exit-code','HEAD','--',seconds=30)
        run('baseline-fetch','git','-c','core.fsmonitor=false','-c','gc.auto=0','fetch',
            '--no-tags','--no-recurse-submodules','--depth=1',
            'https://github.com/KirilsTurkins/latent-service-fabric.git',c.BASELINE,seconds=180)
        native.require(run('baseline-tree','git','-c','core.fsmonitor=false','rev-parse',
            c.BASELINE+'^{tree}',seconds=15).decode().strip() == c.BASELINE_TREE,'node-baseline-tree')
        recipe = private/'baseline-recipe'
        run('baseline-worktree','git','-c','core.fsmonitor=false','-c','gc.auto=0',
            'worktree','add','--detach',recipe,c.BASELINE,seconds=90)
        owner_python = Path(sys.executable).absolute()
        tool_pins['owner-python'] = {'path':str(owner_python),'target':str(owner_python.resolve()),
            **native.identity(read_file(owner_python.resolve(),256*1024**2))}
        native.require(run('owner-python-version',owner_python,'--version',seconds=30).strip() ==
            b'Python 3.13.5','node-pinned-owner-python')
        run('locked-python-dependencies',owner_python,'-m','pip','install',
            '--requirement',ROOT/'tools/requirements.lock',seconds=180)
        run('normal-prerequisite-update','sudo','apt-get','update',seconds=180)
        run('normal-prerequisite-install','sudo','apt-get','install','--yes','--no-install-recommends',
            'gcc','make','flex','bison','bc','libelf-dev','libssl-dev','binutils','libc6-dev',
            'curl','xz-utils','ninja-build','pkg-config','libglib2.0-dev','libpixman-1-dev','zlib1g-dev',
            'libfdt-dev','gnupg','python3-venv','python3-pip','python3-setuptools','python3-wheel',seconds=600)
        # Toolchain installation is an owned child of the SAME command/clock;
        # neither a pre-clock setup action nor rustup's implicit auto-install.
        rustup = Path(shutil.which('rustup') or '').absolute()
        native.require(rustup.is_file(),'node-runner-rustup-required')
        tool_pins['rustup'] = {'path':str(rustup),**native.identity(read_file(rustup.resolve(),256*1024**2))}
        run('fixed-rust-toolchain',rustup,'toolchain','install','1.97.1','--profile','minimal','--no-self-update',seconds=600)
        sysroot = Path(run('rust-sysroot',rustup,'run','1.97.1','rustc','--print','sysroot',seconds=30).decode().strip())
        tools = {n:Path(shutil.which(n) or '').absolute() for n in ('gcc','make','curl','gpg','ninja','sh','tar')}
        tools.update(python=Path('/usr/bin/python3'),rustc=sysroot/'bin/rustc',cargo=sysroot/'bin/cargo')
        native.require(sysroot.is_absolute() and all(p.is_file() for p in tools.values()),'node-normal-tools')
        for name,path in tools.items():
            tool_pins[name] = {'path':str(path),'target':str(path.resolve()),
                **native.identity(read_file(path.resolve(),256*1024**2))}
        native.require(run('pinned-rust-version',tools['rustc'],'--version',seconds=30).startswith(b'rustc 1.97.1 '),
            'node-pinned-rust')
        run('normal-c-version',tools['gcc'],'--version',seconds=30)
        manifest = objects.maintained.manifest(); archive = private/'linux.tar.xz'
        run('official-linux-source',tools['curl'],'--fail','--location','--proto','=https','--tlsv1.2',
            '--max-time','175','--output',archive,manifest['archive']['url'],seconds=180)
        native.require(commands.deadline-time.monotonic() >= 180,'node-auth-original-parent-reserve')
        originals = objects.maintained.authenticate_archive(archive,manifest,
            tuple(sorted(({'net/Kconfig','net/Makefile'}|set(objects.packet_source.fixture()['source']))-set(manifest['source']))))
        native.require(time.monotonic() < commands.deadline,'node-linux-auth-deadline')
        receipt['linuxArchive'] = native.identity(read_file(archive,objects.maintained.MAX_ARCHIVE))
        extract = private/'linux'; extract.mkdir()
        run('extract-linux-source',tools['tar'],'--extract','--xz','--file',archive,'--directory',extract,
            '--no-same-owner','--no-same-permissions',seconds=180)
        tree = extract/('linux-'+manifest['version'])
        native.require(all(c.read(tree/n,c.MAX_FILE) == raw for n,raw in originals.items()),'node-linux-originals')
        for name,suffix in [('net/Kconfig',objects.KCONFIG),('net/Makefile',objects.MAKEFILE)]:
            native.require(objects.SELECTED.encode() not in originals[name],'node-fresh-factory-kbuild')
            (tree/name).write_bytes(originals[name]+suffix.encode())
        build = private/'kernel-build'
        common = [tools['make'],'O='+str(build),'ARCH=x86_64','CC='+str(tools['gcc'])]
        run('original-defconfig',*common,'x86_64_defconfig',root=tree)
        base_config = c.read(build/'.config',c.MAX_DOCUMENT)
        selected = base_config.replace(b'# CONFIG_LSF_STREAM_FACTORY is not set\n',b'CONFIG_LSF_STREAM_FACTORY=y\n')
        native.require(selected != base_config,'node-factory-config-only')
        (build/'.config').write_bytes(selected)
        run('original-selected-olddefconfig',*common,'olddefconfig',root=tree)
        selected = c.read(build/'.config',c.MAX_DOCUMENT)
        native.require(c.identity(selected) == c.CONFIG,'node-original-selected-config')
        selected_file = private/'selected.config'; selected_file.write_bytes(selected)
        capacity_native = c.capacity_native_capture(tree,private/'capacity-originals')
        baseline_output = private/'baseline'; baseline_output.mkdir()
        run('pure-source-baseline',sys.executable,'-B',ROOT/'tools/qualify_host_stream_kernel_stream_objects.py',
            '--baseline-worker','--recipe',recipe,'--kernel-tree',tree,'--config',selected_file,
            '--output',baseline_output,seconds=180)
        baseline = json.loads(c.read(baseline_output/'baseline.json',16*c.MAX_DOCUMENT))
        native.require(baseline['sourceRevision'] == c.BASELINE and baseline['tree'] == c.BASELINE_TREE and
            baseline['sourceBefore'] == baseline['sourceAfter'] and baseline['actualConfiguration'] == c.CONFIG and
            baseline['compilerInvocations'] == baseline['runtimeInvocations'] == 0 and
            baseline['qualificationProjectionApplied'] is False,'node-pure-baseline')
        values = c.current_compose(c.derived_read(baseline_output/'derived',baseline['derived']),tree,netdev_post_init=True)
        stages = []
        values,constructor_stages = c.constructor_compose(values,tree); stages.extend(constructor_stages)
        values,row = c.vp_compose(values); stages.append(row)
        values,row = c.msi_compose(values,tree); stages.append(row)
        values,row = c.q35_compose(values,tree); stages.append(row)
        values,row = c.msi_descriptor_compose(values,tree,private/'msi-originals'); stages.append(row)
        values,row = c.node_compose(values); stages.append(row)
        values,row = c.geometry_compose(values,tree,private/'geometry-originals'); stages.append(row)
        values,row = c.capacity_compose(values,capacity_raw,capacity_native); stages.append(row)
        native.require(len(values) == 485,'node-complete-prior-485')
        rows485 = {n:c.identity(r) for n,r in sorted(values.items())}
        kbuild = {n:c.read(tree/n,c.MAX_FILE) for n in ('net/Kconfig','net/Makefile')}
        values,row = native.node_compose(values,kbuild,boot_raw); stages.append(row)
        for name,value in values.items():
            target = tree/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(value)
        rows488 = {n:c.identity(r) for n,r in sorted(values.items())}
        write_json(output/'derived-inputs.json',rows488)
        write_json(output/'projection-proof.json',{'stages':stages,'prior485':rows485,
            'nativePrimary':{n:c.identity(r) for n,r in capacity_native.items()},
            'researchUtf8':{n:r.decode('utf8') for n,r in {**capacity_raw,**boot_raw}.items()},
            'kbuildBeforeUtf8':{n:r.decode('utf8') for n,r in kbuild.items()}})
        # The only requested new config is the immutable built-in entry. Resolve
        # and record all actual values; never guess NR_CPUS equals topology.
        (build/'.config').write_bytes(selected+b'CONFIG_LSF_STREAM_NODE_BOOTSTRAP=y\n')
        run('boot-selected-olddefconfig',*common,'olddefconfig',root=tree)
        config = c.read(build/'.config',c.MAX_DOCUMENT)
        native.require(b'CONFIG_LSF_STREAM_NODE_BOOTSTRAP=y\n' in config,'node-boot-config-selected')
        old_values,new_values = objects.configuration(selected),objects.configuration(config)
        native.require({k:v for k,v in new_values.items() if k != 'CONFIG_LSF_STREAM_NODE_BOOTSTRAP'} ==
            {k:v for k,v in old_values.items() if k != 'CONFIG_LSF_STREAM_NODE_BOOTSTRAP'},
            'node-only-reviewed-config-addition')
        receipt['bootConfiguration'] = image.check_boot_configuration(config,objects.configuration)
        keep('selected-before.config',selected_file,c.MAX_DOCUMENT)
        keep('boot.config',build/'.config',c.MAX_DOCUMENT)
        run('fresh-node-kernel-image',*common,'-j2','bzImage',root=tree)
        kernel = build/'arch/x86/boot/bzImage'
        kernel_raw = keep('node-bzImage',kernel,image.MAX_KERNEL)
        receipt['kernel'] = image.kernel_image(kernel_raw)
        # Authenticate the accepted signed QEMU source; no ambient qemu binary.
        qemu_archive = private/'qemu.tar.xz'
        for name,pin in [('qemu.tar.xz',native.QEMU_PIN),('qemu.tar.xz.sig',native.QEMU_SIGNATURE),('release-key.asc',native.QEMU_KEY)]:
            path = private/name
            run('official-'+name,tools['curl'],'--fail','--location','--proto','=https','--tlsv1.2',
                '--max-time','175','--output',path,pin['url'],seconds=180)
            native.require(native.identity(read_file(path,pin['bytes'])) ==
                {k:pin[k] for k in ('bytes','sha256')},'node-qemu-source-identity')
        keyring = private/'qemu-keyring'; keyring.mkdir(mode=0o700)
        gpg = ['--no-options','--batch','--no-tty','--homedir',keyring,'--no-autostart',
            '--no-auto-key-retrieve','--status-fd=1']
        run('qemu-key-import',tools['gpg'],*gpg,'--import',private/'release-key.asc',seconds=30)
        signature = run('qemu-official-signature',tools['gpg'],*gpg,'--verify',private/'qemu.tar.xz.sig',qemu_archive,seconds=30)
        valid = re.findall(rb'^\[GNUPG:\] VALIDSIG ([A-F0-9]{40}) .+$',signature,re.M)
        native.require(valid == [native.QEMU_FINGERPRINT.encode()],'node-exact-release-signature')
        qemu_source,tar_inventory = native.node_qemu_extract(qemu_archive,private/'qemu-source',commands.deadline)
        write_json(output/'qemu-source.json',{'archive':native.QEMU_PIN,'signature':native.QEMU_SIGNATURE,
            'key':native.QEMU_KEY,'validSignature':native.QEMU_FINGERPRINT,**tar_inventory})
        qemu_build = private/'qemu-build'; qemu_build.mkdir()
        run('qemu-fixed-configure',tools['sh'],qemu_source/'configure','--python='+str(tools['python']),'--target-list=x86_64-softmmu',
            '--enable-kvm','--disable-tcg','--disable-rust','--disable-download',
            '--disable-debug-info','--disable-docs','--disable-guest-agent','--disable-tools',
            '--disable-slirp','--disable-sdl','--disable-gtk','--disable-vnc','--disable-opengl',
            '--disable-virglrenderer','--disable-plugins','--disable-capstone',root=qemu_build)
        run('qemu-fixed-build',tools['ninja'],'-j2','qemu-system-x86_64',root=qemu_build)
        qemu = qemu_build/'qemu-system-x86_64'
        qemu_pin = native.identity(read_file(qemu,128*1024**2))
        native.require(run('qemu-version',qemu,'--version',seconds=30).startswith(b'QEMU emulator version 11.1.2'),
            'node-actual-qemu-version')
        machines = run('qemu-machine-list',qemu,'-machine','help',seconds=30)
        native.require(re.search(rb'^pc-q35-11\.1 +',machines,re.M) is not None,'node-versioned-q35-machine')
        firmware = qemu_source/'pc-bios'
        firmware_pins = {n:native.identity(read_file(firmware/n,1024**2)) for n in ('bios-256k.bin','kvmvapic.bin')}
        receipt['qemuProduct'] = {'binary':qemu_pin,'firmware':firmware_pins,
            'version':'11.1.2','configurationSource':native.identity(read_file(qemu_source/'configure',1024**2))}
        source_hash = c.identity(c.canonical(rows488))['sha256']
        config_hash = native.identity(config)['sha256']
        environment.update(CARGO_TARGET_DIR=str(private/'native-target'),
            CARGO_ENCODED_RUSTFLAGS='\x1f'.join(FLAGS),
            CARGO_PROFILE_RELEASE_OPT_LEVEL='z',CARGO_PROFILE_RELEASE_LTO='fat',
            CARGO_PROFILE_RELEASE_CODEGEN_UNITS='1',CARGO_PROFILE_RELEASE_PANIC='abort',
            CARGO_PROFILE_RELEASE_STRIP='symbols',RUSTC=str(tools['rustc']),
            LSF_Q35_QUALIFICATION_KERNEL_SHA256=receipt['kernel']['sha256'],
            LSF_Q35_QUALIFICATION_SOURCE_SHA256=source_hash,LSF_Q35_QUALIFICATION_CONFIG_SHA256=config_hash)
        cargo_raw = run('build-node-native-example',tools['cargo'],'build','--locked','-j2','-p','latent-streams',
            '--example','kernel_constructor_vm','--features','development-outbound','--release',
            '--target',TARGET,'--message-format=json')
        executable = cargo_product(cargo_raw,ROOT,private/'native-target')
        child = keep('native-init',executable,native.MAX_NATIVE_INIT)
        receipt['nativeInit'] = native.native_elf(child)
        source = native.node_supervisor(boot_raw,read_file(ROOT/native.ORIGINAL,64*1024))
        # The actual command owner wraps this existing compile helper too.
        class Shared:
            def run(self,label,*argv):return run(label,*argv)
        supervisor,receipt['supervisor'] = image.build_init(Shared(),tools['gcc'],source,private)
        supervisor_raw = keep('constructor-init',supervisor,image.MAX_INIT)
        keep('constructor-init.c',private/'constructor-init.c',64*1024)
        receipt['executablePartition'] = native.executable_partition(supervisor_raw,child)
        spec = image.initramfs_spec(supervisor)+('file /native-init '+str(output/'native-init')+' 755 0 0\n').encode()
        (private/'node-initramfs.list').write_bytes(spec)
        cpio_raw = run('node-initramfs',build/'usr/gen_init_cpio','-t','0',private/'node-initramfs.list')
        native.require(0 < len(cpio_raw) <= image.MAX_INITRAMFS and cpio_raw.startswith(b'070701'),
            'node-actual-initramfs-bound')
        cpio = output/'node-initramfs.cpio'; cpio.write_bytes(cpio_raw); products[cpio.name] = native.identity(cpio_raw)
        boot_args = native.node_boot_argv(qemu,output/'node-bzImage',cpio,firmware)
        receipt['vmArgv'] = list(boot_args)
        serial = run('one-real-q35-kvm-node-prepare',*boot_args,seconds=image.VM_SECONDS)
        native.require(len(serial) <= image.MAX_SERIAL,'node-serial-channel-bound')
        receipt['observations'] = native.node_serial(serial); receipt['freshVmBoots'] = 1
        # Exact source/tool/image identities still hold AFTER the actual VM.
        after = node_source_inputs(ROOT,run('source-path-inventory-after','git','-c','core.fsmonitor=false','ls-files','-z',seconds=30))
        current_physical,current_raw = c.capacity_capture(ROOT)
        native.require(dict(sorted(after.items())) == receipt['sourceBefore'] and current_physical == physical and
            current_raw == capacity_raw and native.node_capture(ROOT) == boot_raw,'node-all-source-unchanged')
        native.require(c.read(build/'.config',c.MAX_DOCUMENT) == config,'node-config-stable')
        native.require(read_file(kernel,image.MAX_KERNEL) == kernel_raw and
            native.identity(read_file(qemu,128*1024**2)) == qemu_pin and
            all(native.identity(read_file(firmware/n,1024**2)) == pin for n,pin in firmware_pins.items()),
            'node-executed-products-stable')
        for name,pin in tool_pins.items():
            native.require(native.identity(read_file(Path(pin['path']).resolve(),256*1024**2)) ==
                {k:pin[k] for k in ('bytes','sha256')},'node-normal-tools-stable')
        native.require(time.monotonic() < commands.deadline,'node-parent-expiry-never-success')
        native.require(run('source-head-after','git','-c','core.fsmonitor=false','rev-parse','HEAD',seconds=15).decode().strip() == revision,'node-source-head-after')
        run('source-clean-after','git','-c','core.fsmonitor=false','diff','--no-ext-diff','--exit-code','HEAD','--',seconds=30)
        receipt.update(status='passed',sourceAfter=receipt['sourceBefore'],sourceUnchanged=True,
            cPhysicalAfter=receipt['cPhysicalBefore'],tools=tool_pins,products=products)
        write_json(output/'receipt.json',receipt)
        return receipt
    except BaseException:
        write_json(output/'FAILED.json',{**receipt,'stage':stage,'status':'failed','products':products,'tools':tool_pins})
        raise
    finally:
        write_json(output/'commands.json',commands.records)
        # No private build trees, source archives or unbounded debug products
        # are public artifacts. The workflow uploads only this finite manifest.
        files = [q for q in output.rglob('*') if q.is_file() and private not in q.parents]
        native.require(sum(q.stat().st_size for q in files) <= 128*1024**2,'node-public-byte-bound')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-commit',required=True)
    parser.add_argument('--node-boot',action='store_true')
    arguments = parser.parse_args()
    (qualify_node if arguments.node_boot else qualify)(arguments.output.resolve(),arguments.source_commit)
