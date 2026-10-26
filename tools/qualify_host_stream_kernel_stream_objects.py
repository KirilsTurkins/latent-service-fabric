#!/usr/bin/env python3
"""One fixed hosted C object check; no image, boot, consumer or qualification."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '013c3866942f1654b0effeebc93986b1c5268c2c'
BASELINE_TREE = 'ee776dfd184e4f3128561ba5213f95988962c98e'
CHECKPOINT = 'a92632a589ceb4db69207f9d6ff5dba286b8eaa5'
BRANCH = 'test/sdk-738-stream-objects-20261026'
WORKFLOW = '.github/workflows/stream-provider-objects.yml'
SOURCE_PATHS = ('research/standard-outbound/linux-6.12-lineage/device-prepaid.h', 'research/standard-outbound/linux-6.12-lineage/factory-stream-find-vqs.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-material-arena.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-material-plan.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-address.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-core.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-cpu.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-fixed.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-name.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-operations.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-retirement.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-root-final-free.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-rss.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-rx-preallocate.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-stop.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-udp-cork.c', 'research/standard-outbound/linux-6.12-lineage/stream-material-geometry-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-net-geometry.c', 'research/standard-outbound/linux-6.12-lineage/stream-net-material-geometry.c', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-core-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-cpu-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-cpu.c', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-fixed-geometry-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-fixed-geometry.c', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-fixed-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-name-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-operation-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-owned-ring.c', 'research/standard-outbound/linux-6.12-lineage/stream-pci-material-geometry.c', 'research/standard-outbound/linux-6.12-lineage/stream-protocol-allocation.c', 'research/standard-outbound/linux-6.12-lineage/stream-ring-geometry.c', 'research/standard-outbound/linux-6.12-lineage/stream-ring-profile-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-skb-dispatch.c', 'research/standard-outbound/linux-6.12-lineage/stream-udp-cork-private.c', 'research/standard-outbound/linux-6.12-lineage/stream-udp-private.c', 'tools/host_stream_kernel_stream_core.py', 'tools/host_stream_kernel_stream_cpu.py', 'tools/host_stream_kernel_stream_fixed_netdev.py', 'tools/host_stream_kernel_stream_name.py', 'tools/host_stream_kernel_stream_netdev.py', 'tools/host_stream_kernel_stream_operations.py', 'tools/host_stream_kernel_stream_protocol.py', 'tools/host_stream_kernel_stream_rss_failure.py', 'tools/host_stream_kernel_stream_rx.py', 'tools/host_stream_kernel_stream_skb.py', 'tools/host_stream_kernel_stream_udp.py')
SOURCE_SHA = '0d297733d0d376b952cafd03ae8e4c9477b979e5afd90d79d53e938ef34e4397'
SOURCE_BYTES = 337639
CLASSDIR_SOURCE_PATHS = tuple(sorted((*SOURCE_PATHS,
    'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-classdir.c',
    'research/standard-outbound/linux-6.12-lineage/stream-netdev-classdir-private.h',
    'tools/host_stream_kernel_stream_classdir.py',
)))
CLASSDIR_SOURCE_SHA = 'c0245686c1c5c5217c778215a151888a853d1ec21f15a2a372330ad7693aedca'
CLASSDIR_SOURCE_BYTES = 367882
CLASSDIR_BRANCH = 'test/sdk-738-classdir-objects-20261026'
CLASSDIR_TARGETS = ('net/factory.o','drivers/base/core.o','lib/kobject.o','net/core/net-sysfs.o')
REGISTRATION_SOURCE_PATHS = tuple(sorted((*CLASSDIR_SOURCE_PATHS,
    'research/standard-outbound/linux-6.12-lineage/factory-stream-classdir-registration.c',
    'research/standard-outbound/linux-6.12-lineage/stream-classdir-registration-private.h',
)))
REGISTRATION_SOURCE_SHA = 'c18734a80e471d1f7933193798feff4c8d746e7b9a701bec3595c3b65d3616eb'
REGISTRATION_SOURCE_BYTES = 415571
REGISTRATION_BRANCH = 'test/sdk-738-classdir-kernfs-objects-20261026'
REGISTRATION_TARGETS = ('net/factory.o','drivers/base/core.o','lib/kobject.o',
    'fs/sysfs/dir.o','fs/kernfs/dir.o','lib/idr.o','lib/radix-tree.o',
    'security/security.o','security/selinux/hooks.o')
CHECKPOINT45_SHA = '1ec18c5c933a74a8378cfa0da8893cb6612a84d6e14f02614a769365f6b30f62'
CONFIG = {'bytes':143135, 'sha256':'0015c9ac3b9af98af1e4a0f88788321e96193ce6a387c5a6cec6eaa358cdc1d6'}
TARGETS = ('net/factory.o','net/socket.o','net/core/sock.o','net/ipv4/af_inet.o',
    'net/ipv6/af_inet6.o','net/ipv4/ip_output.o','net/ipv4/route.o','net/core/dev.o',
    'net/core/dev_addr_lists.o','net/core/net-sysfs.o','net/core/skbuff.o','net/ethernet/eth.o',
    'drivers/net/virtio_net.o','drivers/virtio/virtio_ring.o','drivers/virtio/virtio_pci_common.o',
    'drivers/virtio/virtio_pci_modern.o','drivers/base/core.o','lib/kobject.o')
MAX_PUBLIC, MAX_DOCUMENT, MAX_OBJECT = 128*1024**2, 1024**2, 16*1024**2
MAX_SOURCE, MAX_FILE, MAX_ENTRIES = 16*1024**2, 4*1024**2, 512
MAX_COMMANDS = 32
STAGES = ('source-head','source-tree','source-clean','baseline-object','baseline-tree',
    'baseline-worktree','baseline-head','baseline-clean-before','baseline-clean-after',
    'baseline-tree-after','locked-python-dependencies','normal-prerequisite-update',
    'normal-prerequisite-install','gcc-version','make-version','as-version','ld-version',
    'rustc-version','official-source','extract-source','original-defconfig','selected-olddefconfig',
    'pure-baseline','eighteen-objects','classdir-objects','source-clean-after','source-tree-after','source-head-after')
REGISTRATION_STAGES = (*STAGES,'baseline-fetch','classdir-kernfs-objects')
DOCUMENTS = {'receipt.json':MAX_DOCUMENT,'source-inputs.json':16*MAX_DOCUMENT,
    'derived-inputs.json':4*MAX_DOCUMENT,'baseline-inputs.json':16*MAX_DOCUMENT,
    'commands.json':MAX_DOCUMENT,'baseline.config':MAX_DOCUMENT,'selected.config':MAX_DOCUMENT,
    'generated-autoconf.h':MAX_DOCUMENT}


def require(value, code):
    if not value:
        raise ValueError('stream-object-'+code)


def canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()


def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def read(path, maximum):
    require(not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode), 'regular-input')
    with path.open('rb') as stream:
        raw=stream.read(maximum+1)
    require(len(raw)<=maximum, 'input-bound')
    return raw


def write_json(path, value, maximum=16*MAX_DOCUMENT):
    raw=canonical(value)
    require(len(raw)<=maximum,'document-bound')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)


def deadline(started, now=None):
    now=time.monotonic() if now is None else now
    require(type(started) is float and math.isfinite(started) and 0<=started<=now,
        'original-start')
    end=started+1320.0
    require(now<end-5.0,'original-deadline')
    return end


def mode_targets(classdir=False, classdir_kernfs=False):
    require(type(classdir) is bool and type(classdir_kernfs) is bool and
        not (classdir and classdir_kernfs),'closed-classdir-mode')
    return REGISTRATION_TARGETS if classdir_kernfs else CLASSDIR_TARGETS if classdir else TARGETS


def selected_sources(root, *, classdir=False, classdir_kernfs=False):
    mode_targets(classdir,classdir_kernfs)
    paths = REGISTRATION_SOURCE_PATHS if classdir_kernfs else CLASSDIR_SOURCE_PATHS if classdir else SOURCE_PATHS
    require(len(paths)==len(set(paths))==(52 if classdir_kernfs else 50 if classdir else 47),'source-path-count')
    rows={name:identity(read(root/name,65536)) for name in paths}
    require(sum(r['bytes'] for r in rows.values())==(REGISTRATION_SOURCE_BYTES if classdir_kernfs else CLASSDIR_SOURCE_BYTES if classdir else SOURCE_BYTES) and
        hashlib.sha256(canonical(rows)).hexdigest()==(REGISTRATION_SOURCE_SHA if classdir_kernfs else CLASSDIR_SOURCE_SHA if classdir else SOURCE_SHA),
        'frozen-52-source' if classdir_kernfs else 'frozen-50-source' if classdir else 'frozen-47-source')
    return rows


def safe_name(name):
    p=PurePosixPath(name)
    require(type(name) is str and p.as_posix()==name and not p.is_absolute() and
        '..' not in p.parts and '\\' not in name and ':' not in name and name!='.','source-path')
    return name


def derived_write(output, values):
    require(type(values) is dict and 1<=len(values)<=MAX_ENTRIES,'derived-count')
    rows={};total=0
    output.mkdir()
    for name,raw in sorted(values.items()):
        safe_name(name)
        require(type(raw) is bytes and 0<len(raw)<=MAX_FILE,'derived-file-bound')
        total+=len(raw);require(total<=MAX_SOURCE,'derived-total-bound')
        q=output/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw)
        rows[name]=identity(raw)
    return rows


def derived_read(output, rows):
    require(type(rows) is dict and 1<=len(rows)<=MAX_ENTRIES,'derived-count')
    result={};total=0
    for name,bound in sorted(rows.items()):
        safe_name(name);raw=read(output/name,MAX_FILE);total+=len(raw)
        require(total<=MAX_SOURCE and identity(raw)==bound,'derived-bound-identity')
        result[name]=raw
    return result


def input_files(root):
    # Fixed repository source families; these are metadata, never uploaded code.
    paths=set((root/'tools').rglob('*.py'))
    paths.update((root/'tools/tests/fixtures').glob('host_stream_kernel*.json'))
    paths.update(q for q in (root/'research/standard-outbound/linux-6.12-lineage').iterdir()
        if q.is_file())
    paths.add(root/'tools/requirements.lock')
    require(len(paths)<=4096,'recipe-count')
    total=0;result={}
    for q in sorted(paths):
        raw=read(q,MAX_FILE);total+=len(raw);require(total<=128*1024**2,'recipe-total')
        result[q.relative_to(root).as_posix()]=identity(raw)
    return result


def baseline_worker(recipe, tree, config, output):
    # Fresh Python process: no current tools module/global is replaced. Only
    # regular, byte-bound data files cross back to the current controller.
    require(recipe.is_absolute() and tree.is_absolute() and output.is_absolute(),'worker-paths')
    sys.path.insert(0,str(recipe))
    from tools import host_stream_kernel_cleanup_native_programme as programme
    from tools import host_stream_kernel_return_source as source
    from tools import host_stream_kernel_retirement_observation as observation
    objects=programme.baseline.objects
    require(programme.ROOT.resolve()==recipe.resolve(),'worker-original-root')
    before=input_files(recipe)
    actual=read(config,MAX_DOCUMENT);require(identity(actual)==CONFIG,'worker-actual-config')
    manifest=objects.maintained.manifest()
    names=set(manifest['source'])|{'net/Kconfig','net/Makefile'}|set(objects.packet_source.fixture()['source'])
    original={n:objects.paths.read(tree,n,objects.maintained.MAX_FILE) for n in names}
    base,frozen,originals=programme.baseline_source(tree,original)
    for n in sorted(programme.source_names()-{'selected.config'}):
        if n not in originals:originals[n]=objects.paths.read(tree,n,objects.maintained.MAX_FILE)
    require(sum(map(len,originals.values()))<=objects.maintained.MAX_SELECTED,'worker-selected-originals')
    canonical_config,probes=source.compiler_probe_projection(actual)
    fixture,fixture_proof=programme.source_fixture_configuration(canonical_config)
    normal=programme.compose(base,originals,fixture)
    normal=observation.transform(normal)
    rows=derived_write(output/'derived',normal)
    require(before==input_files(recipe),'worker-source-mutated')
    write_json(output/'baseline.json',{'sourceRevision':BASELINE,'tree':BASELINE_TREE,
        'sourceBefore':before,'sourceAfter':before,'normalSourceFreeze':frozen,
        'normalOwnedFreeze':programme.local_freeze(),'actualConfiguration':identity(actual),
        'sourceFixtureConfiguration':fixture_proof,'compilerProbeDataOnly':probes,
        'derived':rows,'compilerInvocations':0,'runtimeInvocations':0,
        'qualificationProjectionApplied':False})


def udp_source(values, tree):
    # This TU is genuinely absent from the original normal derived map. Add
    # ONLY its exact original primary; never reset an already-transformed TU.
    from tools.host_stream_kernel_stream_udp import IP
    require(IP not in values,'fresh-udp-ip-primary')
    raw=read(tree/IP,MAX_FILE)
    require(identity(raw)=={'bytes': 43820, 'sha256': 'f5d4f5dee6e0995e5b82dc53519ba1480026085b9ea14e472c956f7db93c20b8'},'whole-original-udp-ip-primary')
    result=dict(values);result[IP]=raw
    return result


def current_compose(values, tree, *, classdir=False, classdir_kernfs=False):
    mode_targets(classdir,classdir_kernfs)
    from tools import host_stream_kernel_stream_operations as operations
    from tools import host_stream_kernel_stream_protocol as protocol
    from tools import host_stream_kernel_stream_udp as udp
    from tools import host_stream_kernel_stream_rx as rx
    from tools import host_stream_kernel_stream_netdev as address
    from tools import host_stream_kernel_stream_cpu as cpu
    from tools import host_stream_kernel_stream_fixed_netdev as fixed
    from tools import host_stream_kernel_stream_name as name
    from tools import host_stream_kernel_stream_rss_failure as rss
    from tools import host_stream_kernel_stream_core as core
    values=operations.transform(values)
    values=protocol.transform(values,read(tree/protocol.IPV6,MAX_FILE))
    values=udp.transform(udp_source(values,tree))
    values=rx.transform(values,{n:read(tree/n,MAX_FILE) for n in rx.PREIMAGES})
    values=address.transform(values,read(tree/address.SOURCE,MAX_FILE))
    values=cpu.transform(values,{n:read(tree/n,MAX_FILE) for n in cpu.PREIMAGES})
    values=fixed.transform(values,{n:read(tree/n,MAX_FILE) for n in fixed.PRIMARY})
    values=core.transform(rss.transform(name.transform(values)))
    if classdir or classdir_kernfs:
        from tools import host_stream_kernel_stream_classdir
        values=host_stream_kernel_stream_classdir.transform(values)
    from tools.host_stream_kernel_stream_skb import finish
    values=finish(values)
    if classdir_kernfs:
        values=host_stream_kernel_stream_classdir.registration_transform(values)
    require(b'lsf_factory_selected_consumer(void)\n{\n    return NULL;\n}' in
        values['net/factory-private.h'], 'unselected-consumer')
    return values


def object_identity(path):
    raw=read(path,MAX_OBJECT)
    require(len(raw)>=64 and raw[:7]==b'\x7fELF\x02\x01\x01' and
        struct.unpack_from('<HHI',raw,16)==(1,62,1),'relocatable-x86-64-object')
    shoff=struct.unpack_from('<Q',raw,40)[0]
    size,count=struct.unpack_from('<HH',raw,58)
    require(size==64 and count>0 and shoff>=64 and shoff+size*count<=len(raw),'object-section-table')
    # SHN_UNDEF is ordinary in ET_REL; no link/whole-symbol claim is made.
    return identity(raw)


def public_allowed(name, *, classdir=False, classdir_kernfs=False):
    targets=mode_targets(classdir,classdir_kernfs)
    if name in DOCUMENTS:return DOCUMENTS[name]
    if name in {'objects/'+n for n in targets}:return MAX_OBJECT
    match=re.fullmatch(r'logs/([0-9]{2})-([a-z0-9-]+)\.(stdout|stderr)\.txt',name)
    if match and int(match[1])<MAX_COMMANDS and match[2] in (REGISTRATION_STAGES if classdir_kernfs else STAGES):return 4*1024**2
    return None


def admit(output, *, classdir=False, classdir_kernfs=False):
    targets=mode_targets(classdir,classdir_kernfs)
    require(not output.is_symlink() and output.is_dir(),'public-output-directory')
    rows={};total=logs=0
    for q in sorted(output.rglob('*')):
        require(not q.is_symlink(),'public-symlink')
        if q.is_dir():continue
        name=q.relative_to(output).as_posix()
        if name=='ADMISSION.json':continue
        maximum=public_allowed(name,classdir=classdir,classdir_kernfs=classdir_kernfs);require(maximum is not None,'public-member')
        raw=read(q,maximum);total+=len(raw)
        if name.startswith('logs/'):logs+=len(raw)
        require(total<=MAX_PUBLIC-MAX_DOCUMENT and logs<=16*1024**2,'public-union-bound')
        rows[name]=identity(raw)
    require('receipt.json' in rows and len(rows)<=len(DOCUMENTS)+len(targets)+2*MAX_COMMANDS,'public-inventory')
    record={'schemaVersion':'lsf.stream-object-public.v1','files':rows,'payloadBytes':total,
        'maximumUnionBytes':MAX_PUBLIC,'admissionMaximumBytes':MAX_DOCUMENT}
    raw=canonical(record);require(len(raw)<=MAX_DOCUMENT and total+len(raw)<=MAX_PUBLIC,'public-admission-bound')
    (output/'ADMISSION.json').write_bytes(raw)
    return record


def _copy_public(source, output, name, maximum):
    raw=read(source,maximum);q=output/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw)


def run(output, revision, started, *, classdir=False, classdir_kernfs=False):
    targets=mode_targets(classdir,classdir_kernfs)
    end=deadline(started) # Before imports, filesystem mutation or tool probes.
    require(sys.platform=='linux' and os.environ.get('GITHUB_ACTIONS')=='true' and
        os.environ.get('GITHUB_REPOSITORY')=='KirilsTurkins/latent-service-fabric' and
        os.environ.get('GITHUB_REF_NAME')==(REGISTRATION_BRANCH if classdir_kernfs else CLASSDIR_BRANCH if classdir else BRANCH) and os.environ.get('GITHUB_EVENT_NAME')=='push',
        'fixed-hosted-origin')
    require(type(revision) is str and re.fullmatch('[0-9a-f]{40}',revision),'source-revision')
    before=selected_sources(ROOT,classdir=classdir,classdir_kernfs=classdir_kernfs)
    output=output.resolve()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents and
        not output.exists(),'fresh-public-outside-source')
    sys.path.insert(0,str(ROOT))
    from tools import qualify_host_stream_kernel_objects as objects
    output.mkdir(mode=0o700)
    scratch=Path(tempfile.mkdtemp(prefix='stream-object-private-',dir=output.parent))
    (scratch/'tmp').mkdir(mode=0o700);(scratch/'commands').mkdir(mode=0o700)
    keep=('PATH','HOME','USER','LOGNAME','RUSTUP_HOME','RUSTUP_TOOLCHAIN','CARGO_HOME','SSL_CERT_FILE','SSL_CERT_DIR')
    environment={k:v for k,v in os.environ.items() if k in keep}
    environment.update(PYTHONDONTWRITEBYTECODE='1',LC_ALL='C',LANG='C',TMPDIR=str(scratch/'tmp'),
        KBUILD_BUILD_USER='lsf-object-check',KBUILD_BUILD_HOST='isolated-ci',
        KBUILD_BUILD_TIMESTAMP='2026-10-23 00:00:00 UTC',KCONFIG_NOTIMESTAMP='1')
    if classdir_kernfs:
        environment.update(GIT_NO_LAZY_FETCH='1',GIT_TERMINAL_PROMPT='0')
    commands=objects.Commands(ROOT,scratch/'commands',environment,deadline_seconds=end-time.monotonic(),command_seconds=1200)
    commands.deadline=end-5.0 # ONE reserve; run_owned itself includes cleanup.
    receipt={'schemaVersion':'lsf.stream-classdir-kernfs-objects.v1' if classdir_kernfs else 'lsf.stream-classdir-objects.v1' if classdir else 'lsf.stream-normal-objects.v1','status':'in-progress','stage':'preflight',
        'sourceRevision':revision,'checkpoint':CHECKPOINT,'baselineRecipeRevision':BASELINE,
        'baselineRecipeTree':BASELINE_TREE,'sourceBefore':before,'sourceAfter':None,'checkpoint45SourceDigest':CHECKPOINT45_SHA,
        'objectTargets':list(targets),'products':{},'compiledObjectsOnly':True,'kernelLinked':False,
        'imageBuilt':False,'booted':False,'normalOperationsExecuted':False,'compiledUsefulFit':False,
        'physicalRootRetirementQualified':False,'consumerSelected':False,'productionInstallation':False,
        'whole738Complete':False,'hermetic':False,'compilerImplicitInputsAttested':False,
        'originalStartedMonotonic':started,'originalDeadlineMonotonic':end,'maximumOwnerSeconds':1320,
        'maximumCompileSeconds':1200,'privateScratchRetained':True}
    error=None;tools={};public_sources={}
    def command(stage,*argv,cap=120,root=None):
        require(stage in (REGISTRATION_STAGES if classdir_kernfs else STAGES) and len(commands.records)<MAX_COMMANDS,'fixed-command-count')
        require(time.monotonic()<commands.deadline,'original-deadline')
        commands.root=ROOT if root is None else root
        commands.command_seconds=min(cap,1200)
        receipt['stage']=stage
        return commands.run(stage,*argv)
    try:
        current_inputs=input_files(ROOT)
        source_record={'currentBefore':current_inputs,'currentAfter':None,
            ('current52' if classdir_kernfs else 'current50' if classdir else 'current47'):before,'currentSourceRevision':revision,'originalBaselineSourceRevision':BASELINE}
        write_json(scratch/'source-inputs.json',source_record)
        public_sources['source-inputs.json']=scratch/'source-inputs.json'
        git=shutil.which('git');require(git,'git-tool')
        require(command('source-head',git,'rev-parse','HEAD',cap=15).decode().strip()==revision,'actual-checkout')
        tree_before=command('source-tree',git,'ls-tree','-rz','--full-tree','HEAD',cap=30)
        command('source-clean',git,'diff','--no-ext-diff','--exit-code','HEAD','--',cap=30)
        if classdir_kernfs:
            # ONE exact shallow acquisition, never history search/lazy fallback.
            # A growing current branch is not baseline authority. Same owner,
            # original absolute1320s deadline and single5s reserve apply.
            command('baseline-fetch',git,'-c','gc.auto=0','fetch','--no-tags',
                '--no-recurse-submodules','--depth=1',
                'https://github.com/KirilsTurkins/latent-service-fabric.git',BASELINE,cap=90)
        command('baseline-object',git,'--no-lazy-fetch','cat-file','-e',BASELINE+'^{commit}',cap=15)
        require(command('baseline-tree',git,'rev-parse',BASELINE+'^{tree}',cap=15).decode().strip()==BASELINE_TREE,'original-tree')
        recipe=scratch/'baseline-recipe'
        command('baseline-worktree',git,'-c','gc.auto=0','worktree','add','--detach',recipe,BASELINE,cap=90)
        require(command('baseline-head',git,'rev-parse','HEAD',cap=15,root=recipe).decode().strip()==BASELINE,'baseline-checkout')
        command('baseline-clean-before',git,'diff','--no-ext-diff','--exit-code','HEAD','--',cap=30,root=recipe)
        command('locked-python-dependencies',sys.executable,'-m','pip','install','--requirement',ROOT/'tools/requirements.lock',cap=180)
        command('normal-prerequisite-update','sudo','apt-get','update',cap=180)
        command('normal-prerequisite-install','sudo','apt-get','install','--yes','--no-install-recommends',
            'gcc','make','flex','bison','bc','libelf-dev','libssl-dev','binutils','libc6-dev','curl','xz-utils',cap=600)
        for name in ('gcc','make','as','ld','rustc','tar','curl'):
            found=shutil.which(name);require(found,'normal-tool-'+name)
            tools[name]=Path(found)
            require(tools[name].is_absolute(),'normal-tool-invocation')
        # argv[0] is observable (GCC config text and rustc/rustup proxy mode).
        # Invoke the discovered spelling; hash its real target separately.
        receipt['tools']={n:{'invocationPath':str(q),'resolvedPath':str(q.resolve()),
            **identity(read(q.resolve(),256*1024**2))} for n,q in tools.items()}
        for name in ('gcc','make','as','ld','rustc'):
            raw=command(name+'-version',tools[name],'--version',cap=30)
            receipt.setdefault('toolVersions',{})[name]=raw.decode('utf8','strict').strip()
        require(receipt['toolVersions']['rustc'].startswith('rustc 1.97.1 '),'original-rust-detector')
        manifest=objects.maintained.manifest();archive=scratch/'linux.tar.xz'
        command('official-source',tools['curl'],'--fail','--location','--proto','=https','--tlsv1.2',
            '--max-time','175','--output',archive,manifest['archive']['url'],cap=180)
        require(commands.deadline-time.monotonic()>=180,'source-auth-parent-reserve')
        originals=objects.maintained.authenticate_archive(archive,manifest,
            tuple(sorted(({'net/Kconfig','net/Makefile'}|set(objects.packet_source.fixture()['source']))-set(manifest['source']))))
        require(time.monotonic()<commands.deadline,'source-auth-deadline')
        receipt['originalArchive']=identity(read(archive,objects.maintained.MAX_ARCHIVE))
        extract=scratch/'kernel';extract.mkdir()
        command('extract-source',tools['tar'],'--extract','--xz','--file',archive,'--directory',extract,
            '--no-same-owner','--no-same-permissions',cap=180)
        tree=extract/('linux-'+manifest['version'])
        require(all(read(tree/n,MAX_FILE)==raw for n,raw in originals.items()),'extracted-originals')
        for name,suffix in [('net/Kconfig',objects.KCONFIG),('net/Makefile',objects.MAKEFILE)]:
            raw=originals[name];require(objects.SELECTED.encode() not in raw,'private-config-fresh')
            (tree/name).write_bytes(raw+suffix.encode())
        build=scratch/'objects';common=[tools['make'],'O='+str(build),'ARCH=x86_64','CC='+str(tools['gcc'])]
        command('original-defconfig',*common,'x86_64_defconfig',root=tree)
        base_config=read(build/'.config',MAX_DOCUMENT);public_sources['baseline.config']=build/'.config'
        (scratch/'baseline.config').write_bytes(base_config);public_sources['baseline.config']=scratch/'baseline.config'
        selected=base_config.replace(b'# CONFIG_LSF_STREAM_FACTORY is not set\n',b'CONFIG_LSF_STREAM_FACTORY=y\n')
        require(selected!=base_config,'private-select-only')
        (build/'.config').write_bytes(selected)
        command('selected-olddefconfig',*common,'olddefconfig',root=tree)
        selected=read(build/'.config',MAX_DOCUMENT);require(identity(selected)==CONFIG,'actual-config-byte-drift')
        (scratch/'selected.config').write_bytes(selected);public_sources['selected.config']=scratch/'selected.config'
        receipt['actualConfiguration']=identity(selected)
        baseline_output=scratch/'baseline';baseline_output.mkdir()
        command('pure-baseline',sys.executable,'-B',Path(__file__).resolve(),'--baseline-worker',
            '--recipe',recipe,'--kernel-tree',tree,'--config',scratch/'selected.config','--output',baseline_output,cap=180)
        baseline=json.loads(read(baseline_output/'baseline.json',16*MAX_DOCUMENT))
        require(baseline['sourceRevision']==BASELINE and baseline['tree']==BASELINE_TREE and
            baseline['sourceBefore']==baseline['sourceAfter'] and baseline['actualConfiguration']==CONFIG and
            baseline['compilerInvocations']==baseline['runtimeInvocations']==0 and
            baseline['qualificationProjectionApplied'] is False,'pure-baseline-identity')
        public_sources['baseline-inputs.json']=baseline_output/'baseline.json'
        command('baseline-clean-after',git,'diff','--no-ext-diff','--exit-code','HEAD','--',cap=30,root=recipe)
        require(command('baseline-tree-after',git,'rev-parse','HEAD^{tree}',cap=15,root=recipe).decode().strip()==BASELINE_TREE,'baseline-tree-after')
        values=current_compose(derived_read(baseline_output/'derived',baseline['derived']),tree,
            classdir=classdir,classdir_kernfs=classdir_kernfs)
        rows=derived_write(scratch/'current-derived',values)
        for name,raw in values.items():
            q=tree/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw)
        write_json(scratch/'derived-inputs.json',rows,4*MAX_DOCUMENT);public_sources['derived-inputs.json']=scratch/'derived-inputs.json'
        command('classdir-kernfs-objects' if classdir_kernfs else 'classdir-objects' if classdir else 'eighteen-objects',
            *common,'-j2',*targets,root=tree,cap=1200)
        require(read(build/'.config',MAX_DOCUMENT)==selected,'actual-config-mutated')
        autoconf=read(build/'include/generated/autoconf.h',MAX_DOCUMENT)
        require(b'#define CONFIG_LSF_STREAM_FACTORY 1\n' in autoconf and b'#define CONFIG_RUST ' not in autoconf,
            'actual-selected-autoconf')
        (scratch/'generated-autoconf.h').write_bytes(autoconf);public_sources['generated-autoconf.h']=scratch/'generated-autoconf.h'
        receipt['products']={name:object_identity(build/name) for name in targets}
        require(len(receipt['products'])==len(targets),'nine-exact-products' if classdir_kernfs else 'four-exact-products' if classdir else 'eighteen-exact-products')
        for name in targets:public_sources['objects/'+name]=build/name
        command('source-clean-after',git,'diff','--no-ext-diff','--exit-code','HEAD','--',cap=30)
        require(command('source-tree-after',git,'ls-tree','-rz','--full-tree','HEAD',cap=30)==tree_before,'source-tree-mutated')
        require(command('source-head-after',git,'rev-parse','HEAD',cap=15).decode().strip()==revision,'source-head-mutated')
        receipt['sourceAfter']=selected_sources(ROOT,classdir=classdir,classdir_kernfs=classdir_kernfs)
        require(receipt['sourceAfter']==before and input_files(ROOT)==current_inputs,'current-source-mutated')
        require(time.monotonic()<commands.deadline,'original-deadline')
        source_record.update(currentAfter=current_inputs,currentGitTreeInventory=identity(tree_before))
        write_json(scratch/'source-inputs.json',source_record)
        public_sources['source-inputs.json']=scratch/'source-inputs.json'
        receipt['status']='passed';receipt['stage']='complete'
    except BaseException as failure:
        error=failure;receipt['status']='failed';receipt['failureType']=type(failure).__name__
        # Raw owned command channels carry the actual compiler diagnostic.
        receipt['failureReason']=str(failure)[:1024] if isinstance(failure,ValueError) else getattr(failure,'reason','controller-failed')
    finally:
        receipt['commands']=commands.records
        receipt['ownedProcessCleanupConfirmed']=all(row.get('completed') and row.get('descendantsCleaned') for row in commands.records)
        try:
            write_json(output/'receipt.json',receipt,MAX_DOCUMENT)
            write_json(output/'commands.json',commands.records,MAX_DOCUMENT)
            for name,q in public_sources.items():
                maximum=public_allowed(name,classdir=classdir,classdir_kernfs=classdir_kernfs);require(maximum is not None,'public-source')
                _copy_public(q,output,name,maximum)
            for q in sorted((scratch/'commands/logs').iterdir()):
                name='logs/'+q.name;maximum=public_allowed(name,classdir=classdir,classdir_kernfs=classdir_kernfs);require(maximum is not None,'public-command-channel')
                _copy_public(q,output,name,maximum)
            admit(output,classdir=classdir,classdir_kernfs=classdir_kernfs)
        except BaseException as retention:
            receipt['status']='failed';receipt['retentionFailure']='bounded-public-admission-failed'
            raw=canonical(receipt)
            if len(raw)<=MAX_DOCUMENT:(output/'receipt.json').write_bytes(raw)
            if error is None:error=retention
        # No deletion of scratch/worktree, especially after unknown cleanup.
    if error is not None:raise error
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-commit')
    parser.add_argument('--started',type=float)
    parser.add_argument('--admit',action='store_true')
    parser.add_argument('--classdir',action='store_true',help='fixed private four-object source check only')
    parser.add_argument('--classdir-kernfs',action='store_true',help='fixed private nine-object source check only')
    parser.add_argument('--baseline-worker',action='store_true')
    parser.add_argument('--recipe',type=Path);parser.add_argument('--kernel-tree',type=Path);parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    mode_targets(args.classdir,args.classdir_kernfs)
    require(not ((args.classdir or args.classdir_kernfs) and args.baseline_worker),'one-private-mode')
    if args.admit:
        require(not args.baseline_worker,'one-private-mode')
        try:
            admit(args.output,classdir=args.classdir,classdir_kernfs=args.classdir_kernfs)
        except BaseException:
            # Fixed fallback only; never upload any rejected directory/glob.
            require(not args.output.is_symlink(),'fallback-output-symlink')
            args.output.mkdir(mode=0o700,parents=True,exist_ok=True)
            fallback={'status':'failed','reason':'public-evidence-admission-failed',
                'compilerQualificationClaimed':False,'originalReceiptAvailable':False}
            try:
                original=read(args.output/'receipt.json',MAX_DOCUMENT)
                record=json.loads(original)
                fallback['originalReceiptAvailable']=True
                fallback['originalReceipt']=identity(original)
                for key in ('status','stage','failureType'):
                    value=record.get(key)
                    if type(value) is str and len(value)<=128:
                        fallback['original'+key[0].upper()+key[1:]]=value
            except (ValueError,OSError,TypeError):
                pass
            write_json(args.output/'FAILED.json',fallback,MAX_DOCUMENT)
            if os.environ.get('GITHUB_OUTPUT'):
                with Path(os.environ['GITHUB_OUTPUT']).open('a') as f:f.write('fallback=true\n')
            raise
        if os.environ.get('GITHUB_OUTPUT'):
            with Path(os.environ['GITHUB_OUTPUT']).open('a') as f:f.write('admitted=true\n')
    elif args.baseline_worker:
        require(args.recipe and args.kernel_tree and args.config,'worker-fixed-inputs')
        baseline_worker(args.recipe,args.kernel_tree,args.config,args.output)
    else:run(args.output,args.source_commit,args.started,classdir=args.classdir,classdir_kernfs=args.classdir_kernfs)


if __name__=='__main__':
    main()
