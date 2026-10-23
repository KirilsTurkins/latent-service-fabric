"""Four affected actual defining objects and paid constructor geometry; no boot."""
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
from tools import host_stream_kernel_cleanup_constructor_programme as programme

baseline = programme.baseline
objects = baseline.objects
paths = baseline.paths
require = baseline.require
ROOT = programme.ROOT
BRANCH = 'feat/stream-kernel-cleanup-constructor-cancel-20261023'
WORKFLOW = '.github/workflows/stream-kernel-cleanup-constructor.yml'
# Exactly the four changed defining TUs; no old 24-object or atomic rerun.
REQUIRED = {
    'net/factory.o': ('lsf_factory_cleanup_provider_waiter_current',
        'lsf_factory_cleanup_provider_waiter_cancel'),
    'kernel/kthread.o': ('lsf_prepaid_cleanup_provider_create_full',
        'lsf_prepaid_cleanup_provider_task_create'),
    'kernel/workqueue.o': ('lsf_prepaid_cleanup_provider_queue_pending',
        'lsf_prepaid_cleanup_provider_wait_ready',
        'lsf_prepaid_cleanup_provider_birth_wait_get',
        'lsf_prepaid_cleanup_provider_birth_wait_put',
        'lsf_prepaid_cleanup_provider_birth_remaining'),
    'drivers/acpi/osl.o': ('lsf_prepaid_acpi_provider_queue_changed',),
}


def recipe_inputs():
    names = ('tools/qualify_host_stream_kernel_cleanup_constructor.py',
        'tools/host_stream_kernel_cleanup_constructor_programme.py',
        'tools/host_stream_kernel_cleanup_constructor_wait.py',
        'tools/host_stream_kernel_cleanup_programme.py', WORKFLOW,
        'tools/qualify_host_stream_kernel_cleanup_stack.py',
        'tools/qualify_host_stream_kernel_cleanup_lifecycle.py')
    result = {name: objects.identity(ROOT/name) for name in names}
    require(result['tools/qualify_host_stream_kernel_cleanup_stack.py']['sha256'] ==
        'dcd6300a726cfee952db7913faa6feb1051eafcf6b36c3caf9a95597b7d26a04',
        'cleanup-constructor-reviewed-baseline-recipe')
    return result


