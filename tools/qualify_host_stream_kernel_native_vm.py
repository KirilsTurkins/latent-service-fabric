"""First actual Rust native constructor / qualified kernel join; no quota refund."""
import argparse
import errno
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
from tools import ci_suite_inventory as registry, ci_suite_discovery as discovery
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
        native.require(not set(contract['expectedIgnored']) & cases, 'registered-owner-controls')
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
            available = discovery.listing(commands.run(label+'-all-list',executable.executable,'--list'))
            all_ignored = discovery.listing(commands.run(label+'-all-ignored',executable.executable,'--ignored','--list'))
            discovery.validate_cases(contract, available, all_ignored, {})
            native.require({name for name in available if name.startswith(prefix)} == cases,
                           'registered-owner-controls')
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
                (len(cases),0,0,0,len(available)-len(cases)))
            native.require(len(actual) == len(cases) and set(actual) == cases and totals == [expected],
                'all-fixed-owner-controls-executed')
            if label == 'native-owner':native_controls.outcomes(raw, len(available)-len(cases))
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


def retain_native_candidate(executable, output, receipt):
    """Record bounded rejection evidence without changing the image allowance."""
    candidate = executable.lstat()
    regular = stat.S_ISREG(candidate.st_mode)
    receipt['nativeCandidate'] = {'bytes':candidate.st_size,'mode':candidate.st_mode,
        'fileType':stat.S_IFMT(candidate.st_mode),'regularFile':regular,
        'symlink':stat.S_ISLNK(candidate.st_mode),'maximumAdmittedBytes':native.MAX_NATIVE_INIT}
    if regular and native.MAX_NATIVE_INIT < candidate.st_size <= MAX_REJECTED_NATIVE:
        rejected = read_file(executable,MAX_REJECTED_NATIVE)
        forensic = output/'native-init.rejected.elf'
        native.require(forensic.parent == output, 'native-forensic-owned-output')
        with forensic.open('xb') as saved:
            saved.write(rejected)
        forensic.chmod(0o600)
        receipt['rejectedNativeProduct'] = {**native.identity(rejected),
            'path':forensic.name,'maximumForensicBytes':MAX_REJECTED_NATIVE,
            'admitted':False,'executable':False,'executed':False,'includedInVm':False}


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
        retain_native_candidate(executable,output,receipt)
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
    'tools/qualify_host_stream_kernel_objects.py','tools/requirements.lock',
    'tools/tests/fixtures/q35-bar3.c')


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


# This is executed by the SAME owned child launcher as the positive QEMU,
# without starting a VM, opening a network device, or changing permissions.
_NODE_KVM_OPEN_PROBE = r"""
import json, os, stat
path = '/dev/kvm'
out = {'uid':os.getuid(), 'euid':os.geteuid(), 'gid':os.getgid(),
       'egid':os.getegid(), 'groups':sorted(os.getgroups()), 'label':None,
       'entry':None, 'statErrno':None, 'opened':False, 'openErrno':None, 'sameEntry':None}
try:
    with open('/proc/self/attr/current', 'rb') as source:
        label = source.read(257).strip()
    if len(label) <= 256:
        out['label'] = label.decode('ascii')
except (OSError, UnicodeError):
    pass
try:
    entry = os.lstat(path)
    out['entry'] = {'symlink':stat.S_ISLNK(entry.st_mode),
        'characterDevice':stat.S_ISCHR(entry.st_mode), 'mode':entry.st_mode,
        'device':entry.st_dev, 'inode':entry.st_ino, 'rdev':entry.st_rdev, 'major':os.major(entry.st_rdev),
        'minor':os.minor(entry.st_rdev), 'ownerUid':entry.st_uid, 'ownerGid':entry.st_gid,
        'readWrite':os.access(path, os.R_OK | os.W_OK, effective_ids=True)}
except OSError as error:
    out['statErrno'] = error.errno
else:
    try:
        fd = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        out['openErrno'] = error.errno
    else:
        try:
            opened = os.fstat(fd)
            out['opened'] = True
            out['sameEntry'] = ((opened.st_dev, opened.st_ino, opened.st_rdev) ==
                                (entry.st_dev, entry.st_ino, entry.st_rdev))
        finally:
            os.close(fd)
print(json.dumps(out, sort_keys=True, separators=(',', ':')))
"""


