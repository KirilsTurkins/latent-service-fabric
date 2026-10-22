"""Compile four affected maintained cleanup-task/VM/factory units; never install."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import qualify_host_stream_kernel_objects as objects
from tools import host_stream_kernel_guarded_stack as source
from tools import qualify_host_stream_kernel_retirement as previous

task_source = source.prior
retirement_source = task_source.prior

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'feat/stream-kernel-guarded-stack-20261022'
WORKFLOW = '.github/workflows/stream-kernel-cleanup-stack.yml'
PARENT_RECIPE = 'tools/qualify_host_stream_kernel_objects.py'
PARENT_RECIPE_SHA = '2a5f32b7797677ceaf8c4f1f0343859b1456ab00a54ff9ee52516b317e0e9cd7'
RETIREMENT_RECIPE = 'tools/qualify_host_stream_kernel_retirement.py'
RETIREMENT_RECIPE_SHA = 'b32ecdc53ec79f0fa4339e24ef80ffb41f2e72c99b39f2e4abe09b26947060c4'
TARGET = 'net/factory.o'
require = objects.require
paths = objects.paths
maintained = objects.maintained


def object_selection():
    parent = previous.object_selection()
    require(len(parent[TARGET]) == 87, 'cleanup-stack-original-factory-oracle-drift')
    return {
        TARGET: (*parent[TARGET], 'lsf_factory_cleanup_task_reserve',
            'lsf_factory_cleanup_task_claim', 'lsf_factory_cleanup_task_abort',
            'lsf_factory_cleanup_stack_reserve', 'lsf_factory_cleanup_stack_current',
            'lsf_factory_cleanup_stack_finish', 'lsf_factory_cleanup_stack_poison'),
        'kernel/fork.o': ('kernel_clone', 'free_task', 'put_task_stack',
            'lsf_prepaid_cleanup_task_geometry', 'lsf_prepaid_cleanup_dup_task_struct'),
        'kernel/kthread.o': ('kthreadd', 'kthread_worker_fn', 'kthread_stop',
            'kthread_create_worker', 'lsf_prepaid_cleanup_worker_create'),
        'mm/vmalloc.o': ('vunmap_range', 'vfree', 'vunmap',
            'lsf_prepaid_cleanup_stack_geometry', 'lsf_prepaid_cleanup_stack_create',
            'lsf_prepaid_cleanup_stack_abort_unpublished', 'lsf_prepaid_cleanup_stack_foreign_unmap'),
    }


def recipe_inputs():
    selected = (PARENT_RECIPE, RETIREMENT_RECIPE,
        'tools/qualify_host_stream_kernel_cleanup_stack.py', WORKFLOW)
    result = {name: objects.identity(ROOT / name) for name in selected}
    require(result[PARENT_RECIPE]['sha256'] == PARENT_RECIPE_SHA and
        result[RETIREMENT_RECIPE]['sha256'] == RETIREMENT_RECIPE_SHA,
        'cleanup-stack-reviewed-parent-recipe-changed')
    return result


def derive_frozen(tree, original):
    modules = (retirement_source, task_source, source)
    members = tuple(path for module in modules for path in
        (Path(module.__file__).resolve(), module.FIXTURE.resolve()))
    require(all(ROOT in path.parents for path in members), 'cleanup-stack-source-outside-checkout')
    before = {path.relative_to(ROOT).as_posix(): objects.identity(path) for path in members}
    try:
        derived, frozen, selected = objects.recipient_derive_frozen(tree, original)
        # The original context also freezes the six NEW actual C/H files.
        require(len(frozen) == 138 and len(derived) == 189 and len(selected) == 161,
            'cleanup-stack-original-material-membership')
        selected = dict(selected)
        extra = task_source.EXTRAS | set(source.preimages()['source'])
        require(len(extra) == 12 and not (extra & set(selected)),
            'cleanup-stack-fixed-extracted-membership')
        for name in sorted(extra):
            selected[name] = paths.read(tree, name, maintained.MAX_FILE)
        require(sum(map(len, selected.values())) <= maintained.MAX_SELECTED,
            'cleanup-stack-total-selected-byte-bound')
        task_inputs = {name: selected[name] for name in task_source.EXTRAS}
        stack_inputs = {name: selected[name] for name in source.preimages()['source']}
        task_source.authenticate(task_inputs)
        source.authenticate(stack_inputs)
        retired = retirement_source.transform(derived)
        changed = task_source.transform(retired, task_inputs)
        require(len(changed) == 199, 'cleanup-stack-task-output-membership')
        changed = source.transform(changed, stack_inputs)
        require(len(changed) == 208 and len(selected) == 173,
            'cleanup-stack-complete-material-membership')
    finally:
        require(before == {path.relative_to(ROOT).as_posix(): objects.identity(path) for path in members},
            'cleanup-stack-source-changed-during-derivation')
    require(not (set(frozen) & set(before)), 'cleanup-stack-duplicate-source-freeze')
    return changed, {**frozen, **before}, selected


def configuration(before, after):
    for guard in (objects.selected_configuration, objects.netlabel_configuration,
            objects.sidcache_configuration, objects.audit_configuration,
            objects.route_configuration, objects.device_configuration,
            objects.registration_configuration, objects.recipient_configuration):
        guard(before, after)
    require(all(before.get(name) == after.get(name) == 'y' for name in STACK_REQUIRED),
        'cleanup-stack-original-layout-required')
    require(all(before.get(name, 'n') == after.get(name, 'n') == 'n' for name in STACK_DISABLED),
        'cleanup-stack-original-unsupported-layout')


STACK_REQUIRED = ('CONFIG_X86_64', 'CONFIG_VMAP_STACK', 'CONFIG_THREAD_INFO_IN_TASK',
    'CONFIG_SMP', 'CONFIG_NUMA', 'CONFIG_HOTPLUG_CPU')
STACK_DISABLED = ('CONFIG_MEMCG', 'CONFIG_KASAN', 'CONFIG_KMSAN', 'CONFIG_DEBUG_PAGEALLOC',
    'CONFIG_DEBUG_KMEMLEAK', 'CONFIG_PAGE_TABLE_CHECK', 'CONFIG_DEBUG_LOCK_ALLOC')


def generated_configuration(raw):
    required = set((*objects.REQUIRED, objects.SELECTED, 'CONFIG_NETLABEL', 'CONFIG_XFRM',
        *objects.AUDIT_REQUIRED, *objects.DEVICE_REQUIRED, *objects.REGISTRATION_REQUIRED,
        *objects.RECIPIENT_REQUIRED))
    disabled = set((*objects.DEVICE_DISABLED, *objects.REGISTRATION_DISABLED,
        'CONFIG_NET_DEV_REFCNT_TRACKER', 'CONFIG_LWTUNNEL', 'CONFIG_PREEMPT_RT'))
    require(all(('#define ' + name + ' 1\n').encode() in raw for name in required),
        'cleanup-stack-generated-original-code-disabled')
    require(all(('#define ' + name + ' ').encode() not in raw for name in disabled),
        'cleanup-stack-generated-original-disabled-code-drift')
    require(b'#define CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE 256\n' in raw,
        'cleanup-stack-generated-original-sidcache-profile-drift')
    require(all(('#define ' + name + ' 1\n').encode() in raw for name in STACK_REQUIRED) and
        all(('#define ' + name + ' ').encode() not in raw for name in STACK_DISABLED),
        'cleanup-stack-generated-original-layout-drift')


def defined_symbols(raw, expected):
    result = {}
    for line in raw.decode('utf8').splitlines():
        if not line.strip():
            continue
        fields = line.split()
        require(len(fields) == 3 and re.fullmatch(r'[0-9a-fA-F]+', fields[0]) and
            re.fullmatch(r'[ABCDGIRSTVW]', fields[1]) and fields[2] not in result,
            'cleanup-stack-invalid-or-duplicate-external-symbol')
        result[fields[2]] = fields[1]
    require(len(expected) == len(set(expected)) and expected and
        all(result.get(name) == 'T' for name in expected), 'cleanup-stack-original-global-functions-missing')
    return result


# Compile-only const data is appended after the exact reviewed translation
# units. It is NEVER installed or silently labelled production-derived source.
# The runtime x86 extended arch_task_struct_size cannot be a compile-time value.
GEOMETRY = {
    'net/factory.o': ('lsf_cleanup_geometry_factory', (
        ('backingBytes', 'LSF_BACKING_BYTES'), ('infrastructureBytes', 'LSF_FACTORY_INFRA_BYTES'),
        ('bootstrapCeiling', 'LSF_BOOTSTRAP_CEILING'), ('allocationSlots', 'LSF_ALLOCATION_SLOTS'),
        ('factoryBytes', 'sizeof(factory)'), ('deviceStateBytes', 'sizeof(struct lsf_factory_device_state)'),
        ('poolBytes', 'sizeof(struct lsf_prepaid)'),
        ('staticMetadataBytes', 'sizeof(factory) + sizeof(lsf_device_uevent_taps) + 2u * sizeof(void *)'))),
    'kernel/fork.o': ('lsf_cleanup_geometry_task', (
        ('taskStructBaseBytes', 'sizeof(struct task_struct)'), ('cacheLineBytes', 'L1_CACHE_BYTES'),
        ('taskAlignment', '(L1_CACHE_BYTES > ARCH_MIN_TASKALIGN ? L1_CACHE_BYTES : ARCH_MIN_TASKALIGN)'),
        ('stackBytes', 'THREAD_SIZE'), ('stackAlignment', 'THREAD_ALIGN'), ('pageBytes', 'PAGE_SIZE'))),
    'kernel/kthread.o': ('lsf_cleanup_geometry_request', (
        ('requestBytes', 'sizeof(struct lsf_cleanup_request)'),
        ('requestAlignment', '__alignof__(struct lsf_cleanup_request)'),
        ('workerBytes', 'sizeof(struct kthread_worker)'), ('lockClassKeyBytes', 'sizeof(struct lock_class_key)'))),
    'mm/vmalloc.o': ('lsf_cleanup_geometry_mapping', (
        ('mappingMetadataBytes', 'sizeof(struct lsf_cleanup_stack)'),
        ('mappingAlignment', '__alignof__(struct lsf_cleanup_stack)'),
        ('stackRecordBytes', 'sizeof(struct lsf_cleanup_stack) + PAGE_SIZE - 1u + THREAD_SIZE'),
        ('stackPayloadBytes', 'THREAD_SIZE'), ('guardBytes', 'PAGE_SIZE'),
        ('bankAlignmentSlack', 'PAGE_SIZE - 1u'), ('vmStructBytes', 'sizeof(struct vm_struct)'),
        ('vaDescriptorBytes', 'sizeof(struct vmap_area)'), ('leafSlots', 'THREAD_SIZE / PAGE_SIZE + 1u'))),
}
GEOMETRY_MAGIC = 0x4c534647454f4d31
GEOMETRY_SECTION = '.lsf_cleanup_geometry'


def geometry_suffix(target):
    name, fields = GEOMETRY[target]
    return ('\n/* Compile-only measured layout; no runtime or installation result. */\n'
        'const unsigned long long ' + name + '[]\n'
        '__attribute__((used, aligned(8), section("' + GEOMETRY_SECTION + '"))) = {\n'
        '    0x4c534647454f4d31ULL, ' + str(len(fields)) + 'ULL,\n' +
        ''.join('    (unsigned long long)(' + expression + '),\n' for _, expression in fields) + '};\n').encode()


def geometry_values(target, raw):
    _, fields = GEOMETRY[target]
    require(len(raw) == 8 * (len(fields) + 2), 'cleanup-stack-geometry-byte-length')
    values = struct.unpack('<' + 'Q' * (len(fields) + 2), raw)
    require(values[:2] == (GEOMETRY_MAGIC, len(fields)), 'cleanup-stack-geometry-origin')
    return dict(zip((name for name, _ in fields), values[2:]))


def compile_geometry(tree, derived):
    require(set(GEOMETRY) == set(object_selection()), 'cleanup-stack-geometry-target-membership')
    recorded = {}
    for target in GEOMETRY:
        name = target[:-2] + '.c'
        suffix = geometry_suffix(target)
        require(name in derived and (tree / name).read_bytes() == derived[name] and
            GEOMETRY_SECTION.encode() not in derived[name], 'cleanup-stack-geometry-exact-source-prefix')
        (tree / name).write_bytes(derived[name] + suffix)
        recorded[name] = {'reviewedDerivedPrefix': {'bytes': len(derived[name]),
                'sha256': hashlib.sha256(derived[name]).hexdigest()},
            'compileOnlySuffix': {'bytes': len(suffix), 'sha256': hashlib.sha256(suffix).hexdigest()},
            'compiledWholeSource': objects.identity(tree / name),
            'geometrySymbol': GEOMETRY[target][0]}
    return recorded


def run(archive, output):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true' and
        os.environ.get('RUNNER_OS') == 'Linux', 'hosted-linux-only')
    origin = {name: os.environ.get(name) for name in ('GITHUB_REPOSITORY',
        'GITHUB_EVENT_NAME', 'GITHUB_REF_NAME')}
    require(origin == {'GITHUB_REPOSITORY': 'KirilsTurkins/latent-service-fabric',
        'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF_NAME': BRANCH}, 'cleanup-stack-fixed-owning-origin')
    selected_objects, recipe = object_selection(), recipe_inputs()
    value = maintained.manifest()
    output = paths.absolute(output)
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'outside-checkout-output')
    paths.new_directory(output)
    archive = objects.snapshot_archive(archive, output / 'source.tar.xz', value['archive'])
    additional = ('net/Kconfig', 'net/Makefile') + tuple(name
        for name in objects.packet_source.fixture()['source'] if name not in value['source'])
    original = maintained.authenticate_archive(archive, value, additional)
    archive_identity = objects.identity(archive)
    require(archive_identity == {key: value['archive'][key] for key in ('bytes', 'sha256')},
        'archive-identity-drift')
    log, source_root = output / 'commands', output / 'source'
    log.mkdir()
    source_root.mkdir()
    tools = {name: shutil.which(name) for name in ('tar', 'make', 'gcc', 'nm', 'objcopy')}
    require(all(tools.values()), 'missing-kbuild-tool')
    env = objects.build_environment(output)
    env.update(KBUILD_BUILD_USER='lsf-object-check', KBUILD_BUILD_HOST='isolated-ci',
        KBUILD_BUILD_TIMESTAMP='2026-10-21 00:00:00 UTC', KCONFIG_NOTIMESTAMP='1')
    commands = objects.Commands(source_root, log, env, deadline_seconds=900, command_seconds=300)
    receipt = {'schemaVersion': 'lsf.maintained-kernel-cleanup-stack-object-check.v1',
        'status': 'in-progress', 'profile': 'private-unpublished-task-guarded-stack-source',
        'upstreamCommit': maintained.COMMIT, 'archive': archive_identity,
        'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
            timeout=15).decode().strip(), 'origin': origin,
        'manifestSha256': maintained.MANIFEST_SHA, 'recipeInputs': recipe,
        'additionalArchiveSources': list(additional),
        'additionalSourcesIndependentlyGitCorroborated': False,
        'historicalRecipientObjectSource': '1625510fc6b6bcd32505511729ea355cae226b38',
        'historicalRecipientObjects': 56, 'historicalRecipientDefinedSymbols': 243,
        'historicalRecipientBuildReexecuted': False,
        'retirementResumptionSourceImplemented': True,
        'stackMappingSourceImplemented': True, 'linuxMappingExecuted': False,
        'taskCreated': False, 'executorReady': False,
        'runningTaskStackRetirementImplemented': False, 'extendedArchTaskBytesKnown': False,
        'kernelLinked': False, 'kernelBooted': False, 'factoryInstalled': False,
        'productionInstallation': False, 'completeAllocationClosure': False,
        'actualSharedWorkqueueAccounted': False, 'actualRecipientCallbackClosure': False,
        'instrumentationAdmissionQualified': False, 'physicalQueueQualified': False}
    receipt.update({gate: False for gate in retirement_source.GATES})
    stage, failed = 'extract', False
    try:
        commands.run('extract-authenticated-source', tools['tar'], '--extract', '--xz',
            '--file', str(archive), '--directory', str(source_root),
            '--no-same-owner', '--no-same-permissions')
        tree = source_root / ('linux-' + value['version'])
        commands.root = tree
        require(objects.identity(archive) == archive_identity, 'snapshot-changed-during-extraction')
        require(all((tree / name).read_bytes() == raw for name, raw in original.items()),
            'extracted-preimage-drift')
        stage = 'derive'
        derived, frozen, original = derive_frozen(tree, original)
        receipt['cleanupStackSourceFreeze'] = frozen
        receipt['selectedOriginalInputs'] = {name: objects.identity(tree / name) for name in original}
        receipt['changedFactoryFragments'] = sorted(retirement_source.preimages()['selectedWholeDerivedFiles'])
        receipt['derived'] = {}
        for name, raw in derived.items():
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            receipt['derived'][name] = objects.identity(target)
        for name, suffix in (('net/Kconfig', objects.KCONFIG), ('net/Makefile', objects.MAKEFILE)):
            require(objects.SELECTED.encode() not in original[name], 'private-config-already-present')
            (tree / name).write_bytes(original[name] + suffix.encode())
        receipt['compileOnlyTranslationUnitSuffixes'] = compile_geometry(tree, derived)
        build = output / 'objects'
        common = [tools['make'], 'O=' + str(build), 'ARCH=x86_64', 'CC=' + tools['gcc']]
        stage = 'configuration'
        receipt['compiler'] = commands.run('compiler-identity', tools['gcc'], '--version').decode('utf8')
        commands.run('original-defconfig', *common, 'x86_64_defconfig')
        baseline = (build / '.config').read_bytes()
        (output / 'baseline.config').write_bytes(baseline)
        before = objects.configuration(baseline)
        require(before.get(objects.SELECTED) == 'n', 'private-default-enabled')
        selected = baseline.replace(b'# CONFIG_LSF_STREAM_FACTORY is not set\n',
            b'CONFIG_LSF_STREAM_FACTORY=y\n')
        require(selected != baseline, 'missing-private-config')
        (build / '.config').write_bytes(selected)
        commands.run('resolve-selected-config', *common, 'olddefconfig')
        final = (build / '.config').read_bytes()
        configuration(before, objects.configuration(final))
        (output / 'selected.config').write_bytes(final)
        receipt['configuration'] = {'baseline': objects.identity(output / 'baseline.config'),
            'selected': objects.identity(output / 'selected.config'),
            'onlyChangedSymbol': objects.SELECTED, 'symbols': len(before),
            'stackRequiredUnchanged': list(STACK_REQUIRED),
            'stackUnsupportedOptionsRemainDisabled': list(STACK_DISABLED)}
        paths.write_new(output / 'selection.json', (json.dumps(receipt, indent=2) + '\n').encode())
        stage = 'four-affected-objects'
        commands.run('four-affected-real-kbuild-objects', *common, '-j2', *selected_objects)
        generated_configuration((build / 'include/generated/autoconf.h').read_bytes())
        require((build / '.config').read_bytes() == final, 'build-mutated-config')
        receipt['objects'], receipt['geometry'] = {}, {}
        geometry_root = output / 'geometry'
        geometry_root.mkdir()
        for target, expected in selected_objects.items():
            product = build / target
            with product.open('rb') as stream:
                elf = stream.read(64)
            require(len(elf) >= 64 and elf[:6] == b'\x7fELF\x02\x01' and
                struct.unpack_from('<HH', elf, 16) == (1, 62), 'x86-64-relocatable-elf-product-required')
            symbols = commands.run('symbols-' + target.replace('/', '-'), tools['nm'],
                '--extern-only', '--defined-only', str(product))
            actual = defined_symbols(symbols, expected)
            require(actual.get(GEOMETRY[target][0]) == 'R', 'cleanup-stack-global-geometry-symbol-missing')
            checksum = objects.identity(product)
            blob = geometry_root / (target.replace('/', '-').removesuffix('.o') + '.bin')
            commands.run('geometry-' + target.replace('/', '-'), tools['objcopy'],
                '--dump-section', GEOMETRY_SECTION + '=' + str(blob), str(product), '/dev/null')
            require(objects.identity(product) == checksum, 'cleanup-stack-measurement-mutated-object')
            geometry_raw = paths.read(geometry_root, blob.name, 8 * (len(GEOMETRY[target][1]) + 2))
            receipt['geometry'][target] = {'values': geometry_values(target, geometry_raw),
                'binary': objects.identity(blob), 'section': GEOMETRY_SECTION,
                'symbol': GEOMETRY[target][0]}
            receipt['objects'][target] = {**objects.identity(product),
                'requiredDefinedSymbols': list(expected)}
        factory = receipt['geometry'][TARGET]['values']
        fork = receipt['geometry']['kernel/fork.o']['values']
        request = receipt['geometry']['kernel/kthread.o']['values']
        mapping = receipt['geometry']['mm/vmalloc.o']['values']
        require((factory['backingBytes'], factory['infrastructureBytes'],
            factory['bootstrapCeiling'], factory['allocationSlots']) ==
            (524288, 196608, 1048576, 256), 'cleanup-stack-original-bounds-drift')
        require((fork['pageBytes'], fork['stackBytes'], fork['stackAlignment'],
            mapping['guardBytes'], mapping['leafSlots']) == (4096, 16384, 16384, 4096, 5),
            'cleanup-stack-measured-original-layout-drift')
        receipt['geometryScope'] = {'source': 'compile-only const ELF section from four real maintained TUs',
            'extendedArchTaskBytesKnown': False, 'actualRuntimeGeometryFunctionExecuted': False,
            'wholeInfrastructureFitQualified': False,
            'minimumRequestBaseTaskAndStackBytes': sum((value + 63) & ~63 for value in
                (request['requestBytes'], fork['taskStructBaseBytes'], mapping['stackRecordBytes'])),
            'bootstrapStaticBytesIncludingBank': factory['backingBytes'] + factory['staticMetadataBytes']}
        require(objects.identity(archive) == archive_identity, 'archive-changed')
        require(all(objects.identity(tree / name) ==
            receipt['compileOnlyTranslationUnitSuffixes'].get(name, {}).get('compiledWholeSource', row)
            for name, row in receipt['derived'].items()),
            'derived-source-changed')
        require(all(objects.identity(ROOT / name) == row for name, row in frozen.items()),
            'cleanup-stack-source-changed-during-build')
        require(recipe_inputs() == recipe, 'cleanup-stack-recipe-changed-during-build')
        receipt['status'] = 'passed'
        paths.write_new(output / 'qualification.json', (json.dumps(receipt, indent=2) + '\n').encode())
        return receipt
    except BaseException:
        failed = True
        try:
            paths.write_new(output / 'FAILED.json',
                (json.dumps({**receipt, 'status': 'failed', 'stage': stage}, indent=2) + '\n').encode())
        except BaseException:
            pass
        raise
    finally:
        try:
            paths.write_new(output / 'commands.json', (json.dumps(commands.records, indent=2) + '\n').encode())
        except BaseException:
            if not failed:
                raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.archive.resolve(strict=True), args.output)