def run(archive, output):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true' and
        os.environ.get('RUNNER_OS') == 'Linux', 'cleanup-constructor-hosted-linux-only')
    origin = {name:os.environ.get(name) for name in ('GITHUB_REPOSITORY','GITHUB_EVENT_NAME','GITHUB_REF_NAME')}
    require(origin['GITHUB_REPOSITORY']=='KirilsTurkins/latent-service-fabric' and
        origin['GITHUB_REF_NAME']==BRANCH and origin['GITHUB_EVENT_NAME'] in ('workflow_dispatch','push'),
        'cleanup-constructor-fixed-origin')
    original = baseline.object_selection()
    selected = {name:tuple(original.get(name,()))+REQUIRED[name] for name in programme.TARGETS}
    require(len(selected) == 4 and set(programme.GEOMETRY) == set(selected),
        'cleanup-constructor-fixed-objects')
    value = baseline.maintained.manifest()
    output = paths.absolute(output)
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'cleanup-constructor-outside-checkout-output')
    paths.new_directory(output)
    recipe, local = recipe_inputs(), programme.local_freeze()
    archive = objects.snapshot_archive(archive, output/'source.tar.xz', value['archive'])
    extras = {'net/Kconfig','net/Makefile'} | set(objects.packet_source.fixture()['source'])
    originals = baseline.maintained.authenticate_archive(archive, value,
        tuple(sorted(extras - set(value['source']))))
    archive_identity = objects.identity(archive)
    tools = {name:shutil.which(name) for name in ('tar','make','gcc','nm','objcopy')}
    require(all(tools.values()), 'cleanup-constructor-kbuild-tools')
    log, source_root = output/'commands', output/'source'
    log.mkdir(); source_root.mkdir()
    env = objects.build_environment(output)
    env.update(KBUILD_BUILD_USER='lsf-object-check',KBUILD_BUILD_HOST='isolated-ci',
        KBUILD_BUILD_TIMESTAMP='2026-10-23 00:00:00 UTC',KCONFIG_NOTIMESTAMP='1')
    commands = objects.Commands(source_root,log,env,deadline_seconds=1200,command_seconds=600)
    receipt = dict(schemaVersion='lsf.maintained-kernel-cleanup-constructor-programme.v1',
        status='in-progress',origin=origin,sourceCommit=subprocess.check_output(
            ['git','rev-parse','HEAD'],cwd=ROOT,timeout=15).decode().strip(),
        archive=archive_identity,upstreamCommit=baseline.maintained.COMMIT,
        recipeInputs=recipe,localSourceFreeze=local,taskCreated=False,kernelLinked=False,
        kernelBooted=False,actualLinuxAtomicExecution=False,actualRcuExecution=False,
        actualIrqExecution=False,actualNativeLedger=False,consumerSelected=False,
        initialBirthBounded=False,publicIoCallIntegrated=False,completeBootstrapRemeasured=False,
        fullConstructorClosure=False,completeAllocationClosure=False,productionInstallation=False)
    stage, failed = 'extract', False
    try:
        commands.run('extract-authenticated-source',tools['tar'],'--extract','--xz',
            '--file',str(archive),'--directory',str(source_root),'--no-same-owner','--no-same-permissions')
        tree = source_root/('linux-'+value['version'])
        commands.root = tree
        require(all((tree/name).read_bytes() == raw for name,raw in originals.items()),
            'cleanup-constructor-extracted-preimage')
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
            'cleanup-constructor-selected-byte-bound')
        for name,suffix in (('net/Kconfig',objects.KCONFIG),('net/Makefile',objects.MAKEFILE)):
            raw = original_inputs[name]
            require(objects.SELECTED.encode() not in raw,'cleanup-constructor-private-config-present')
            (tree/name).write_bytes(raw+suffix.encode())
        build = output/'objects'
        common = [tools['make'],'O='+str(build),'ARCH=x86_64','CC='+tools['gcc']]
        commands.run('compiler-identity',tools['gcc'],'--version')
        commands.run('original-defconfig',*common,'x86_64_defconfig')
        before_raw = (build/'.config').read_bytes()
        (output/'baseline.config').write_bytes(before_raw)
        before = objects.configuration(before_raw)
        require(before.get(objects.SELECTED) == 'n','cleanup-constructor-private-default-enabled')
        selected_raw = before_raw.replace(b'# CONFIG_LSF_STREAM_FACTORY is not set\n',b'CONFIG_LSF_STREAM_FACTORY=y\n')
        require(selected_raw != before_raw,'cleanup-constructor-missing-private-config')
        (build/'.config').write_bytes(selected_raw)
        commands.run('resolve-selected-config',*common,'olddefconfig')
        final = (build/'.config').read_bytes()
        baseline.configuration(before,objects.configuration(final))
        (output/'selected.config').write_bytes(final)
        # This generated exact selected config is also independently pinned in
        # the authenticated provider source fixture, never a copied local file.
        stage = 'complete-source-composition'
        fixture_config,receipt['sourceFixtureConfiguration'] = programme.source_fixture_configuration(final)
        # Retain both real selected bytes and the explicit data-only fixture
        # projection. The actual Kbuild configuration is NEVER rewritten.
        (output/'source-fixture.config').write_bytes(fixture_config)
        derived = programme.compose(base,original_inputs,fixture_config)
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
                'cleanup-constructor-geometry-prefix')
            (tree/name).write_bytes(derived[name]+suffix)
            receipt['compileOnlyTranslationUnitSuffixes'][name] = dict(
                reviewedDerivedPrefix=receipt['derived'][name],
                compileOnlySuffix=dict(bytes=len(suffix),sha256=hashlib.sha256(suffix).hexdigest()),
                compiledWholeSource=objects.identity(tree/name))
        paths.write_new(output/'selection.json',(json.dumps(receipt,indent=2)+'\n').encode())
        stage = 'four-affected-objects'
        commands.run('four-affected-real-kbuild-objects',*common,'-j2',*selected)
        baseline.generated_configuration((build/'include/generated/autoconf.h').read_bytes())
        require(b'#define CONFIG_RUST ' not in (build/'include/generated/autoconf.h').read_bytes(),
            'cleanup-constructor-generated-rust-must-remain-unselected')
        require((build/'.config').read_bytes() == final,'cleanup-constructor-build-config-drift')
        receipt['objects'], receipt['geometry'] = {}, {}
        geometry_root = output/'geometry'; geometry_root.mkdir()
        for target,expected in selected.items():
            product = build/target
            with product.open('rb') as stream:
                elf = stream.read(64)
            require(len(elf) == 64 and elf[:6] == b'\x7fELF\x02\x01' and
                struct.unpack_from('<HH',elf,16) == (1,62),'cleanup-constructor-real-object')
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
                require(actual.get(symbol) == 'R','cleanup-constructor-geometry-symbol')
                blob = geometry_root/(target.replace('/','-')[:-2]+'.bin')
                commands.run('geometry-'+target.replace('/','-'),tools['objcopy'],
                    '--dump-section',baseline.GEOMETRY_SECTION+'='+str(blob),str(product),'/dev/null')
                require(objects.identity(product) == checksum,'cleanup-constructor-object-mutated')
                raw = paths.read(geometry_root,blob.name,8*(len(fields)+2))
                values = struct.unpack('<'+'Q'*(len(fields)+2),raw)
                require(values[:2] == (baseline.GEOMETRY_MAGIC,len(fields)),
                    'cleanup-constructor-geometry-framing')
                receipt['geometry'][target] = dict(values=dict(zip((key for key,_ in fields),values[2:])),
                    binary=objects.identity(blob),section=baseline.GEOMETRY_SECTION,symbol=symbol)
        stage = 'fitting-and-final-source-freeze'
        receipt['fitting'] = programme.fitting({key:bound['values'] for key,bound in receipt['geometry'].items()})
        require(objects.identity(archive) == archive_identity,'cleanup-constructor-archive-drift')
        require(all(objects.identity(tree/name) == receipt['compileOnlyTranslationUnitSuffixes'].get(
            name,{}).get('compiledWholeSource',bound) for name,bound in receipt['derived'].items()),
            'cleanup-constructor-derived-source-drift')
        require(all(objects.identity(ROOT/name) == bound for name,bound in frozen.items()) and
            programme.local_freeze() == local and recipe_inputs() == recipe,
            'cleanup-constructor-local-source-drift')
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