def node_kvm_observe(run, receipt, label, *, require_open):
    """Bound the actual child-context open without replacing the KVM boot."""
    native.require(label in ('initial', 'before-trace', 'before-boot', 'after-restore', 'after-boot-failure')
        and type(require_open) is bool, 'node-KVM-probe-fixed-stage')
    raw = run('node-KVM-'+label+'-open',sys.executable,'-I','-B','-c',
        _NODE_KVM_OPEN_PROBE,seconds=10)
    native.require(type(raw) is bytes and len(raw) <= 4096, 'node-KVM-probe-output-bound')
    observed = json.loads(raw)
    native.require(type(observed) is dict and set(observed) == {
        'uid','euid','gid','egid','groups','label','entry','statErrno',
        'opened','openErrno','sameEntry'}, 'node-KVM-probe-closed-record')
    native.require(all(type(observed[k]) is int and 0 <= observed[k] < 2**32
        for k in ('uid','euid','gid','egid')) and
        type(observed['groups']) is list and len(observed['groups']) <= 128 and
        all(type(x) is int and 0 <= x < 2**32 for x in observed['groups']) and
        observed['groups'] == sorted(set(observed['groups'])) and
        (observed['label'] is None or type(observed['label']) is str and
         len(observed['label']) <= 256 and all(32 <= ord(c) <= 126 for c in observed['label'])) and
        type(observed['opened']) is bool and
        (observed['openErrno'] is None or type(observed['openErrno']) is int and 0 < observed['openErrno'] < 4096) and
        (observed['statErrno'] is None or type(observed['statErrno']) is int and 0 < observed['statErrno'] < 4096) and
        (observed['sameEntry'] is None or type(observed['sameEntry']) is bool),
        'node-KVM-probe-record-types')
    entry = observed['entry']
    keys = ('mode','device','inode','rdev','major','minor','ownerUid','ownerGid')
    native.require(entry is None or type(entry) is dict and set(entry) == {
        *keys,'symlink','characterDevice','readWrite'} and
        all(type(entry[k]) is int and 0 <= entry[k] < 2**64 for k in keys) and
        all(type(entry[k]) is bool for k in ('symlink','characterDevice','readWrite')),
        'node-KVM-probe-device-types')
    native.require((observed['opened'] and observed['openErrno'] is None
                    and type(observed['sameEntry']) is bool and entry is not None
                    and observed['statErrno'] is None) or
        (not observed['opened'] and observed['sameEntry'] is None and
         ((entry is None and observed['statErrno'] is not None and observed['openErrno'] is None) or
          (entry is not None and observed['statErrno'] is None and observed['openErrno'] is not None))),
        'node-KVM-probe-record-consistency')
    row = {'stage':label, 'child':observed, 'acl':None}
    receipt.setdefault('kvmLaunchChecks',[]).append(row)
    baseline = receipt['kvmAccess']['after']
    same_identity = (entry is not None and not entry['symlink'] and entry['characterDevice'] and
        all(entry[k] == baseline[k] for k in keys) and
        all(observed[k] == baseline[k] for k in ('uid','euid','gid','egid','groups')))
    if same_identity:
        acl = run('node-KVM-'+label+'-ACL','/usr/bin/getfacl','--omit-header','--numeric',
            '--no-effective','--','/dev/kvm',seconds=10)
        native.require(type(acl) is bytes and len(acl) <= 4096, 'node-KVM-probe-ACL-bound')
        lines = [line for line in acl.decode('ascii').splitlines() if line]
        native.require(len(lines) <= 32 and all(re.fullmatch(r'[A-Za-z0-9:_-]{1,128}',line)
            for line in lines), 'node-KVM-probe-ACL-text')
        row['acl'] = lines
    if require_open:
        native.require(same_identity, 'node-KVM-probe-identity-changed')
        native.require(row['acl'] == receipt['kvmAccess']['aclAfter'], 'node-KVM-probe-ACL-changed')
        native.require(observed['opened'] and observed['sameEntry'], 'node-KVM-probe-real-open-required')
    return row


