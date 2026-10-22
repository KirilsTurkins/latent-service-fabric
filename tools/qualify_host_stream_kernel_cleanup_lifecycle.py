"""Bounded hosted actual-object geometry plus native atomic controls; no boot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import host_stream_kernel_cleanup_programme as programme
from tools import host_stream_kernel_cleanup_atomic_control as atomic

baseline = programme.baseline
objects = baseline.objects
paths = baseline.paths
require = baseline.require
ROOT = programme.ROOT
BRANCH = 'feat/stream-kernel-cleanup-constructors-20261022'
WORKFLOW = '.github/workflows/stream-kernel-cleanup-lifecycle.yml'
# Real defining TUs modified by this source chain; ordinary unchanged Linux TUs
# are not rebuilt. The existing four-object oracle is included intact.
EXTRA_OBJECTS = ('kernel/pid.o', 'kernel/cred.o', 'security/security.o',
    'security/selinux/hooks.o', 'kernel/events/core.o', 'kernel/auditsc.o',
    'mm/mempolicy.o', 'block/blk-ioc.o', 'kernel/cgroup/cgroup.o',
    'kernel/tracepoint.o', 'drivers/connector/cn_proc.o', 'kernel/kprobes.o',
    'kernel/module/kmod.o', 'kernel/umh.o', 'kernel/workqueue.o',
    'drivers/acpi/osl.o', 'lib/idr.o', 'lib/radix-tree.o', 'kernel/taskstats.o', 'kernel/acct.o')


def recipe_inputs():
    names = ('tools/qualify_host_stream_kernel_cleanup_lifecycle.py',
        'tools/host_stream_kernel_cleanup_programme.py',
        'tools/host_stream_kernel_cleanup_atomic_control.py', WORKFLOW,
        'tools/qualify_host_stream_kernel_cleanup_stack.py')
    result = {name: objects.identity(ROOT/name) for name in names}
    require(result['tools/qualify_host_stream_kernel_cleanup_stack.py']['sha256'] ==
        'dcd6300a726cfee952db7913faa6feb1051eafcf6b36c3caf9a95597b7d26a04',
        'cleanup-lifecycle-reviewed-baseline-recipe')
    return result


def run(archive, output):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true' and
        os.environ.get('RUNNER_OS') == 'Linux', 'cleanup-lifecycle-hosted-linux-only')
    origin = {name:os.environ.get(name) for name in ('GITHUB_REPOSITORY','GITHUB_EVENT_NAME','GITHUB_REF_NAME')}
    require(origin == dict(GITHUB_REPOSITORY='KirilsTurkins/latent-service-fabric',
        GITHUB_EVENT_NAME='push',GITHUB_REF_NAME=BRANCH), 'cleanup-lifecycle-fixed-origin')
    selected = {**baseline.object_selection(), **{name:() for name in EXTRA_OBJECTS}}
    require(len(selected) == 24 and set(programme.GEOMETRY) <= set(selected),
        'cleanup-lifecycle-fixed-objects')
    value = baseline.maintained.manifest()
    output = paths.absolute(output)
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'cleanup-lifecycle-outside-checkout-output')
    paths.new_directory(output)
    recipe, local = recipe_inputs(), programme.local_freeze()
    archive = objects.snapshot_archive(archive, output/'source.tar.xz', value['archive'])
    extras = {'net/Kconfig','net/Makefile'} | set(objects.packet_source.fixture()['source'])
    originals = baseline.maintained.authenticate_archive(archive, value,
        tuple(sorted(extras - set(value['source']))))
    archive_identity = objects.identity(archive)
    tools = {name:shutil.which(name) for name in ('tar','make','gcc','nm','objcopy')}
    require(all(tools.values()), 'cleanup-lifecycle-kbuild-tools')
    log, source_root = output/'commands', output/'source'
    log.mkdir(); source_root.mkdir()
    env = objects.build_environment(output)
    env.update(KBUILD_BUILD_USER='lsf-object-check',KBUILD_BUILD_HOST='isolated-ci',
        KBUILD_BUILD_TIMESTAMP='2026-10-23 00:00:00 UTC',KCONFIG_NOTIMESTAMP='1')
    commands = objects.Commands(source_root,log,env,deadline_seconds=1200,command_seconds=600)
    receipt = dict(schemaVersion='lsf.maintained-kernel-cleanup-lifecycle-programme.v1',
        status='in-progress',origin=origin,sourceCommit=subprocess.check_output(
            ['git','rev-parse','HEAD'],cwd=ROOT,timeout=15).decode().strip(),
        archive=archive_identity,upstreamCommit=baseline.maintained.COMMIT,
        recipeInputs=recipe,localSourceFreeze=local,taskCreated=False,kernelLinked=False,
        kernelBooted=False,actualLinuxAtomicExecution=False,actualRcuExecution=False,
        actualIrqExecution=False,actualNativeLedger=False,consumerSelected=False,
        fullConstructorClosure=False,completeAllocationClosure=False,productionInstallation=False)
    stage, failed = 'extract', False
    try:
        commands.run('extract-authenticated-source',tools['tar'],'--extract','--xz',
            '--file',str(archive),'--directory',str(source_root),'--no-same-owner','--no-same-permissions')
        tree = source_root/('linux-'+value['version'])
        commands.root = tree
        require(all((tree/name).read_bytes() == raw for name,raw in originals.items()),
            'cleanup-lifecycle-extracted-preimage')
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
            'cleanup-lifecycle-selected-byte-bound')
        for name,suffix in (('net/Kconfig',objects.KCONFIG),('net/Makefile',objects.MAKEFILE)):
            raw = original_inputs[name]
            require(objects.SELECTED.encode() not in raw,'cleanup-lifecycle-private-config-present')
            (tree/name).write_bytes(raw+suffix.encode())
        build = output/'objects'
        common = [tools['make'],'O='+str(build),'ARCH=x86_64','CC='+tools['gcc']]
        commands.run('compiler-identity',tools['gcc'],'--version')
        commands.run('original-defconfig',*common,'x86_64_defconfig')
        before_raw = (build/'.config').read_bytes()
        (output/'baseline.config').write_bytes(before_raw)
        before = objects.configuration(before_raw)
        require(before.get(objects.SELECTED) == 'n','cleanup-lifecycle-private-default-enabled')
        selected_raw = before_raw.replace(b'# CONFIG_LSF_STREAM_FACTORY is not set\n',b'CONFIG_LSF_STREAM_FACTORY=y\n')
        require(selected_raw != before_raw,'cleanup-lifecycle-missing-private-config')
        (build/'.config').write_bytes(selected_raw)
        commands.run('resolve-selected-config',*common,'olddefconfig')
        final = (build/'.config').read_bytes()
        baseline.configuration(before,objects.configuration(final))
        (output/'selected.config').write_bytes(final)
        # This generated exact selected config is also independently pinned in
        # the authenticated provider source fixture, never a copied local file.
        stage = 'complete-source-composition'
        derived = programme.compose(base,original_inputs,final)
        receipt['selectedOriginalInputs'] = {name:objects.identity(tree/name)
            for name in programme.source_names() if name != 'selected.config'}
        receipt['derived'] = {}
        for name,raw in derived.items():
            target = tree/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(raw)
            receipt['derived'][name] = objects.identity(target)
        receipt['compileOnlyTranslationUnitSuffixes'] = {}
        for target in programme.GEOMETRY:
            name = target[:-2]+'.c'
            suffix = programme.geometry_suffix(target)
            require(name in derived and baseline.GEOMETRY_SECTION.encode() not in derived[name],
                'cleanup-lifecycle-geometry-prefix')
            (tree/name).write_bytes(derived[name]+suffix)
            receipt['compileOnlyTranslationUnitSuffixes'][name] = dict(
                reviewedDerivedPrefix=receipt['derived'][name],
                compileOnlySuffix=dict(bytes=len(suffix),sha256=hashlib.sha256(suffix).hexdigest()),
                compiledWholeSource=objects.identity(tree/name))
        paths.write_new(output/'selection.json',(json.dumps(receipt,indent=2)+'\n').encode())
        stage = 'exact-leaf-native-control'
        control = output/'atomic-control.c'
        control.write_bytes(atomic.program())
        executable = output/'atomic-control'
        commands.run('compile-exact-leaf-atomic-control',tools['gcc'],'-std=c11','-O2',
            '-Wall','-Wextra','-Werror',str(control),'-o',str(executable))
        commands.run('execute-exact-leaf-atomic-control',str(executable))
        receipt['atomicControl'] = dict(source=objects.identity(control),
            executable=objects.identity(executable),passed=True,
            compilerAtomicsExecuted=True,deterministicInterleavings=True,
            actualLinuxAtomicExecution=False,deviceDestructorExecuted=False,
            nativeCapacityRefunded=False)
        stage = '24-affected-objects'
        commands.run('24-affected-real-kbuild-objects',*common,'-j2',*selected)
        baseline.generated_configuration((build/'include/generated/autoconf.h').read_bytes())
        require((build/'.config').read_bytes() == final,'cleanup-lifecycle-build-config-drift')
        receipt['objects'], receipt['geometry'] = {}, {}
        geometry_root = output/'geometry'; geometry_root.mkdir()
        for target,expected in selected.items():
            product = build/target
            with product.open('rb') as stream:
                elf = stream.read(64)
            require(len(elf) == 64 and elf[:6] == b'\x7fELF\x02\x01' and
                struct.unpack_from('<HH',elf,16) == (1,62),'cleanup-lifecycle-real-object')
            symbols = commands.run('symbols-'+target.replace('/','-'),tools['nm'],
                '--extern-only','--defined-only',str(product))
            # Preserve every old four-object function requirement. New objects
            # establish compilation/layout only, with no invented call oracle.
            actual = baseline.defined_symbols(symbols,expected) if expected else {
                line.split()[2]:line.split()[1] for line in symbols.decode().splitlines() if line.strip()}
            checksum = objects.identity(product)
            receipt['objects'][target] = dict(**checksum,requiredDefinedSymbols=list(expected))
            if target in programme.GEOMETRY:
                symbol,fields = programme.GEOMETRY[target]
                require(actual.get(symbol) == 'R','cleanup-lifecycle-geometry-symbol')
                blob = geometry_root/(target.replace('/','-')[:-2]+'.bin')
                commands.run('geometry-'+target.replace('/','-'),tools['objcopy'],
                    '--dump-section',baseline.GEOMETRY_SECTION+'='+str(blob),str(product),'/dev/null')
                require(objects.identity(product) == checksum,'cleanup-lifecycle-object-mutated')
                raw = paths.read(geometry_root,blob.name,8*(len(fields)+2))
                values = struct.unpack('<'+'Q'*(len(fields)+2),raw)
                require(values[:2] == (baseline.GEOMETRY_MAGIC,len(fields)),
                    'cleanup-lifecycle-geometry-framing')
                receipt['geometry'][target] = dict(values=dict(zip((key for key,_ in fields),values[2:])),
                    binary=objects.identity(blob),section=baseline.GEOMETRY_SECTION,symbol=symbol)
        stage = 'fitting-and-final-source-freeze'
        receipt['fitting'] = programme.fitting({key:bound['values'] for key,bound in receipt['geometry'].items()})
        require(objects.identity(archive) == archive_identity,'cleanup-lifecycle-archive-drift')
        require(all(objects.identity(tree/name) == receipt['compileOnlyTranslationUnitSuffixes'].get(
            name,{}).get('compiledWholeSource',bound) for name,bound in receipt['derived'].items()),
            'cleanup-lifecycle-derived-source-drift')
        require(all(objects.identity(ROOT/name) == bound for name,bound in frozen.items()) and
            programme.local_freeze() == local and recipe_inputs() == recipe,
            'cleanup-lifecycle-local-source-drift')
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