def node_kvm_before_boot(run, receipt):
    """Restore only the previously admitted UID grant, once, on the same device."""
    row = node_kvm_observe(run,receipt,'before-boot',require_open=False)
    observed,access = row['child'],receipt['kvmAccess']
    native.require(row['acl'] is not None, 'node-KVM-probe-identity-changed')
    if row['acl'] == access['aclAfter']:
        native.require(observed['opened'] and observed['sameEntry'], 'node-KVM-probe-real-open-required')
        return

    baseline = access['after']
    uid = baseline['uid']
    original,admitted = access['aclBefore'],access['aclAfter']
    grant = 'user:'+str(uid)+':rw-'
    checks = receipt['kvmLaunchChecks']
    trace = receipt.get('traceLossControl')
    # A completely different ACL, credential, error, or stage stays refused.
    simple = {}
    for line in original:
        match = re.fullmatch(r'(user|group|other)::([r-][w-][x-])',line)
        native.require(match is not None and match[1] not in simple,
            'node-KVM-recovery-original-simple-ACL-required')
        simple[match[1]] = match[2]
    native.require(access['grantAttempted'] is True and type(uid) is int and uid > 0 and
        set(simple) == {'user','group','other'} and simple['group'][2] == '-' and
        len(admitted) == 5 and len(set(admitted)) == 5 and
        set(admitted) == set(original)|{grant,'mask::rw-'} and
        row['acl'] == [line for line in admitted if line != grant] and
        not observed['opened'] and observed['openErrno'] == errno.EACCES and
        observed['entry']['readWrite'] is False and
        len(checks) >= 2 and checks[-2]['stage'] == 'before-trace' and
        checks[-2]['acl'] == admitted and checks[-2]['child']['opened'] is True and
        checks[-2]['child']['sameEntry'] is True and
        checks[-2]['child']['label'] == observed['label'] and
        trace == {'sink':'/dev/full', 'deviceMajor':1, 'deviceMinor':7, 'expectedExit':74,
            'actualExit':74, 'allDescendantsCleaned':True, 'partialGuestMayHaveBooted':True,
            'guestResultQualified':False} and receipt.get('emulatorAttempts') == 1 and
        'kvmAclRecovery' not in receipt, 'node-KVM-probe-ACL-changed')

    recovery = receipt['kvmAclRecovery'] = {'uid':uid,'attempted':False,
        'before':list(row['acl']),'restored':False,'target':'opened-device'}
    # O_PATH can pin the already-verified character device even after its
    # read/write grant vanished. setfacl follows this stable proc-fd reference.
    fd = os.open('/dev/kvm',os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        current = {'uid':os.getuid(),'euid':os.geteuid(),'gid':os.getgid(),
            'egid':os.getegid(),'groups':sorted(os.getgroups()),'mode':st.st_mode,
            'device':st.st_dev,'inode':st.st_ino,'rdev':st.st_rdev,
            'major':os.major(st.st_rdev),'minor':os.minor(st.st_rdev),
            'ownerUid':st.st_uid,'ownerGid':st.st_gid}
        native.require(stat.S_ISCHR(st.st_mode) and
            all(current[key] == baseline[key] for key in current),
            'node-KVM-recovery-anchor-identity')
        anchor = '/proc/'+str(os.getpid())+'/fd/'+str(fd)
        def anchored_acl(label):
            raw = run(label,'/usr/bin/getfacl','--omit-header','--numeric',
                '--no-effective','--',anchor,seconds=10)
            native.require(type(raw) is bytes and len(raw) <= 4096, 'node-KVM-probe-ACL-bound')
            lines = [line for line in raw.decode('ascii').splitlines() if line]
            native.require(len(lines) <= 32 and all(re.fullmatch(r'[A-Za-z0-9:_-]{1,128}',line)
                for line in lines), 'node-KVM-probe-ACL-text')
            return lines
        native.require(anchored_acl('node-KVM-recovery-before-ACL') == row['acl'],
            'node-KVM-recovery-anchor-ACL-changed')
        recovery['attempted'] = True
        run('node-KVM-recovery-runner-UID-ACL','sudo','-n','/usr/bin/setfacl','--no-mask',
            '--modify',grant,'--',anchor,seconds=15)
        recovery['after'] = anchored_acl('node-KVM-recovery-after-ACL')
        native.require(recovery['after'] == admitted, 'node-KVM-recovery-ACL-changed')
    finally:
        os.close(fd)
    # This is a fresh real open of the launch pathname, not a positive VM.
    node_kvm_observe(run,receipt,'after-restore',require_open=True)
    recovery['restored'] = True


def qualify_node(output,revision):
    """One fresh development image; no ordinary constructor/TCG receipt reuse."""
    import math
    from tools import qualify_host_stream_kernel_stream_objects as c
    from tools import qualify_host_stream_kernel_objects as objects
    native.require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true' and
        os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric' and
        os.environ.get('GITHUB_REF_NAME') in native.NODE_BRANCHES and
        os.environ.get('GITHUB_EVENT_NAME') == 'push','node-one-hosted-push')
    bar3 = os.environ.get('GITHUB_REF_NAME') == native.NODE_BAR3_BRANCH
    intx = os.environ.get('GITHUB_REF_NAME') in (native.NODE_INTX_BRANCH,native.NODE_BAR3_BRANCH)
    fixup = os.environ.get('GITHUB_REF_NAME') in (native.NODE_FIXUP_BRANCH,native.NODE_INTX_BRANCH,native.NODE_BAR3_BRANCH)
    setup = os.environ.get('GITHUB_REF_NAME') in (native.NODE_SETUP_BRANCH,native.NODE_FIXUP_BRANCH,native.NODE_INTX_BRANCH,native.NODE_BAR3_BRANCH)
    prefix = os.environ.get('GITHUB_REF_NAME') in (native.NODE_PREFIX_BRANCH,native.NODE_SETUP_BRANCH,native.NODE_FIXUP_BRANCH,native.NODE_INTX_BRANCH,native.NODE_BAR3_BRANCH)
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
        'pciConstructorQualified':False,'napiQualified':False,
        'hermetic':False,'compilerImplicitInputsAttested':False,'reproducibility':'not-checked',
        'profile':{'qemu':'11.1.2','machine':'pc-q35-11.1','accel':'kvm',
            'cpus':1,'maxcpus':1,'virtualIommu':False,'interruptRemapping':False,
            'virtioNetPciVectors':3,'hostNetwork':False,'hostDrives':False,
            'expectedPciBdf':'0000:00:03.0','expectedPciVendor':'1af4',
            'expectedPciDevice':'1041','modernOnly':True}}
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
        prefix_raw = native.node_prefix_capture(ROOT) if prefix else {}
        setup_raw = native.node_setup_capture(ROOT) if setup else {}
        fixup_raw = native.node_fixup_capture(ROOT) if fixup else {}
        intx_raw = native.node_intx_capture(ROOT) if intx else {}
        bar3_raw = native.node_bar3_capture(ROOT) if bar3 else {}
        groups = (boot_raw,prefix_raw,setup_raw,fixup_raw,intx_raw,bar3_raw)
        native.require(all(set(a).isdisjoint(b) for i,a in enumerate(groups) for b in groups[i+1:]),
            'node-research-captures-disjoint')
        extra_raw = {**boot_raw,**prefix_raw,**setup_raw,**fixup_raw,**intx_raw,**bar3_raw}
        native.require(set(physical).isdisjoint(extra_raw) and set(boot_raw).isdisjoint(prefix_raw) and
            len(physical)+len(extra_raw) <= c.MAX_ENTRIES and
            sum(r['bytes'] for r in physical.values())+sum(map(len,extra_raw.values())) <= c.MAX_SOURCE,
            'node-complete-research-envelope')
        receipt.update(sourceBefore=dict(sorted(before.items())),
            cPhysicalBefore={**physical,**{n:native.identity(b) for n,b in extra_raw.items()}},
            cPhysicalCount=len(physical)+len(extra_raw))
        write_json(output/'native-source-inputs.json',receipt['sourceBefore'])
        node_kvm_access(run,receipt,tool_pins)
        if intx:
            node_kvm_observe(run,receipt,'initial',require_open=True)
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
        if os.environ.get('GITHUB_REF_NAME') in (native.NODE_IDENTITY_BRANCH,native.NODE_PREFIX_BRANCH,native.NODE_SETUP_BRANCH,native.NODE_FIXUP_BRANCH,native.NODE_INTX_BRANCH,native.NODE_BAR3_BRANCH):
            run('node-q35-pci-identity-refusal-controls',owner_python,'-B','-m','unittest',
                'tools.tests.test_kernel_native_constructor_vm.Q35NodeBootSourceControls',
                '-v',seconds=30)
        if prefix:
            run('node-q35-prefix-refusal-controls',owner_python,'-B','-m','unittest',
                'tools.tests.test_kernel_native_constructor_vm.Q35NodePciPrefixControls',
                '-v',seconds=30)
        if setup:
            run('node-q35-setup-refusal-controls',owner_python,'-B','-m','unittest',
                'tools.tests.test_kernel_native_constructor_vm.Q35NodePciSetupControls',
                '-v',seconds=30)
        if fixup:
            run('node-q35-fixup-refusal-controls',owner_python,'-B','-m','unittest',
                'tools.tests.test_kernel_native_constructor_vm.Q35NodePciFixupControls',
                '-v',seconds=30)
        if intx:
            run('node-q35-intx-refusal-controls',owner_python,'-B','-m','unittest',
                'tools.tests.test_kernel_native_constructor_vm.Q35NodePciIntxControls',
                'tools.tests.test_kernel_native_constructor_vm.Q35NodePciIntxOwnerControls',
                'tools.tests.test_kernel_native_constructor_vm.Q35NodeKvmLaunchControls',
                'tools.tests.test_kernel_native_constructor_vm.Q35NodeKvmRecoveryControls',
                'tools.tests.test_kernel_native_constructor_vm.TraceRefusalControls','-v',seconds=30)
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
        if bar3:
            bar3_control = private/'bar3-control'
            run('node-q35-bar3-fault-control-compile',tools['gcc'],'-std=c11','-Wall','-Wextra','-Werror',
                ROOT/'tools/tests/fixtures/q35-bar3.c','-o',bar3_control,seconds=30)
            result = run('node-q35-bar3-fault-control-run',bar3_control,seconds=10)
            native.require(result == b'q35 BAR3 custody fault controls passed\n', 'node-bar3-fault-control-result')
            run('node-q35-bar3-fault-and-trace-controls',owner_python,'-B','-m','unittest',
                'tools.tests.test_q35_bar3','-v',seconds=30)
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
        if prefix:
            values,prefix_stages = native.node_prefix_compose(values,prefix_raw)
            stages.extend(prefix_stages)
        if setup:
            values,setup_stage = native.node_setup_compose(values,setup_raw)
            stages.append(setup_stage)
        if fixup:
            original_quirks = c.read(tree/'drivers/pci/quirks.c',c.MAX_FILE)
            values,fixup_stage = native.node_fixup_compose(values,fixup_raw,original_quirks)
            stages.append(fixup_stage)
        if intx:
            values,intx_stage = native.node_intx_compose(values,intx_raw)
            stages.append(intx_stage)
        if bar3:
            values,bar3_stage = native.node_bar3_compose(values,bar3_raw)
            stages.append(bar3_stage)
        for name,value in values.items():
            target = tree/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(value)
        derived_rows = {n:c.identity(r) for n,r in sorted(values.items())}
        write_json(output/'derived-inputs.json',derived_rows)
        write_json(output/'projection-proof.json',{'stages':stages,'prior485':rows485,
            'nativePrimary':{n:c.identity(r) for n,r in capacity_native.items()},
            'researchUtf8':{n:r.decode('utf8') for n,r in {**capacity_raw,**boot_raw,**prefix_raw,**setup_raw,**fixup_raw,**intx_raw,**bar3_raw}.items()},
            'kbuildBeforeUtf8':{n:r.decode('utf8') for n,r in kbuild.items()}})
        # The only requested new config is the immutable built-in entry. Resolve
        # and record all actual values; never guess NR_CPUS equals topology.
        requested = b'CONFIG_LSF_STREAM_NODE_BOOTSTRAP=y\n'
        if prefix:
            requested += b'CONFIG_LSF_STREAM_NODE_PCI_PREFIX=y\n'
        if setup:
            requested += b'CONFIG_LSF_STREAM_NODE_PCI_SETUP=y\n'
        if fixup:
            requested += b'CONFIG_LSF_STREAM_NODE_PCI_FIXUP=y\n'
        if intx:
            requested += b'CONFIG_LSF_STREAM_NODE_PCI_INTX=y\n'
        if bar3:
            requested += b'CONFIG_LSF_STREAM_NODE_PCI_BAR3=y\n'
        (build/'.config').write_bytes(selected+requested)
        run('boot-selected-olddefconfig',*common,'olddefconfig',root=tree)
        config = c.read(build/'.config',c.MAX_DOCUMENT)
        native.require(b'CONFIG_LSF_STREAM_NODE_BOOTSTRAP=y\n' in config and
            (not prefix or b'CONFIG_LSF_STREAM_NODE_PCI_PREFIX=y\n' in config) and
            (not setup or b'CONFIG_LSF_STREAM_NODE_PCI_SETUP=y\n' in config) and
            (not fixup or b'CONFIG_LSF_STREAM_NODE_PCI_FIXUP=y\n' in config) and
            (not intx or b'CONFIG_LSF_STREAM_NODE_PCI_INTX=y\n' in config) and
            (not bar3 or b'CONFIG_LSF_STREAM_NODE_PCI_BAR3=y\n' in config),'node-boot-config-selected')
        old_values,new_values = objects.configuration(selected),objects.configuration(config)
        reviewed = {'CONFIG_LSF_STREAM_NODE_BOOTSTRAP'}
        if prefix:
            reviewed.add('CONFIG_LSF_STREAM_NODE_PCI_PREFIX')
        if setup:
            reviewed.add('CONFIG_LSF_STREAM_NODE_PCI_SETUP')
        if fixup:
            reviewed.add('CONFIG_LSF_STREAM_NODE_PCI_FIXUP')
        if intx:
            reviewed.add('CONFIG_LSF_STREAM_NODE_PCI_INTX')
        if bar3:
            reviewed.add('CONFIG_LSF_STREAM_NODE_PCI_BAR3')
        native.require({k:v for k,v in new_values.items() if k not in reviewed} ==
            {k:v for k,v in old_values.items() if k not in reviewed},
            'node-only-reviewed-config-addition')
        native.require(new_values.get('CONFIG_PRINTK') == 'y' and
            new_values.get('CONFIG_PRINTK_TIME') == 'y' and
            new_values.get('CONFIG_CONSOLE_LOGLEVEL_DEFAULT') == '7',
            'node-pci-observation-console-config')
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
        qemu_derivatives = {}
        if intx:
            for name,script in (('util/log.c',native.INTX_SINK),
                                ('hw/virtio/virtio-pci.c',native.INTX_VIRTIO)):
                target = qemu_source/name
                original = read_file(target,4*1024**2)
                derived,proof = native.node_intx_module(intx_raw,script).transform(original)
                native.require(proof['originalSourceInverseExact'] is True and
                    proof['qemuExecuted'] is False,'node-qemu-derivation-inverse')
                extra_proof = None
                if bar3 and name == 'hw/virtio/virtio-pci.c':
                    derived,extra_proof = native.node_intx_module(bar3_raw,native.BAR3_QEMU).transform(derived)
                    native.require(extra_proof['originalSourceInverseExact'] is True and
                        extra_proof['qemuExecuted'] is False and extra_proof['fullBarSizing'] is False,
                        'node-bar3-qemu-derivation-inverse')
                target.write_bytes(derived)
                native.require(read_file(target,4*1024**2) == derived,'node-qemu-derivation-written')
                qemu_derivatives[name] = {'before':native.identity(original),
                    'after':native.identity(derived),'proof':proof}
                if extra_proof is not None:
                    qemu_derivatives[name]['bar3Proof'] = extra_proof
        qemu_build = private/'qemu-build'; qemu_build.mkdir()
        run('qemu-fixed-configure',tools['sh'],qemu_source/'configure','--python='+str(tools['python']),'--target-list=x86_64-softmmu',
            '--enable-kvm','--disable-tcg','--disable-rust','--disable-download',
            '--disable-debug-info','--disable-docs','--disable-guest-agent','--disable-tools',
            '--disable-slirp','--disable-sdl','--disable-gtk','--disable-vnc','--disable-opengl',
            '--disable-virglrenderer','--disable-plugins','--disable-capstone',
            *(['--enable-trace-backends=log'] if intx else []),root=qemu_build)
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
        if intx:
            receipt['qemuDiagnosticDerivatives'] = qemu_derivatives
            receipt['qemuDiagnosticOnly'] = True
        source_hash = c.identity(c.canonical(derived_rows))['sha256']
        config_hash = native.identity(config)['sha256']
        environment.update(CARGO_TARGET_DIR=str(private/'native-target'),
            CARGO_ENCODED_RUSTFLAGS='\x1f'.join(FLAGS),
            CARGO_PROFILE_RELEASE_OPT_LEVEL='z',CARGO_PROFILE_RELEASE_LTO='fat',
            CARGO_PROFILE_RELEASE_CODEGEN_UNITS='1',CARGO_PROFILE_RELEASE_PANIC='abort',
            CARGO_PROFILE_RELEASE_STRIP='symbols',RUSTC=str(tools['rustc']),
            LSF_Q35_QUALIFICATION_KERNEL_SHA256=receipt['kernel']['sha256'],
            LSF_Q35_QUALIFICATION_SOURCE_SHA256=source_hash,LSF_Q35_QUALIFICATION_CONFIG_SHA256=config_hash)
        if prefix:
            environment['LSF_Q35_PREFIX_PROFILE'] = native.SETUP_PROFILE if setup else native.PREFIX_PROFILE
        cargo_raw = run('build-node-native-example',tools['cargo'],'build','--locked','-j2','-p','latent-streams',
            '--example','kernel_constructor_vm','--features','development-outbound','--release',
            '--target',TARGET,'--message-format=json')
        executable = cargo_product(cargo_raw,ROOT,private/'native-target')
        retain_native_candidate(executable,output,receipt)
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
        if intx:
            from tools import q35_intx_owner, q35_intx_trace
            boot_args = q35_intx_owner.trace_argv(boot_args, bar3=bar3)
            node_kvm_observe(run,receipt,'before-trace',require_open=True)
            stage = 'qemu-trace-loss-refusal'
            commands.root = ROOT
            receipt['traceLossControl'] = q35_intx_owner.probe_loss(commands,boot_args)
            receipt['emulatorAttempts'] = 1  # The loss probe may boot partway.
            node_kvm_before_boot(run,receipt)
            receipt['emulatorAttempts'] = 2  # The next command is the single positive VM.
        receipt['vmArgv'] = list(boot_args)
        vm_log_index = len(commands.records)
        try:
            serial = run('one-real-q35-kvm-node-prepare',*boot_args,seconds=image.VM_SECONDS)
        except Exception:
            if intx:
                failed_stage = stage
                try:
                    node_kvm_observe(run,receipt,'after-boot-failure',require_open=False)
                except Exception as inspection_error:
                    receipt['kvmFailureInspection'] = {'errorType':type(inspection_error).__name__}
                finally:
                    stage = failed_stage
            raise
        native.require(len(serial) <= image.MAX_SERIAL,'node-serial-channel-bound')
        receipt['observations'] = (native.node_bar3_serial(serial) if bar3 else
            native.node_intx_serial(serial) if intx else
            native.node_fixup_serial(serial) if fixup else
            native.node_setup_serial(serial) if setup else
            native.node_prefix_serial(serial) if prefix else native.node_serial(serial))
        receipt['freshVmBoots'] = 1
        if intx:
            trace_path = commands.output/'logs'/f'{vm_log_index:02d}-one-real-q35-kvm-node-prepare.stderr.txt'
            trace = read_file(trace_path,4*1024**2)
            fact = receipt['observations']['pciIntx']
            if bar3:
                from tools import q35_bar3_trace
                trace_observed = q35_bar3_trace.inspect(trace,fact['originalCommand'],fact['pin'],fact['line'])
            else:
                trace_observed = q35_intx_trace.inspect(trace,fact['originalCommand'],fact['pin'],fact['line'])
            native.require(receipt['traceLossControl']['actualExit'] == 74 and
                commands.records[vm_log_index]['descendantsCleaned'] is True,
                'node-trace-loss-control-and-retirement')
            receipt['pciTrace'] = {'raw':native.identity(trace),'events':list(q35_intx_owner.events(bar3)),
                'sinkFailureControl':receipt['traceLossControl'], 'observation':trace_observed}
        # Exact source/tool/image identities still hold AFTER the actual VM.
        after = node_source_inputs(ROOT,run('source-path-inventory-after','git','-c','core.fsmonitor=false','ls-files','-z',seconds=30))
        current_physical,current_raw = c.capacity_capture(ROOT)
        native.require(dict(sorted(after.items())) == receipt['sourceBefore'] and current_physical == physical and
            current_raw == capacity_raw and native.node_capture(ROOT) == boot_raw and
            (not prefix or native.node_prefix_capture(ROOT) == prefix_raw) and
            (not setup or native.node_setup_capture(ROOT) == setup_raw) and
            (not fixup or native.node_fixup_capture(ROOT) == fixup_raw) and
            (not intx or native.node_intx_capture(ROOT) == intx_raw) and
            (not bar3 or native.node_bar3_capture(ROOT) == bar3_raw),'node-all-source-unchanged')
        if intx:
            native.require(all(native.identity(read_file(qemu_source/name,4*1024**2)) == row['after']
                for name,row in qemu_derivatives.items()),'node-qemu-derived-source-stable')
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
